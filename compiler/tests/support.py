"""Test helpers: compile a pack and evaluate its integrity views on DuckDB (a test-only SQL engine)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb

from rezono_compiler import batch, emit, facts, pack, rules_split
from rezono_compiler import rules as ir

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "minimal"


def compile_dir(pack_dir: Path, out: Path) -> dict[str, str]:
    files = emit.compile_pack(pack.read(pack_dir))
    for rel, text in files.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(text.encode("utf-8"))
    return files


def example_copy(tmp_path: Path, example: Path, change) -> Path:
    """An example pack copied with its channel table changed; the standard packs it imports stay where its paths
    point (three levels up)."""
    (tmp_path / "packs").symlink_to(REPO / "packs")
    d = Path(shutil.copytree(example, tmp_path / example.resolve().relative_to(REPO)))
    (d / "channels.yaml").write_text(change((d / "channels.yaml").read_text()))
    return d


def violations(files: dict[str, str], rows: dict[str, list[tuple]]) -> dict[str, set[tuple]]:
    """Load parameters and fact rows, then return every logical check with violations as its rows of
    validation_result, (subject, value) as text (decision E11: one view per check kind)."""
    db = duckdb.connect()
    db.execute(emit.DUCKDB_FUNCTIONS)
    db.execute(files["engine/tables.sql"])
    db.execute(emit.duckdb(files["engine/integrity.sql"]))
    params = json.loads(files["engine/parameters.json"])
    tables = {t: [tuple(r.values()) for r in rs] for t, rs in params.items()} | rows
    for table, rs in tables.items():
        if rs:
            db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
    names = {c["view"] for c in json.loads(files["bundle/schema-bundle.json"])["checks"]}
    if not names:
        return {}
    found = db.execute("SELECT info, subject, value FROM validation_result").fetchall()
    out: dict[str, set[tuple]] = {}
    for info, subject, value in found:
        assert info in names, f"validation_result names {info}, which is no logical check of the bundle"
        out.setdefault(info, set()).add((subject, value))
    assert len(found) == sum(map(len, out.values())), "validation_result must not repeat a violation"
    return out


def value_text(v) -> str:
    """A value as the engine casts it to VARCHAR (DuckDB): booleans in lower case, dates in ISO."""
    return v.isoformat() if hasattr(v, "isoformat") else ("true" if v is True else "false" if v is False else str(v))


def row_text(row: tuple) -> tuple[str, str]:
    """A violation in the shape of a per-slot view of before E11, as its row of validation_result: (id,) has
    no value, (id, n) or (id, v) the value, and a path equation (id, left_end, right_end) both ends."""
    if len(row) == 1:
        return value_text(row[0]), ""
    if len(row) == 2:
        return value_text(row[0]), value_text(row[1])
    return value_text(row[0]), f"{value_text(row[1])} <> {value_text(row[2])}"


def text(by_check: dict[str, set[tuple]]) -> dict[str, set[tuple]]:
    """Violations written per logical check in the per-slot shape, as violations() gives them."""
    return {name: {row_text(r) for r in rows} for name, rows in by_check.items()}


def expected(path: Path) -> dict[str, set[tuple]]:
    return text({view: {tuple(r) for r in rows} for view, rows in json.loads(path.read_text()).items()})


def load(pack_dir: Path, fact_file: Path) -> dict[str, list[tuple]]:
    return facts.load(pack.read(pack_dir), fact_file)


def part_program(prog, names):
    """One part as a program of its own: what it reads from earlier parts becomes an input relation."""
    doc = ir.to_doc(prog)
    reads = {d for n in names for d in prog.deps(n)}
    rels = []
    for r in doc["relations"]:
        if r["name"] in names:
            rels.append(r)
        elif r["name"] in reads:
            rels.append({"name": r["name"], "role": "base", "key": r["key"], **({"values": r["values"]} if "values" in r else {})})
    rules = [dict({k: v for k, v in r.items() if k != "witness"}) for r in doc["rules"] if r["head"]["relation"] in names]
    return ir.load(ir.with_strata({"format": ir.FORMAT, "pack": "part", "relations": rels, "rules": rules}))


def typed(prog, name, rows):
    rel = prog.relations[name]
    types = [c.type for c in rel.key + rel.values]
    return [[int(v) if t == "integer" else v for v, t in zip(r, types)] for r in rows]


def run_split(model, files: dict[str, str], rows: dict[str, list[tuple]]):
    """The rule parts as engine/pipelines.json cuts them, on DuckDB, in their order. `integrity` computes the
    seal from the fact rows and hands it on through its own export view (engine/integrity-export.sql),
    decoded as the relay decodes it; each part gets only the tables the plan sends it and what earlier
    pipelines export. Returns every derived relation (as batch.read) and what `integrity` forwarded."""
    plan = json.loads(files["engine/pipelines.json"])
    prog = ir.load(model.rules)
    sent = {t: [tuple(r.values()) for r in rs] for t, rs in emit.parameters(model).items()} | rows
    forwarded: dict[str, list[tuple]] = {}
    integrity = plan["pipelines"][0]
    assert integrity["name"] == "integrity"
    if integrity["exports"]:
        db = duckdb.connect()
        db.execute(emit.DUCKDB_FUNCTIONS)
        for f in integrity["sql"]:
            db.execute(emit.duckdb(files[f]))
        for table, rs in sent.items():
            if rs and table in integrity["tables"]:
                db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
        db.execute(f"INSERT INTO {emit.q(plan['epoch_table'])} VALUES (1)")
        stream = db.execute(f"SELECT * FROM {emit.q(plan['export_view'])}").fetchall()
        assert ("#epoch", "1") in {r[:2] for r in stream}
        for rel, *cells in stream:
            if rel != "#epoch":
                forwarded.setdefault(rel, []).append(rules_split.decode(prog, rel, cells))
    known: dict[str, set[tuple]] = {}
    for p in plan["pipelines"]:
        if not p["views"]:
            continue
        sub = part_program(prog, p["views"])
        data = {t: sorted(set(sent.get(t, [])), key=repr) for t in p["tables"]}
        for r in p["imports"]:
            data[r] = forwarded.get(r, []) if r in integrity["exports"] else typed(prog, r, known[r])
        con = batch.connect(sub, data)
        batch.compute(con, sub)
        known.update(batch.read(con, sub))
    return known, forwarded
