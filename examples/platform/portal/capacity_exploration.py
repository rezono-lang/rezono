"""Evaluate a written platform capacity exploration and publish its checked threshold."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import lru_cache
import json
import os
from pathlib import Path
import shutil

import duckdb
import yaml
from rezono_canon import canonical_sha256
from rezono_compiler import batch as compiler_batch
from rezono_compiler import calc, emit, explain, scenarios, seal, source_writer, writer
from rezono_compiler import checks as check_meta
from rezono_compiler import facts as fact_files
from rezono_compiler import pack as packs
from rezono_compiler import rules as ir
from rezono_compiler import rules_dl
from rezono_compiler import sources as provenance
from rezono_publisher import access, batch, publish

FORMAT = "rezono.capacity-exploration/1"
KNOWLEDGE_TIME = "2026-02-01T00:00:00Z"


@lru_cache(maxsize=1)
def _runtime_metadata() -> tuple[str, dict, dict]:
    """Process-constant compiler hash, build record, and engine component."""
    return (
        canonical_sha256(batch.compiler_parts()),
        batch.build_record(),
        batch.engine_component(),
    )


def _load_exploration(tables: dict[str, list[tuple]], exploration_id: str) -> tuple[str, str, list[int]]:
    """Extract pool, target request, and ascending numeric candidate capacities."""
    explorations = {row[0] for row in tables.get("capacity_exploration", ())}
    if exploration_id not in explorations:
        raise KeyError(f"unknown capacity_exploration {exploration_id!r}")

    pools = [row[1] for row in tables.get("capacity_exploration__pool", ()) if row[0] == exploration_id]
    if len(pools) != 1:
        raise ValueError(f"capacity_exploration {exploration_id!r} must name exactly one pool, got {len(pools)}")
    pool = str(pools[0])

    requests = [row[1] for row in tables.get("capacity_exploration__request", ()) if row[0] == exploration_id]
    if len(requests) != 1:
        raise ValueError(f"capacity_exploration {exploration_id!r} must name exactly one request, got {len(requests)}")
    request = str(requests[0])

    values = sorted({
        int(row[1])
        for row in tables.get("capacity_exploration__values", ())
        if row[0] == exploration_id
    })
    if not values:
        raise ValueError(f"capacity_exploration {exploration_id!r} has no candidate values")

    return pool, request, values


_VALID_ROLE_MODES = frozenset({access.COMPLETE, access.FILTERED})
# Without a base manifest or explicit role_mode, only the standalone operator role (when not
# declared as a pack role or named in access rules) defaults to complete; all other roles fail
# closed to access.FILTERED.
_STANDALONE_COMPLETE_ROLES = frozenset({"operator"})


def _declared_filtered_roles(tables: dict[str, list[tuple]] | None, prog) -> set[str]:
    """Roles named in pack role facts or as constants in may_read / may_read_full rules."""
    roles: set[str] = set()
    if tables:
        roles |= {str(row[0]) for row in tables.get(access.ROLE, ()) if row}
        roles |= {str(row[0]) for row in tables.get(access.CAPABILITY, ()) if row}
    if prog is not None:
        for rule in prog.rules.values():
            head = rule.head
            if head.relation in {access.ACCESS, access.READ_FULL} and head.terms:
                first = head.terms[0]
                if not ir.is_var(first):
                    roles.add(str(first))
    return roles


def _role_mode(
    base: dict | None,
    role: str,
    *,
    role_mode: str | None = None,
    tables: dict[str, list[tuple]] | None = None,
    prog=None,
) -> str:
    """Resolve the publication access mode for `role` fail-closed."""
    if role_mode is not None and role_mode not in _VALID_ROLE_MODES:
        raise ValueError(f"unknown role_mode {role_mode!r}")

    if base is not None:
        role_snaps = [snap for snap in base.get("snapshots", ()) if snap.get("role") == role]
        if not role_snaps:
            raise publish.Blocked(f"role {role!r} is not published in {base['id']}")
        modes = {access.COMPLETE if snap.get("complete") is True else access.FILTERED for snap in role_snaps}
        if len(modes) != 1:
            raise publish.Blocked(f"role {role!r} has inconsistent access modes in {base['id']}")
        resolved = next(iter(modes))
        if role_mode is not None and role_mode != resolved:
            raise publish.Blocked(
                f"role {role!r} requested mode {role_mode!r} does not match {base['id']} ({resolved!r})"
            )
        return resolved

    if role_mode is not None:
        return role_mode

    if role in _STANDALONE_COMPLETE_ROLES and role not in _declared_filtered_roles(tables, prog):
        return access.COMPLETE
    return access.FILTERED


def _prepare_candidate(pack_dir: Path, lay: writer.Layout, pool: str, capacity: int,
                       proposal: str, knowledge_time: str) -> tuple[Path, Path, set[str]]:
    """Copy the pack into a fresh work dir and apply the candidate pool_cores assumption."""
    work = writer.work_dir()
    try:
        copied = writer.checkout(pack_dir, work)
        delta = {
            "format": writer.FORMAT,
            "changes": [{
                "op": "set",
                "kind": "pool_cores",
                "key": pool,
                "slot": "cores",
                "value": str(capacity),
            }],
        }
        stated = source_writer.stated(proposal, knowledge_time)
        texts, _ = writer.apply_delta(copied, delta, lay=lay, stated=stated)
        if texts:
            writer.write_files(copied, texts)
        changed = {rel for rel in texts if rel.endswith(".yaml") and not rel.endswith(".sources.yaml")}
        return work, copied, changed
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def _run_rules_for_candidate(
    *,
    model: packs.Pack,
    prog,
    calc_program,
    db_rows: dict[str, list[tuple[str, ...]]],
    facts: dict[str, list],
    checks: list[dict],
    copied: Path,
    changed_files: set[str],
    base_sources_by_file: dict[str, list[dict]],
    params: dict[str, list[tuple]],
    tables_sql: str,
) -> tuple[dict[str, list[tuple[str, ...]]], list[dict], list[dict], list[dict], dict[str, list], list[dict], str]:
    """Run Datalog rules, witnesses, and fact provenance for one candidate."""
    rows = dict(db_rows)
    candidate_checks = list(checks)
    calc_witnesses, witnesses, protected = [], [], {}
    if prog is not None:
        protected = {n: [] for n in sorted(rules_dl.PROTECTED) if n in prog.relations}
        for name in protected:
            key = [(c.name, c.type) for c in prog.relations[name].key]
            if name in rules_dl.base_tables(model) or name in rows or key != rules_dl.PROTECTED[name]:
                raise publish.Blocked(
                    f"rezono:evidence: {name} is a protected admission input, but the pack has it "
                    "as a table of its own; only `.decl` with the fixed signature declares it"
                )
        for name in protected:
            rows[name] = []
        con = compiler_batch.connect(prog, scenarios.rule_rows(model, prog, facts | protected))
        try:
            def run_calc():
                calc_db = duckdb.connect()
                try:
                    calc_db.execute(emit.DUCKDB_FUNCTIONS)
                    calc_db.execute(tables_sql)
                    for table, rs in sorted((params | facts).items()):
                        if rs:
                            ph = ", ".join("?" * len(rs[0]))
                            calc_db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({ph})", rs)
                    return batch.calculate(calc_program, calc_db, con, rows)
                finally:
                    calc_db.close()

            calc_witnesses = compiler_batch.phases(
                con, prog, calc_program, run_calc, batch.compute_rules,
            ) or []
            derived = compiler_batch.read(con, prog)
            for name in sorted(n for n, r in prog.relations.items() if r.invariant):
                n = len(derived.get(name, ()))
                candidate_checks.append({"name": name, "status": "red" if n else "green", "violations": n})
            candidate_checks += batch.rule_checks(con, prog)
            thetas = compiler_batch.witnesses(con, prog)
            ex = explain.Explainer(prog, compiler_batch.read(con, prog, prog.base_used()) | derived, thetas)
            witnesses = [
                ex.instance(prog.rules[rid], dict(zip(prog.rules[rid].variables, theta)))
                for rid in sorted(thetas)
                for theta in thetas[rid]
            ]
            for name in sorted(derived):
                rows[name] = sorted(derived[name])
        finally:
            con.close()
    elif calc_program is not None:
        with closing(duckdb.connect()) as calc_db, closing(duckdb.connect()) as rule_db:
            calc_db.execute(emit.DUCKDB_FUNCTIONS)
            calc_db.execute(tables_sql)
            for table, rs in sorted((params | facts).items()):
                if rs:
                    ph = ", ".join("?" * len(rs[0]))
                    calc_db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({ph})", rs)
            calc_witnesses = batch.calculate(calc_program, calc_db, rule_db, rows)

    entries = []
    for rel, file_entries in sorted(base_sources_by_file.items()):
        if rel in changed_files:
            entries.extend(provenance.file_entries(model, copied / rel, relative=Path(rel)))
        else:
            entries.extend(file_entries)
    for rel in sorted(changed_files - set(base_sources_by_file)):
        entries.extend(provenance.file_entries(model, copied / rel, relative=Path(rel)))
    fact_sources = provenance.collected(entries)
    candidate_checks.append(batch.origin_check(model, fact_sources, copied))
    pack_sha = batch.tree_sha256(copied)
    return rows, candidate_checks, witnesses, calc_witnesses, protected, fact_sources, pack_sha


def publish_exploration(
    pack_directory,
    file_store,
    exploration_id: str,
    role: str,
    role_mode: str | None = None,
) -> str:
    """Evaluate a written capacity_exploration in ascending order and publish its checked report."""
    pack_dir = Path(pack_directory)
    lay = writer.layout(pack_dir)
    model = lay.pack
    if model.meta["theory"]:
        raise publish.Blocked("a theory pack cannot publish an instance")
    schemas = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted((pack_dir / "schema").glob("*.yaml"))]
    if batch.unchecked_invariants(schemas):
        raise publish.Blocked("the schema declares invariants (annotation `invariants`) that the engine does not check yet")

    base_facts_by_file: dict[str, dict[str, list[tuple]]] = {}
    merged_tables: dict[str, list[tuple]] = {}
    for file_path in fact_files.files(pack_dir):
        rel = file_path.relative_to(pack_dir).as_posix()
        loaded = fact_files.load(model, file_path)
        base_facts_by_file[rel] = loaded
        for table, rows in loaded.items():
            merged_tables.setdefault(table, []).extend(rows)

    base_sources_by_file: dict[str, list[dict]] = {}
    for path, dataset in fact_files.files_with_datasets(pack_dir):
        rel = path.relative_to(pack_dir).as_posix()
        base_sources_by_file[rel] = provenance.file_entries(model, path, relative=Path(rel), dataset=dataset)

    pool, request, values = _load_exploration(merged_tables, exploration_id)
    pack_name = model.meta["name"]

    compiled_files = emit.compile_pack(model)
    tables_sql = emit.duckdb(compiled_files["engine/tables.sql"])
    integrity_sql = emit.duckdb(compiled_files["engine/integrity.sql"])
    logical_checks = json.loads(compiled_files["bundle/schema-bundle.json"])["checks"]
    params = {t: [tuple(r.values()) for r in rs] for t, rs in emit.parameters(model).items()}
    prog = ir.load(model.rules) if model.rules else None
    calc_program = calc.build(model, model.calc) if model.calc is not None else None
    seal_views = [n for n, _ in seal.views(model)]
    definition_sha256 = batch.definition_sha256(pack_dir)
    columns = batch.columns(model)
    assets = batch.asset_files(pack_dir)
    compiler_sha256, build, engine = _runtime_metadata()
    parents = {k: v.parent for k, v in sorted(model.kinds.items()) if v.parent}

    base = publish.newest_main(file_store, pack_name) if hasattr(file_store, "list") else None
    base_manifest = base["id"] if base is not None else ""
    base_epoch = int(base["epoch"]) if base is not None else 0
    knowledge_time = str(base["knowledge_time"]) if base is not None else KNOWLEDGE_TIME
    resolved_role_mode = _role_mode(base, role, role_mode=role_mode, tables=merged_tables, prog=prog)

    prepared: list[tuple[int, str, Path, Path, set[str]]] = []
    candidate_inputs: list[tuple[dict[str, list[tuple[str, ...]]], dict[str, list], list[dict]]] = []
    try:
        for capacity in values:
            proposal = f"{exploration_id}-{capacity}"
            work, copied, changed = _prepare_candidate(pack_dir, lay, pool, capacity, proposal, knowledge_time)
            prepared.append((capacity, proposal, work, copied, changed))

        # Populate DuckDB integrity views once, then swap only changed tables per candidate.
        db = duckdb.connect()
        try:
            db.execute(emit.DUCKDB_FUNCTIONS)
            db.execute(tables_sql)
            db.execute(integrity_sql)
            current_facts: dict[str, list] = {t: list(rs) for t, rs in merged_tables.items()}
            for table, rs in sorted((params | current_facts).items()):
                if rs:
                    ph = ", ".join("?" * len(rs[0]))
                    db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({ph})", rs)
            all_tables = [
                r[0] for r in db.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE' ORDER BY table_name"
                ).fetchall()
                if not r[0].startswith(check_meta.P)
            ] + list(seal_views)
            metadata_tables = [
                r[0] for r in db.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE' ORDER BY table_name"
                ).fetchall()
                if r[0].startswith(check_meta.P)
            ]
            check_metadata = {
                t: [tuple(batch.text(v) for v in r) for r in db.execute(f"SELECT * FROM {emit.q(t)}").fetchall()]
                for t in metadata_tables
            }
            base_rows = {
                t: sorted({tuple(batch.text(v) for v in r) for r in db.execute(f"SELECT * FROM {emit.q(t)}").fetchall()})
                for t in all_tables
            }

            for _, _, _, copied, changed in prepared:
                facts: dict[str, list] = {}
                for rel, file_tables in sorted(base_facts_by_file.items()):
                    loaded = fact_files.load(model, copied / rel) if rel in changed else file_tables
                    for table, rs in loaded.items():
                        facts.setdefault(table, []).extend(rs)
                for rel in sorted(changed - set(base_facts_by_file)):
                    for table, rs in fact_files.load(model, copied / rel).items():
                        facts.setdefault(table, []).extend(rs)

                diff_tables = {
                    t for t in set(current_facts) | set(facts)
                    if current_facts.get(t) != facts.get(t)
                }
                for table in sorted(diff_tables):
                    db.execute(f"DELETE FROM {emit.q(table)}")
                    new_rows = (params | facts).get(table, [])
                    if new_rows:
                        ph = ", ".join("?" * len(new_rows[0]))
                        db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({ph})", new_rows)
                current_facts = facts

                counts = (
                    dict(db.execute("SELECT info, COUNT(*) FROM validation_result GROUP BY info").fetchall())
                    if logical_checks else {}
                )
                checks = [
                    {"name": c["view"], "status": "red" if counts.get(c["view"]) else "green",
                     "violations": counts.get(c["view"], 0)}
                    for c in logical_checks
                ]
                cand_rows = dict(base_rows)
                rows_diff = {
                    t for t in set(merged_tables) | set(facts)
                    if merged_tables.get(t) != facts.get(t)
                }
                for table in sorted(rows_diff | set(seal_views)):
                    cand_rows[table] = sorted({
                        tuple(batch.text(v) for v in r)
                        for r in db.execute(f"SELECT * FROM {emit.q(table)}").fetchall()
                    })
                candidate_inputs.append((cand_rows, facts, checks))
        finally:
            db.close()

        def compute_one(item):
            (_, _, _, copied, changed), (cand_rows, facts, checks) = item
            return _run_rules_for_candidate(
                model=model,
                prog=prog,
                calc_program=calc_program,
                db_rows=cand_rows,
                facts=facts,
                checks=checks,
                copied=copied,
                changed_files=changed,
                base_sources_by_file=base_sources_by_file,
                params=params,
                tables_sql=tables_sql,
            )

        pairs = list(zip(prepared, candidate_inputs))
        if len(pairs) == 1:
            computed = [compute_one(pairs[0])]
        else:
            workers = min(len(pairs), os.cpu_count() or 1)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                computed = list(executor.map(compute_one, pairs))

        epochs: list[publish.Epoch] = []
        for (capacity, proposal, _, _, _), (rows, checks, witnesses, calc_witnesses, protected, fact_sources, pack_sha) in zip(prepared, computed):
            epochs.append(
                publish.Epoch(
                    pack=pack_name,
                    theory=model.meta["theory"],
                    epoch=base_epoch + 1,
                    knowledge_time=knowledge_time,
                    pack_sha256=pack_sha,
                    definition_sha256=definition_sha256,
                    columns=columns | {n: (None,) * len(rules_dl.PROTECTED[n]) for n in protected},
                    compiler_sha256=compiler_sha256,
                    build=build,
                    schema_version=str(model.meta.get("version", "")),
                    engine=engine,
                    sources=[("exploration", f"{exploration_id}:{capacity}")],
                    checks=checks,
                    kinds=frozenset(model.kinds),
                    rows=rows,
                    witnesses=witnesses,
                    check_metadata=check_metadata,
                    parents=parents,
                    proposal=proposal,
                    base_manifest=base_manifest,
                    bundle=compiled_files["bundle/schema-bundle.json"],
                    rules=compiled_files.get("ir/rules.json") or batch.EMPTY_RULES,
                    sweeps=compiled_files.get("ir/sweeps.json", ""),
                    seals=tuple(s.kind for s in model.seals),
                    calc=compiled_files.get("ir/calc.json", ""),
                    calc_witnesses=calc_witnesses,
                    assets=assets,
                    fact_sources=fact_sources,
                    evidence=None,
                )
            )
    finally:
        for _, _, work, _, _ in prepared:
            shutil.rmtree(work, ignore_errors=True)

    samples: list[dict] = []
    previous_manifest = base
    for (capacity, _, _, _, _), epoch_obj in zip(prepared, epochs):
        manifest = publish.publish(epoch_obj, file_store, {role: resolved_role_mode}, reuse=previous_manifest)
        previous_manifest = manifest
        mid = manifest["id"]
        objs = publish.role_objects(file_store, pack_name, mid, role)
        outcome_key = objs.get("relations/request_outcome.json")
        witnesses_key = objs.get("witnesses.json")
        if outcome_key is None or witnesses_key is None:
            raise KeyError(f"manifest {mid!r} role {role!r} lacks request_outcome or witnesses")

        outcomes = [
            row["key"][1]
            for row in json.loads(file_store.get(outcome_key))
            if len(row["key"]) == 2 and row["key"][0] == request
        ]
        if len(outcomes) != 1:
            raise ValueError(
                f"expected unique request_outcome for {request!r} at capacity {capacity}, got {outcomes!r}"
            )
        outcome = outcomes[0]

        witnesses = json.loads(file_store.get(witnesses_key))["witnesses"]
        matching = [
            w for w in witnesses
            if w["conclusion"]["relation"] == "request_outcome"
            and json.loads(w["conclusion"]["key"]) == [request, outcome]
        ]
        if len(matching) != 1 or not matching[0].get("premises"):
            raise ValueError(
                f"expected unique witness with premises for {(request, outcome)!r} at capacity {capacity}"
            )
        witness = matching[0]

        samples.append({
            "capacity": capacity,
            "manifest": mid,
            "outcome": outcome,
            "witness": witness,
        })

    first_change = None
    for before, after in zip(samples, samples[1:]):
        if before["outcome"] != after["outcome"]:
            first_change = {
                "before": {
                    "capacity": before["capacity"],
                    "manifest": before["manifest"],
                    "witness": before["witness"],
                },
                "after": {
                    "capacity": after["capacity"],
                    "manifest": after["manifest"],
                    "witness": after["witness"],
                },
            }
            break

    report = {
        "format": FORMAT,
        "pack": pack_name,
        "exploration": exploration_id,
        "pool": pool,
        "request": request,
        "role": role,
        "samples": samples,
        "first_change": first_change,
    }
    data = publish.canonical(report)
    key = f"{pack_name}/explorations/{exploration_id}/{role}/{publish.sha256(data)}.json"
    file_store.put_new(key, data)
    return key
