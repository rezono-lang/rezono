"""Check confidence-qualified candidates from a retained AnyBURL snapshot."""

import argparse
from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from rezono_compiler import facts, modules, pack, rule_proposal_oracle, rule_proposals, rules_dl, scenarios
from rezono_compiler.__main__ import main as compiler
from rezono_publisher.batch import text

from project import KIND, catalog, decode, digest, write_json


VARIABLE = re.compile(r"[A-Z][A-Z0-9_]*")
TERM = r"(?:[A-Z][A-Z0-9_]*|v_[0-9a-f]+)"
ATOM = re.compile(rf"([a-z][a-z0-9_]*)\(({TERM}),\s*({TERM})\)")
TYPES = {"BIGINT": "number", "VARCHAR": "symbol"}


def atom(source, tables):
    match = ATOM.fullmatch(source.strip())
    if match is None:
        raise ValueError("not a supported positive binary atom")
    relation, left, right = match.groups()
    if relation != "is":
        if relation not in tables or len(tables[relation]) != 2:
            raise ValueError("not a projected slot relation")
        return relation, (left, right)
    if VARIABLE.fullmatch(right):
        raise ValueError("a variable kind cannot be written as one named relation")
    domain, relation = decode(right)
    if domain != KIND or relation not in tables or len(tables[relation]) != 1:
        raise ValueError("not a projected kind relation")
    return relation, (left,)


def quoted(value):
    if value == "_" or value.startswith("?") or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("a projected constant cannot be written in the rule language")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return '"' + escaped + '"'


def translate(source, tables, targets, known):
    head, separator, body = source.partition("<=")
    if not separator or not body.strip():
        raise ValueError("a candidate must have a nonempty Horn body")
    parts = re.split(r"(?<=\)),\s*", body.strip())
    output, terms = atom(head, tables)
    if (output if len(terms) == 2 else "is") not in targets:
        raise ValueError("the head does not name a closed training target")
    variables = {}

    def render(terms, domains):
        rendered = []
        for term, domain in zip(terms, domains, strict=True):
            if domain[1] not in TYPES:
                raise ValueError(f"column type {domain[1]} is outside the rule language")
            if VARIABLE.fullmatch(term):
                if variables.setdefault(term, domain) != domain:
                    raise ValueError("the same variable joins two distinct encoded domains")
                rendered.append(term.lower())
            else:
                actual, value = decode(term)
                if actual != domain:
                    raise ValueError("a constant belongs to a different encoded domain")
                rendered.append(str(int(value)) if domain[1] == "BIGINT" else quoted(value))
        return ", ".join(rendered)

    literals = []
    for item in parts:
        relation, arguments = atom(item, tables)
        literals.append(f"{relation}({render(arguments, tables[relation])})")
    if any(VARIABLE.fullmatch(term) and term not in variables for term in terms):
        raise ValueError("a head variable does not occur in the body")
    name = "anyburl_candidate"
    while name in known:
        name += "_rule"
    signature = ", ".join(f"c{i}: {TYPES[domain[1]]}" for i, domain in enumerate(tables[output])
                          if domain[1] in TYPES)
    head = render(terms, tables[output])
    rule = f".decl {name}({signature})\n{name}({head}) :- {', '.join(literals)}.\n"
    return output, rule


def published_rows(raw, tables):
    rows = {relation: set() for relation in tables}
    for line in raw.decode("utf-8").splitlines():
        left, predicate, right = line.split("\t")
        if predicate == "is":
            domain, relation = decode(right)
            if domain != KIND:
                raise ValueError("is must name a kind")
            tokens = (left,)
        else:
            relation, tokens = predicate, (left, right)
        columns = []
        for token, domain in zip(tokens, tables[relation], strict=True):
            actual, value = decode(token)
            if actual != domain:
                raise ValueError(f"{relation}: a published triple has the wrong domain")
            columns.append(value)
        row = tuple(columns)
        if row in rows[relation]:
            raise ValueError(f"{relation}: duplicate published triple")
        rows[relation].add(row)
    return rows


