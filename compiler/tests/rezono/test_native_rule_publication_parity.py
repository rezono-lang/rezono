"""Migration parity from authored Datalog and typed Rezono through the checked publisher."""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from rezono_compiler import batch, explain, pack, rules, scenarios
from rezono_publisher import batch as publisher_batch
from rezono_publisher import publish, store
from support import FIXTURE


PAIR = Path(__file__).parent / "fixtures" / "native_publication_parity"
ROLES = {"checker": "complete", "viewer": "may_read"}
TIME = "2026-01-01T00:00:00Z"
RULES = ("listed", "listed_count")
BASE = """alpha:
  - {id: a1, title: open}
  - {id: a2, title: closed}
beta:
  - {id: b, alpha: a2}
"""
OVERLAY = """alpha:
  - {id: a1, title: closed}
  - {id: a2, title: open}
  - {id: a3, title: open}
"""
AFTER = OVERLAY + """beta:
  - {id: b, alpha: a2}
"""
ACCESS = """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "alpha", x) :- alpha__title(x, "open").
may_read("viewer", "beta", x) :- beta(x).
"""
SENTENCES = """@locale en
---
arrow.total = {{Every {$kind} has exactly one {$arrow}.}}
arrow.partial = {{Every {$kind} has at most one {$arrow}.}}
attribute.total = {{Every {$kind} has exactly one {$attribute}.}}
attribute.partial = {{Every {$kind} has at most one {$attribute}.}}
is_a = {{Every {$kind} is a {$parent}.}}
unique_key = {{{$key} belongs to at most one {$kind}.}}
path_equation = {{For every {$kind}: {$equation}.}}
"""
MESSAGES = {
    "listed": "rule.listed = {{This item is listed.}}",
    "listed_count": "rule.listed_count = {{This is the number of listed items.}}",
}


def write(directory, name, contents):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents.encode("utf-8"))


def example(directory, representation):
    shutil.copytree(FIXTURE / "schema", directory / "schema")
    shutil.copyfile(FIXTURE / "channels.yaml", directory / "channels.yaml")
    write(directory, "pack.yaml", 'name: minimal\nversion: "0"\ndefault_language: en\nimports: []\n')
    write(directory, "facts/base.yaml", BASE)
    write(directory, "scenarios/relist.yaml", OVERLAY)
    write(directory, "rules/access.dl", ACCESS)
    write(directory, "messages/en.mf2", SENTENCES + "\n".join(MESSAGES.values()) + "\n")
    if representation == "legacy":
        source = "rules/eligibility.dl"
        write(directory, source, (PAIR / "eligibility.dl").read_text(encoding="utf-8"))
    else:
        source = "rezono/eligibility.rezono"
        write(directory, source, (PAIR / "eligibility.rezono").read_text(encoding="utf-8"))
        module_form = (PAIR / "eligibility.json").read_text(encoding="utf-8")
        write(directory, "rezono/eligibility.json", module_form)
        meta = (directory / "pack.yaml").read_text(encoding="utf-8")
        write(directory, "pack.yaml", meta + "\nrezono:\n"
              "  - {module: rezono/eligibility.rezono, form: rezono/eligibility.json, layer: facts}\n")
    return source


def digest(data):
    return sha256(data).hexdigest()


def artifact(bucket, entry):
    data = bucket.get(entry["uri"].split("/", 3)[3])
    assert data is not None
    assert digest(data) == entry["sha256"]
    return json.loads(data)


def definition_pin(directory):
    # The only files defining the test pack are its root metadata and these five source families.
    paths = [directory / name for name in ("pack.yaml", "channels.yaml")]
    for folder in ("schema", "rules", "rezono", "labels", "messages"):
        paths.extend(p for p in (directory / folder).glob("*") if p.is_file())
    files = {p.relative_to(directory).as_posix(): digest(p.read_bytes()) for p in paths}
    return digest(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())


def fact_origins(directory, rows, sources):
    lines = (directory / "facts/base.yaml").read_text(encoding="utf-8").splitlines()
    origins = {(e["row"]["relation"], tuple(json.loads(e["row"]["key"]))): e["sources"] for e in sources}
    for relation in ("alpha", "alpha__title", "beta", "beta__alpha"):
        for key in rows[relation]:
            [line] = [i for i, text in enumerate(lines, 1) if f"{{id: {key[0]}," in text]
            assert origins[(relation, key)] == [{"kind": "pack", "name": "facts/base.yaml", "position": str(line)}]
    observed = {name: set() for name in ("alpha", "alpha__title", "beta", "beta__alpha")}
    for relation, key in origins:
        if relation in observed:
            observed[relation].add(key)
    assert observed == {name: rows[name] for name in observed}


