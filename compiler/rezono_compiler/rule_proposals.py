"""Check an imported-rule proposal against an immutable pack copy."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex

from . import batch, facts, modules, pack, rule_proposal_oracle, rules, rules_dl, scenarios, sources


DUCKDB_VERSION = "2.0.0"  # requirements/run.txt and requirements/dev.txt


def row_refs(relation: str, rows) -> list[dict]:
    return [{"relation": relation, "key": canonical_json(row)} for row in sorted(rows)]


def definitions(model) -> dict:
    worlds = rules_dl.base_worlds(model)
    tables = {name: {"name": name, "role": "base", "world": worlds.get(name, "closed"),
                     "key": [{"name": column, "type": type_} for column, type_ in columns]}
              for name, columns in rules_dl.base_tables(model).items() if all(type_ for _, type_ in columns)}
    tables.update({relation["name"]: relation for relation in (model.rules or {}).get("relations", [])})
    return tables


def sealed_tables(model) -> set[str]:
    """Sealed facts need a separate proof of which records stand in a closed period."""
    return {table for seal in model.seals for table in
            (seal.kind, seal.refused, seal.accepted, seal.row_sha256, *seal.tables,
             *(table for part in seal.parts for table in (part.kind, part.accepted, *part.tables)))}


def candidate_program(model, target: str, filename: str, text: str):
    relations = definitions(model)
    sealed = sealed_tables(model)
    if (target not in rules_dl.base_worlds(model) or target not in relations or target in sealed
            or relations[target]["world"] != "closed"):
        raise ValueError(f"{target} must be a complete typed fact relation")
    statements = rules_dl.parse_file(text, filename)
    declared = [statement[1] for statement in statements if statement[0] == "decl"]
    if len(set(declared)) != len(declared) or set(declared) & relations.keys():
        raise ValueError("proposal declarations must be unique and separate from the pinned relations")
    for statement in statements:
        if statement[:2] == ("io", "input") and any(name not in relations for name in statement[2]):
            raise ValueError("proposal inputs must come from pinned relations")
        if statement[0] == "decl" and any(statement[5:]):
            raise ValueError("proposal declarations cannot change the pack's rule semantics")
    explicit = [name for statement in statements if statement[:2] == ("io", "output") for name in statement[2]]
    outputs = explicit or declared
    if len(outputs) != 1 or outputs[0] not in declared:
        raise ValueError("declare one proposal output, or select it with .output")
    output = outputs[0]
    inputs = {name: [(column["name"], column["type"]) for column in relation["key"]]
              for name, relation in relations.items() if not relation.get("values")}
    made = rules_dl.read_program(text, filename, inputs, "proposal")
    inferred = {entry["name"]: entry for entry in made["relations"] if entry["role"] == "derived"}
    if not any(rule["head"]["relation"] == output for rule in made["rules"]):
        raise ValueError("the proposal output needs a rule")
    if [c["type"] for c in inferred[output]["key"]] != [c["type"] for c in relations[target]["key"]]:
        raise ValueError("proposal output columns must match the target relation's types and order")
    relations.update(inferred)
    by_head = {}
    original = (model.rules or {}).get("rules", [])
    # Use a distinct rule ID namespace even when a declaration and an existing rule ID have the same name.
    used_ids = {rule["id"] for rule in original}
    for rule in made["rules"]:
        name = "proposal_" + rule["id"]
        while name in used_ids:
            name = "proposal_" + name
        rule["id"] = name
        rule.pop("witness", None)
        used_ids.add(name)
    for rule in (*original, *made["rules"]):
        by_head.setdefault(rule["head"]["relation"], []).append(rule)
    needed, pending = set(), [output]
    while pending:
        name = pending.pop()
        if name in needed:
            continue
        relation = relations[name]
        if (name in sealed or relation["role"] == "calc"
                or any(relation.get(key) for key in ("absence", "outcome", "closes", "values"))):
            raise ValueError(f"{name} needs proof inputs unsupported by the proposal comparison")
        needed.add(name)
        for rule in by_head.get(name, ()):
            pending.extend(item["relation"] for item in rule.get("body", []) + rule.get("aggregates", []))
    selected = [rule for name in sorted(needed) for rule in by_head.get(name, ())]
    # World and strata are checked again after binding the candidate to its actual pack dependencies.
    chosen = [{key: value for key, value in relations[name].items()
               if key != "world" or relations[name]["role"] == "base"} for name in sorted(needed)]
    program = rules.load(rules.with_strata({"format": rules.FORMAT, "pack": model.meta["name"],
                                            "relations": chosen, "rules": selected}))
    if target in needed:
        for rule in program.rules.values():
            closed = [lit.atom.relation for lit in rule.body if lit.polarity == "negative"]
            closed.extend(aggregate.atom.relation for aggregate in rule.aggregates)
            if any(program.reaches(target, relation) for relation in closed):
                raise ValueError("a withheld relation cannot establish absence or aggregate completeness")
    return program, relations[target], output


def typed_rows(rows, columns) -> set[tuple]:
    return {tuple(int(value) if column["type"] == "integer" else str(value)
                  for value, column in zip(row, columns, strict=True)) for row in rows}


def compare(program, data: dict, output: str, columns) -> tuple[set[tuple], set[tuple]]:
    try:
        with closing(batch.connect(program, data, threads=1)) as connection:
            batch.compute(connection, program)
            calculated = batch.read(connection, program, [output])[output]
    except duckdb.Error as error:
        raise ValueError(f"DuckDB failed: {error}") from error
    independent = rule_proposal_oracle.evaluate(program, data, output)
    return typed_rows(calculated, columns), typed_rows(independent, columns)


def exact_origin(model, documents: dict, locator: dict, relation: str, values: tuple) -> bool:
    """Check an explicit fact-file pointer against the original admitted record and cell."""
    name, found, pointer = locator["position"].partition("#")
    if locator["kind"] != "pack" or not found or name != locator["name"] or name not in documents:
        return False
    parts = pointer.split("/")
    if len(parts) not in (3, 4) or parts[0] != "":
        return False
    kind, index = (part.replace("~1", "/").replace("~0", "~") for part in parts[1:3])
    slot = parts[3].replace("~1", "/").replace("~0", "~") if len(parts) == 4 else None
    records = documents[name].get(kind) or []
    if not index.isascii() or not index.isdecimal() or len(index) > len(str(len(records))):
        return False
    if str(int(index)) != index or int(index) >= len(records):
        return False
    record = records[int(index)]
    if slot is not None and slot not in record:
        return False
    match = False

    def observe(table, row, row_kind, _id, slot_name, _context):
        nonlocal match
        if table == relation and row_kind == kind and (slot is None or slot_name == slot) and tuple(row) == values:
            match = True

    facts.walk(facts.schema(model), kind, record, on_row=observe)
    return match


def retained_sources(model, directory: Path, files, target: str, remainder: set) -> tuple[list[dict], set]:
    if not remainder:
        return [], set()
    names = {path.relative_to(directory).as_posix(): facts.document(path, model)
             for path in files if path.parent == directory / "facts"}
    entries = {(entry["row"]["relation"], entry["row"]["key"]): entry for entry in sources.read(model, directory)}
    retained, gaps = [], set()
    for row in sorted(remainder):
        entry = entries.get((target, canonical_json(row)), {})
        verified = [source for source in entry.get("sources", [])
                    if exact_origin(model, names, source, target, row)]
        if verified and "reason" in entry:
            retained.append(entry | {"sources": verified})
        else:
            gaps.add(row)
    return retained, gaps


def check(pack_dir: Path, target: str, candidate: Path) -> dict:
    raw = candidate.read_bytes()
    text = raw.decode("utf-8")
    with TemporaryDirectory(prefix="rezono-rule-proposal-") as temp:
        directory = modules.copy_closure(pack_dir, Path(temp) / "pack")
        model = pack.read(directory)
        files = facts.files(directory)
        original_rows = scenarios.rows_of(model, [record for path in files for record in scenarios.records(model, path)])
        companions = (path.with_suffix(".sources.yaml") for path in files)
        inputs = set(files) | {path for path in companions if path.is_file()}
        report = {"relation": target, "definition_sha256": modules.pack_hash(directory),
                  "facts_sha256": canonical_sha256({p.relative_to(directory).as_posix(): sha256_hex(p.read_bytes())
                                                    for p in sorted(inputs)}),
                  "candidate_sha256": sha256_hex(raw)}
        _, imports = modules.closure(directory)
        report["imports"] = [{"name": name, "definition_sha256": modules.pack_hash(path)} for name, path in imports]
        program, relation, output = candidate_program(model, target, candidate.name, text)
        columns = relation["key"]
        original = typed_rows(original_rows.get(target, ()), columns)
        held_out = {name: rows for name, rows in original_rows.items() if name != target}
        data = scenarios.rule_rows(model, program, held_out)
        if duckdb.__version__ != DUCKDB_VERSION:
            raise ValueError(f"rule proposals require the repository-pinned DuckDB {DUCKDB_VERSION}")
        rule_proposal_oracle.verified_interpreter()
        explained, other = compare(program, data, output, columns)
        if explained != other:
            return report | {"status": "engine_disagreement", "duckdb_only": row_refs(target, explained - other),
                             "souffle_only": row_refs(target, other - explained)}
        if excess := explained - original:
            return report | {"status": "excess_rows", "excess": row_refs(target, excess)}
        remainder = original - explained
        retained, gaps = retained_sources(model, directory, files, target, remainder)
        report |= {"explained": row_refs(target, explained), "retained": retained}
        if gaps:
            return report | {"status": "provenance_gap", "gaps": row_refs(target, gaps)}

        final_data = scenarios.rule_rows(model, program, held_out | {target: sorted(remainder)})
        left, right = compare(program, final_data, output, columns)
        if left != right:
            return report | {"status": "engine_disagreement", "duckdb_only": row_refs(target, left - right),
                             "souffle_only": row_refs(target, right - left)}
        final = left | remainder
        if final != original:
            return report | {"status": "replacement_changed", "missing": row_refs(target, original - final),
                             "excess": row_refs(target, final - original)}
        charged = {name: sorted(rows) for name, rows in final_data.items()}
        candidate_bytes = len(canonical_bytes({candidate.name: text})) + len(canonical_bytes(charged))
        explained_bytes = len(canonical_bytes(sorted(explained)))
        return report | {"status": "eligible" if candidate_bytes < explained_bytes else "not_smaller",
                         "sizes": {"candidate_bytes": candidate_bytes, "explained_bytes": explained_bytes},
                         "charged": charged}
