"""Evaluate the checked-in witness-graph Rezono rule pack (`edge/publisher/packs/witness-graph`).

Derives `founded_witness/3` and `load_bearing/5` over a role's usable witness instances via
`rezono_compiler.batch` (decisions/one-structure-space-and-readings.md §4,
decisions/publish-founded-witnesses.md). Fails closed if rule evaluation fails.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

from rezono_canon import canonical_sha256
from rezono_compiler import batch as compiler_batch
from rezono_compiler import pack as compiler_pack
from rezono_compiler import rules as compiler_rules

PACK_DIR = Path(__file__).resolve().parents[1] / "packs" / "witness-graph"


def witness_hash(w: dict) -> str:
    """Canonical SHA-256 of a witness without any `iri` slot (decisions/publication-conclusion-addresses.md §2)."""
    if "iri" in w:
        return canonical_sha256({k: v for k, v in w.items() if k != "iri"})
    return canonical_sha256(w)


@functools.lru_cache(maxsize=1)
def _compiled_program():
    model = compiler_pack.read(PACK_DIR)
    return compiler_rules.load(model.rules)


def _bulk_insert(con, table: str, rows: list[tuple] | list[list], chunk_size: int = 500) -> None:
    if not rows:
        return
    width = len(rows[0])
    row_ph = "(" + ", ".join("?" for _ in range(width)) + ")"
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        values_sql = ", ".join(row_ph for _ in chunk)
        flat = [cell for row in chunk for cell in row]
        con.execute(f'INSERT INTO "{table}" VALUES {values_sql}', flat)


def evaluate(instances: list[dict], derived) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str, str, str]]]:
    """Run the compiled `witness-graph` Rezono rule pack on `instances` via `rezono_compiler.batch`.

    Returns `(founded_witness_rows, load_bearing_rows)`:
    - `founded_witness_rows`: set of `(conclusion_rel, conclusion_key, witness_hash)`
    - `load_bearing_rows`: set of `(conclusion_rel, conclusion_key, premise_rel, premise_key, how)`
    """
    prog = _compiled_program()
    usable_witness = []
    usable_conclusion_rel = []
    usable_conclusion_key = []
    usable_dep_count = []
    witness_premise = []
    witness_premise_witness = []
    witness_premise_rel = []
    witness_premise_key = []
    witness_premise_how = []
    witness_dep_step = []
    witness_dep_witness = []
    witness_dep_from = []
    witness_dep_to = []
    witness_dep_rel = []
    witness_dep_key = []

    seen_w: set[str] = set()
    p_seq = 0
    d_seq = 0
    for w in instances:
        wid = witness_hash(w)
        if wid in seen_w:
            continue
        seen_w.add(wid)
        c_rel = w["conclusion"]["relation"]
        c_key = w["conclusion"]["key"]

        derived_deps = sorted({
            (p["row"]["relation"], p["row"]["key"])
            for p in w.get("premises", ())
            if p["polarity"] == "positive" and p["row"]["relation"] in derived
        })
        usable_witness.append((wid,))
        usable_conclusion_rel.append((wid, c_rel))
        usable_conclusion_key.append((wid, c_key))
        usable_dep_count.append((wid, str(len(derived_deps))))

        seen_p: set[tuple[str, str, str]] = set()
        for p in w.get("premises", ()):
            pt = (p["row"]["relation"], p["row"]["key"], p["polarity"])
            if pt in seen_p:
                continue
            seen_p.add(pt)
            pid = f"p{p_seq}"
            p_seq += 1
            witness_premise.append((pid,))
            witness_premise_witness.append((pid, wid))
            witness_premise_rel.append((pid, pt[0]))
            witness_premise_key.append((pid, pt[1]))
            witness_premise_how.append((pid, pt[2]))

        for idx, (dr, dk) in enumerate(derived_deps):
            sid = f"d{d_seq}"
            d_seq += 1
            witness_dep_step.append((sid,))
            witness_dep_witness.append((sid, wid))
            witness_dep_from.append((sid, str(idx)))
            witness_dep_to.append((sid, str(idx + 1)))
            witness_dep_rel.append((sid, dr))
            witness_dep_key.append((sid, dk))

    base_data = {
        "usable_witness__conclusion_rel": usable_conclusion_rel,
        "usable_witness__conclusion_key": usable_conclusion_key,
        "usable_witness__dep_count": usable_dep_count,
        "witness_premise__witness": witness_premise_witness,
        "witness_premise__premise_rel": witness_premise_rel,
        "witness_premise__premise_key": witness_premise_key,
        "witness_premise__how": witness_premise_how,
        "witness_dep_step__witness": witness_dep_witness,
        "witness_dep_step__step_from": witness_dep_from,
        "witness_dep_step__step_to": witness_dep_to,
        "witness_dep_step__dep_rel": witness_dep_rel,
        "witness_dep_step__dep_key": witness_dep_key,
    }
    con = compiler_batch.connect(prog, {})
    try:
        for table, rows in base_data.items():
            _bulk_insert(con, table, rows)
        compiler_batch.compute(con, prog)
        derived_rows = compiler_batch.read(con, prog, ["founded_witness", "load_bearing", "fixpoint_incomplete"])
        if derived_rows["fixpoint_incomplete"]:
            raise RuntimeError(
                f"witness-graph fixpoint incomplete for {len(derived_rows['fixpoint_incomplete'])} conclusion(s)"
            )
        return derived_rows["founded_witness"], derived_rows["load_bearing"]
    finally:
        con.close()