def premise(relation, *key):
    return {"row": {"relation": relation, "key": json.dumps(key, separators=(",", ":"))},
            "polarity": "positive", "stratum": 0}


def check_publication(directory, source, bucket, manifest, titles, listed, count, numbers):
    assert manifest["definition_sha256"] == definition_pin(directory)
    assert manifest["sources"] == [{"source_id": "rules", "position": digest((directory / source).read_bytes())}]
    assert {entry["status"] for entry in manifest["checks"]} == {"green"}
    compiled = {entry["file"]: artifact(bucket, entry) for entry in manifest["compiled"]}
    bundle = compiled["bundle/schema-bundle.json"]
    # Rule IDs and stable IDs are local choices of each representation; resolve them by relation.
    published_rules = {entry["relation"]: entry for entry in bundle["rules"] if entry["relation"] in RULES}
    assert set(published_rules) == set(RULES)
    rule_relation = {entry["id"]: entry["relation"] for entry in bundle["rules"]}
    assert published_rules["listed_count"]["aggregates"] == [{"position": 0, "relation": "listed", "function": "count"}]
    message = next(entry["resource"] for entry in bundle["messages"] if entry["lang"] == "en").splitlines()
    for name, number in zip(RULES, numbers):
        rule = published_rules[name]
        assert rule["message"] == f"rule.{name}" and MESSAGES[name] in message
        assert rule["origin"] == {"file": source, "line": str(number)}
        line = (directory / source).read_text(encoding="utf-8").splitlines()[number - 1]
        column = line.index(f"{name}(") + 1
        assert rule["span"] == {"file": source, "line": str(number), "column": str(column)}

    all_rows = {
        "alpha": {(item,) for item in titles},
        "alpha__title": set(titles.items()),
        "beta": {("b",)},
        "beta__alpha": {("b", "a2")},
        "listed": {(item,) for item in listed},
        "listed_count": {("b", str(count))},
    }
    viewer_rows = all_rows | {
        "alpha": all_rows["listed"],
        "alpha__title": {(item, "open") for item in listed},
        "beta__alpha": {("b", "a2")} if "a2" in listed else set(),
        "listed_count": set(),
    }

    seen = {}
    for role, expected in (("checker", all_rows), ("viewer", viewer_rows)):
        refs = {entry["relation"]: entry for entry in manifest["snapshots"] if entry["role"] == role}
        rows = {name: {tuple(row["key"]) for row in artifact(bucket, refs[name])}
                for name in expected}
        assert rows == expected, (role, rows)
        assert refs["listed_count"]["full"] == (role == "checker")
        [source_set] = [entry for entry in manifest["fact_sources"] if entry["role"] == role]
        fact_origins(directory, rows, artifact(bucket, source_set))
        [witness_set] = [entry for entry in manifest["witnesses"] if entry["role"] == role]
        witnesses = artifact(bucket, witness_set)
        assert witnesses["hidden"] == []
        # Accumulate every alternative of a conclusion before comparing its grounds.
        evidence = {}
        for w in witnesses["witnesses"]:
            if w["conclusion"]["relation"] in RULES:
                evidence.setdefault((w["conclusion"]["relation"], tuple(json.loads(w["conclusion"]["key"]))), []).append(w)
        assert set(evidence) == {(name, key) for name in RULES for key in expected[name]}
        for item in listed:
            [witness] = evidence["listed", (item,)]
            assert rule_relation[witness["rule_id"]] == "listed"
            assert [binding["value"] for binding in witness["bindings"]] == [item]
            assert witness["premises"] == [premise("alpha", item), premise("alpha__title", item, "open")]
        if role == "checker":
            [witness] = evidence["listed_count", ("b", str(count))]
            assert rule_relation[witness["rule_id"]] == "listed_count"
            assert sorted(binding["value"] for binding in witness["bindings"]) == sorted(["b", str(count)])
            assert witness["premises"] == [premise("beta", "b")]
            [group] = witness["aggregates"]
            contributors = [[json.dumps([item])] for item in sorted(listed)]
            assert group == {
                "relation": "listed", "position": 0, "group_key": "[]", "count": count,
                "contributors_sha256": digest(json.dumps(contributors, separators=(",", ":")).encode()),
                "result": f"known:{count}",
            }
        seen[role] = (rows, grounds(evidence))

    prefix = f"minimal/{manifest['id']}/viewer/publication/"
    index = json.loads(bucket.get(prefix + "index.json"))
    assert index["role"] == "viewer"
    [entry] = [entry for entry in index["objects"] if entry["name"] == "rows.json"]
    view = artifact(bucket, entry)["$rows"]
    visible = {(row["$kind"], row["$id"]) for row in view if row["$kind"] != "MayRead"}
    expected_view = {("Beta", "b")} | {("Alpha", item) for item in listed} | {
        ("Listed", json.dumps([item])) for item in listed
    }
    assert visible == expected_view

    # Compare rows, grounds and each rule's head arity across source paths. Rule IDs, variable names, clause
    # order and logical column types are local to each representation (decisions/language-expression-semantics.md §4).
    return seen, {name: len(rule["head"]["terms"]) for name, rule in published_rules.items()}


