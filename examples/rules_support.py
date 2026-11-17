"""Shared by the rule tests of the example packs: discovery, fact states, and the batch run per state."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from rede_compiler import batch, calc, checks, explain, pack, scenarios, seal
from rede_compiler import rules as ir

ROOT = Path(__file__).parent
# Every example pack, at any depth, with rules and facts.
RULED = sorted(p.parent for p in ROOT.rglob("pack.yaml")
               if (p.parent / "rules").is_dir() and (p.parent / "facts").is_dir() and "expected" not in p.parts)


def name(p: Path) -> str:
    return str(p.relative_to(ROOT))


class State:
    """One fact state of a pack, computed on the batch backend (DuckDB), with the calculation in its phase
    when a rule reads a selection. `base` is what the rules read: the tables and the selections. With a
    calculation, `calc_witnesses` are its witnesses (decision W12) and `tables` the rows of every table and
    calculation view as a publication holds them (`batch.calculate`), so an epoch check recomputes them."""

    def __init__(self, model, prog, label, rows, calculation=None):
        self.label, self.prog = label, prog
        # refused and accepted input of a seal (decision E3): base relations the compiler makes
        self.seal = {r: {tuple(str(x) for x in row) for row in rs} for r, rs in seal.rows(model, rows).items()}
        con, self.calc_witnesses, calculated = batch.run(model, prog, rows, calculation)
        selections = {n: sorted(rs) for n, rs in batch.read(con, prog, prog.calc_inputs()).items()}
        self.base = scenarios.rule_rows(model, prog, rows) | selections
        self.derived = batch.read(con, prog)
        self.rows = batch.read(con, prog, prog.base_used() + prog.calc_inputs()) | self.derived
        self.explainer = explain.Explainer(prog, self.rows, batch.witnesses(con, prog))
        self.tables, self.calc_ir = {}, calc.to_doc(calculation) if calculation is not None else None
        if calculation is not None:  # the publisher's tables: every base table but the check metadata
            db = batch.database(model, rows)
            names = [r[0] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_type = "
                                              "'BASE TABLE' ORDER BY table_name").fetchall() if not r[0].startswith(checks.P)]
            self.tables = {t: sorted({tuple(seal.text(v) for v in r) for r in db.execute(f'SELECT * FROM "{t}"').fetchall()})
                           for t in names} | calculated

    def proof(self, relation, key):
        """The chosen proof of one derived row, with the calculation witnesses it reaches."""
        return explain.with_calculation(self.explainer.proof(relation, key, self.label), self.calc_witnesses)

    def manifest(self):
        """A manifest with a complete snapshot of every relation, and a reader for its URIs: of every rule
        relation, and with a calculation every table and calculation view as a publication holds it."""
        snaps = {r: self.explainer.snapshot(r).encode() for r in sorted(self.prog.relations) if r not in self.tables}
        snaps |= {t: snapshot(rs) for t, rs in sorted(self.tables.items())}
        manifest = {"id": self.label, "snapshots": [
            {"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
             "sha256": hashlib.sha256(b).hexdigest()} for r, b in snaps.items()]}
        return manifest, snaps.__getitem__


def snapshot(rows) -> bytes:
    """Rows of canonical text as a complete snapshot: each row its key, sorted, as a publication writes it."""
    lines = [json.dumps({"key": list(r)}, ensure_ascii=False, separators=(",", ":"))
             for r in sorted(set(rows), key=explain.key_text)]
    return ("[\n" + ",\n".join(lines) + ("\n" if lines else "") + "]\n").encode()


def states(example: Path):
    """The pack, its rule program and each fact state computed. A committed example pack (RULED) is computed once
    per session: every rule test of the pack reads the same states. Any other directory, such as a copy a test
    changes in its own tmp_path, is computed for that call and not kept. The cache held every copy until the
    session ended, one more pack's states for each test that made a copy, and `full (rest)` lost its runner to
    that memory (15-11-2026)."""
    key = Path(example).resolve()
    return _committed(key) if key in _RULED else _computed(key)


_RULED = frozenset(p.resolve() for p in RULED)


@lru_cache(maxsize=None)
def _committed(example: Path):
    return _computed(example)


def _computed(example: Path):
    model = pack.read(example)
    prog = ir.load(model.rules)
    calculation = calc.build(model, model.calc) if prog.calc_inputs() else None
    return model, prog, [State(model, prog, label, rows, calculation)
                         for label, rows in scenarios.states(model, example)]


def module_relations(example: Path, module: str):
    """In a pack with modules (`schema/<module>/`, `rules/<module>_*.dl`): says of a relation whether it is of
    that module: the table of one of its kinds, a slot of one (`kind__slot`), or a relation its rule files
    declare. A test of one module's read rules looks at these; the other modules have tests of their own."""
    import re

    import yaml
    classes = [name for f in sorted((example / "schema" / module).glob("*.yaml"))
               for name in (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("classes") or {}]
    kinds = {re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower() for name in classes}
    declared = {name for f in sorted((example / "rules").glob(f"{module}_*.dl"))
                for name in re.findall(r"(?m)^\.decl (\w+)\(", f.read_text(encoding="utf-8"))}
    return lambda relation: relation in declared or relation.split("__")[0] in kinds