def counterexamples(model, rows, expected, target, report, rule, filename):
    status = report["status"]
    if status == "engine_disagreement":
        raise ValueError(f"independent evaluators disagree: {report}")
    if status == "invalid":
        return {}
    explained = {tuple(json.loads(ref["key"])) for ref in report.get("explained", [])}
    extra = set()
    if status == "excess_rows":
        # The CLI rejects excess before reporting the explained subset. Recover the entire
        # withheld prediction in both ordinary engines for the near-miss measurement.
        program, relation, output = rule_proposals.candidate_program(model, target, filename, rule)
        withheld = {key: value for key, value in rows.items() if key != target}
        data = scenarios.rule_rows(model, program, withheld)
        left, right = rule_proposals.compare(program, data, output, relation["key"])
        if left != right:
            raise ValueError("the excess-row measurement found an engine disagreement")
        predictions = {tuple(text(value) for value in row) for row in left}
        extra = predictions - expected
        if extra != {tuple(json.loads(ref["key"])) for ref in report["excess"]}:
            raise ValueError("the withheld measurement disagrees with the CLI counterexample")
        explained = predictions & expected
    missing = expected - explained
    difference = len(extra) + len(missing)
    return {"original_count": len(expected), "missing": sorted(missing), "excess": sorted(extra),
            "possible_exceptions": 0 < 20 * difference <= len(expected)}


def replay(pack_dir, projection, rules, destination):
    rule_proposal_oracle.verified_interpreter()
    model = pack.read(pack_dir)
    tables = catalog(model)
    known = rule_proposals.definitions(model)
    metadata = json.loads((projection / "input.json").read_bytes())
    raw = (projection / "facts.tsv").read_bytes()
    if digest(raw) != metadata["triples_sha256"] or modules.pack_hash(pack_dir) != metadata["definition_sha256"]:
        raise ValueError("the replay inputs differ from the pinned publication")
    expected = published_rows(raw, tables)
    rows = scenarios.rows_of(model, [record for path in facts.files(pack_dir)
                                     for record in scenarios.records(model, path)])
    for relation, original in expected.items():
        if original != {tuple(text(value) for value in row) for row in rows.get(relation, ())}:
            raise ValueError(f"{relation}: the replay inputs differ from the original rows")
    targets = set(metadata["closed_targets"])
    worlds = rules_dl.base_worlds(model)
    if any((relation != "is" and worlds[relation] != "closed") or
           (relation == "is" and any(worlds[kind] != "closed" for kind in model.kinds))
           for relation in targets):
        raise ValueError("the replay metadata includes an open training target")
    snapshot = rules.read_bytes()
    results = []
    with TemporaryDirectory(prefix="anyburl-candidates-") as temp:
        candidate = Path(temp) / "candidate.dl"
        for index, line in enumerate(snapshot.decode("utf-8").splitlines(), 1):
            predicted, correct, confidence, source = line.split("\t", 3)
            score = Decimal(confidence)
            if not score.is_finite() or not 0 <= score <= 1 or not 0 <= int(correct) <= int(predicted):
                raise ValueError(f"invalid candidate score on raw line {index}")
            if score < Decimal("0.9"):
                continue
            record = {"line": index, "confidence": confidence, "source": source}
            try:
                relation, rule = translate(source, tables, targets, known)
            except ValueError as error:
                results.append(record | {"status": "unexpressible", "reason": str(error)})
                continue
            candidate.write_bytes(rule.encode("utf-8"))
            with redirect_stdout(StringIO()) as captured:
                code = compiler(["check-rule-proposal", str(pack_dir), relation, str(candidate)])
            report = json.loads(captured.getvalue())
            if (code == 0) != (report["status"] == "eligible"):
                raise ValueError("the rule proposal status and CLI exit code disagree")
            measured = counterexamples(model, rows, expected[relation], relation, report, rule, candidate.name)
            results.append(record | {"relation": relation, "rule": rule, "check": report, **measured})
    write_json(destination, {"raw_sha256": digest(snapshot), "raw_rules": len(snapshot.splitlines()),
                             "input": metadata, "candidates": results})


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("pack", type=Path)
    cli.add_argument("projection", type=Path)
    cli.add_argument("rules", type=Path)
    cli.add_argument("report", type=Path)
    args = cli.parse_args()
    replay(args.pack, args.projection, args.rules, args.report)