def grounds(evidence):
    """The union of signed premises and group certificates over all alternatives of each conclusion."""
    union = {}
    for conclusion, alternatives in evidence.items():
        reads = set()
        for witness in alternatives:
            reads.update((p["polarity"], p["row"]["relation"], p["row"]["key"]) for p in witness["premises"])
            reads.update(("group", g["relation"], g["group_key"], g["count"], g["contributors_sha256"])
                         for g in witness.get("aggregates", ()))
        union[conclusion] = reads
    return union


def changed_epoch(model, states, template):
    """Replay the scenario's changed input rows on the normal incremental rule path."""
    [(_, initial), (_, after)] = states
    prog = rules.load(model.rules)
    before = scenarios.rule_rows(model, prog, initial)
    later = scenarios.rule_rows(model, prog, after)
    changed = {name for name in before if before[name] != later[name]}
    assert changed == {"alpha", "alpha__title"}
    with batch.connect(prog, before) as con:
        batch.compute(con, prog)
        for relation in sorted(changed):
            for row in sorted(set(before[relation]) - set(later[relation])):
                batch.apply(con, prog, relation, row, "delete")
            for row in sorted(set(later[relation]) - set(before[relation])):
                batch.apply(con, prog, relation, row, "insert")
        batch.compute(con, prog, relations=prog.downstream(changed))
        derived = batch.read(con, prog)
        bindings = batch.witnesses(con, prog)

    evaluator = explain.Explainer(prog, {**later, **derived}, bindings)
    witnesses = [evaluator.instance(prog.rules[name], dict(zip(prog.rules[name].variables, values)))
                 for name, instances in bindings.items() for values in instances]
    return replace(template, rows=template.rows | {name: sorted(rows) for name, rows in derived.items()},
                   witnesses=witnesses)


def build(directory, source, number):
    return publisher_batch.epoch(directory, epoch=number, knowledge_time=TIME,
                                 sources=[("rules", digest((directory / source).read_bytes()))])


def published_meaning(tmp_path, representation):
    directory = tmp_path / "minimal"
    source = example(directory, representation)
    numbers = (2, 4) if representation == "legacy" else (4, 6)
    initial = build(directory, source, 1)
    bucket = store.FileStore(tmp_path / "batch")
    m1 = publish.publish(initial, bucket, ROLES, forms=True)
    before = check_publication(directory, source, bucket, m1, {"a1": "open", "a2": "closed"}, ("a1",), 1, numbers)

    model = pack.read(directory)
    states = scenarios.states(model, directory)
    assert [name for name, _ in states] == ["0-base", "relist"]
    changed = tmp_path / "changed" / "minimal"
    shutil.copytree(directory, changed)
    write(changed, "facts/base.yaml", AFTER)
    fresh = build(changed, source, 2)
    expected_state = ({"a1": "closed", "a2": "open", "a3": "open"}, ("a2", "a3"), 2, numbers)
    m2 = publish.publish(fresh, bucket, ROLES, reuse=m1, forms=True)
    after = check_publication(changed, source, bucket, m2, *expected_state)

    incremental = store.FileStore(tmp_path / "incremental")
    base = publish.publish(initial, incremental, ROLES, forms=True)
    m2_delta = publish.publish(changed_epoch(model, states, fresh), incremental, ROLES, reuse=base, forms=True)
    assert check_publication(changed, source, incremental, m2_delta, *expected_state) == after
    assert m2_delta == m2
    return before, after


class NativePublicationError(Exception):
    """The native source reached the parity gate but could not publish the required result."""


@pytest.mark.xfail(
    strict=True,
    raises=NativePublicationError,
    reason="M3: Publish native rules through the normal pack compiler in compiler/rezono_compiler/. "
           "Read decisions/language-native-rules.md sections 3, 5, 7 and 11, and the migration comparison in "
           "decisions/language-expression-semantics.md §4. Waits for test_expression_python_branch_bindings and "
           "test_order_check_ordinary_filtered_count, which lower the slot-call conjunction and the count on "
           "the ordinary path. The two source fixtures are authored, so state projection and the corpus "
           "converter are not needed here.",
)
def test_native_rule_publication_parity(tmp_path):
    expected = published_meaning(tmp_path / "legacy", "legacy")
    try:
        actual = published_meaning(tmp_path / "native", "native")
        assert actual == expected
    except (pack.CompileError, publish.Blocked, AssertionError) as exc:
        raise NativePublicationError(str(exc)) from exc
