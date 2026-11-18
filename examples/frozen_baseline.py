"""Frozen baseline acceptance: a replacement model must derive exactly the rows that today's packs derive
(tests only, never in production).

The baseline is frozen as content. Every row set (one relation, in one fact state, of one pack) is a file
`sets/<sha256>.json` holding its canonical JSON, and `index.json` names the hash of each relation's set per
pack and state. A set is what the engine derives now (rules, the refused and accepted input of a seal, and the
calculation results), not what `expected/` says, so regenerating `expected/` cannot move the baseline. A set
changes only through `freeze` with the changed states named, and that shows as a changed line in the index.

A replacement (a merged model, an import step) is compared through an `Adapter`: which baseline states each of
its states stands for (several packs at once), and which relation and kind names it renamed. Missing rows and
extra rows in a frozen relation both fail; relations the baseline does not have are new and not compared.
`may_read` is compared per role, as the typed elements (kind, id) the role may read.

Nothing here knows a domain: the packs, states, relations and roles come from the index and the adapter.

Usage: python examples/frozen_baseline.py <baseline dir> freeze [<pack>=<pack dir> ...] [<pack>/<state> ...]
  Freezes every pack in the index, plus any pack given as <pack>=<pack dir> (relative to examples/). A state
  whose sets change must be named as <pack>/<state>; otherwise nothing is written and the differences are shown.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rezono_canon import canonical_bytes

FORMAT = "rezono-frozen-baseline/1"
ACCESS = "may_read"  # std-access: may_read(role, kind, id)
CALC = "calc:"  # a calculation result: calc:<rule>, rows (subject, value or state when not known)
ROOT = Path(__file__).resolve().parent

Rows = set[tuple[str, ...]]
States = dict[str, dict[str, Rows]]  # state -> relation -> rows


def observe(pack_dir: Path) -> States:
    """What the pack derives now, per fact state (facts/ together, then each scenario cumulatively)."""
    for p in (ROOT, ROOT.parent / "compiler" / "tests"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from rules_support import states

    model, _, run = states(pack_dir)
    out: States = {s.label: {r: {tuple(str(x) for x in row) for row in rows}
                             for r, rows in (s.derived | s.seal).items()} for s in run}
    if (pack_dir / "calc").is_dir():
        from calcsupport import run as calc_run
        from rezono_compiler import calc, calc_sql, scenarios

        prog = calc.build(model, model.calc)
        for label, rows in scenarios.states(model, pack_dir):
            rows = rows | {t: [tuple(r.values()) for r in rs] for t, rs in calc_sql.rows(prog).items()}
            for rule, subjects in calc_run(model, prog, rows).items():
                out[label][CALC + rule] = {(str(s), v[1] if v[0] == "known" else v[0]) for s, v in subjects.items()}
    return out


def encode(rows: Rows) -> bytes:
    return canonical_bytes(sorted([list(r) for r in rows]))


def load(base: Path) -> dict[str, States]:
    """The frozen sets, {pack: {state: {relation: rows}}}. Each file must hash to its name and be canonical."""
    index = json.loads((base / "index.json").read_text(encoding="utf-8"))
    assert index["format"] == FORMAT, index.get("format")
    out: dict[str, States] = {}
    for pack, entry in index["packs"].items():
        for state, relations in entry["states"].items():
            out.setdefault(pack, {})[state] = {}
            for relation, sha in relations.items():
                data = (base / "sets" / f"{sha}.json").read_bytes()
                assert hashlib.sha256(data).hexdigest() == sha, f"sets/{sha}.json does not hash to its name"
                rows = {tuple(r) for r in json.loads(data)}
                assert data == encode(rows), f"sets/{sha}.json is not canonical"
                out[pack][state][relation] = rows
    return out


class Changed(Exception):
    """A freeze would change frozen states that were not named."""


def freeze(base: Path, packs: dict[str, tuple[str, States]], accept=frozenset()) -> dict:
    """Writes the sets of `packs` ({pack: (pack dir, observed states)}) and the index. A state whose sets differ
    from the index must be in `accept` as "<pack>/<state>"; otherwise nothing is written."""
    index_file = base / "index.json"
    old = json.loads(index_file.read_text(encoding="utf-8"))["packs"] if index_file.exists() else {}
    new, sets = {}, {}
    for pack, (source, states) in sorted(packs.items()):
        entry = {}
        for state, relations in sorted(states.items()):
            entry[state] = {}
            for relation, rows in sorted(relations.items()):
                data = encode(rows)
                sha = hashlib.sha256(data).hexdigest()
                sets[sha], entry[state][relation] = data, sha
        new[pack] = {"source": source, "states": entry}
    changed = sorted(f"{p}/{s}" for p in new if p in old
                     for s in set(new[p]["states"]) | set(old[p]["states"])
                     if old[p]["states"].get(s) != new[p]["states"].get(s))
    refused = [c for c in changed if c not in accept]
    if refused:
        frozen, lines = load(base), []
        for c in refused:
            pack, state = c.split("/", 1)
            want = expected(frozen, Adapter({state: {pack: state}})) if state in frozen[pack] else {}
            lines += differences(want, {state: packs[pack][1].get(state, {})}) or [(state, "*", "new state")]
        raise Changed(f"frozen sets would change for {', '.join(refused)}; name them to accept:\n"
                      + "\n".join(f"  {d}" for d in lines))
    # Every set first, then the index in one atomic replace, and only then the sets nothing names: an
    # interrupted freeze leaves the old index with all its sets, or the new one with all of its.
    (base / "sets").mkdir(parents=True, exist_ok=True)
    for sha, data in sets.items():
        path = base / "sets" / f"{sha}.json"
        if not path.exists():
            part = path.with_suffix(".part")
            part.write_bytes(data)
            os.replace(part, path)
    packs_out = old | new
    index = {"format": FORMAT, "packs": packs_out}
    part = index_file.with_suffix(".part")
    part.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(part, index_file)
    kept = {sha for p in packs_out.values() for rs in p["states"].values() for sha in rs.values()}
    for path in (base / "sets").glob("*.json"):
        if path.stem not in kept:
            path.unlink()
    return index


@dataclass(frozen=True)
class Adapter:
    """How a replacement's names stand for the baseline's.

    states: replacement state -> {pack: baseline state}; the replacement's rows in that state must be the union
    of those packs' rows. relations: baseline relation -> replacement relation, or None for a helper relation
    the replacement no longer derives (named, so a review sees it; its rows are then not compared).
    kinds: pack -> {baseline kind -> replacement kind}, in the kind column of that pack's `may_read`. Per pack,
    because two packs may use the same kind id and only one of them renames it (lab `zone`, network `zone`).
    """

    states: dict[str, dict[str, str]]
    relations: dict[str, str | None] = field(default_factory=dict)
    kinds: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self):
        # Access is always compared, per role: an adapter may not rename or retire it.
        if ACCESS in self.relations or ACCESS in self.relations.values():
            raise ValueError(f"an adapter may not rename or retire {ACCESS}")
        packs = {pack for composed in self.states.values() for pack in composed}
        for pack, renames in self.kinds.items():
            if pack not in packs or not isinstance(renames, dict):
                raise ValueError(f"kind renames are per pack, {{pack: {{old: new}}}}; {pack!r} is not a pack here")

    @staticmethod
    def identity(frozen: dict[str, States], pack: str) -> Adapter:
        return Adapter({s: {pack: s} for s in frozen[pack]})

    @staticmethod
    def from_state_map(state_map: dict[str, dict[str, str]], **renames) -> Adapter:
        """From a plan's state map, {pack: {baseline state: replacement state}}, whose replacement scenarios
        form one cumulative stream in lexical order (as the compiler reads them): in each replacement state, a
        pack stands at its latest mapped state at or before it."""
        stream = sorted({new for m in state_map.values() for new in m.values()})
        states: dict[str, dict[str, str]] = {}
        for here in stream:
            states[here] = {}
            for pack, m in sorted(state_map.items()):
                before = sorted((new, old) for old, new in m.items() if new <= here)
                if not before:
                    raise ValueError(f"{pack} has no state at or before {here}")
                states[here][pack] = before[-1][1]
        return Adapter(states, **renames)


def expected(frozen: dict[str, States], adapter: Adapter) -> States:
    """The rows the replacement must derive, in its own state and relation names."""
    out: States = {}
    for state, packs in adapter.states.items():
        target = out.setdefault(state, {})
        for pack, baseline in sorted(packs.items()):
            for relation, rows in frozen[pack][baseline].items():
                name = adapter.relations.get(relation, relation)
                if name is None:
                    continue
                if relation == ACCESS:
                    kinds = adapter.kinds.get(pack, {})
                    rows = {(r, kinds.get(k, k), x) for r, k, x in rows}
                target.setdefault(name, set()).update(rows)
    return out


def per_role(rows: Rows) -> dict[str, set[tuple[str, str]]]:
    """may_read as the typed elements (kind, id) per role."""
    out: dict[str, set[tuple[str, str]]] = {}
    for role, kind, element in rows:
        out.setdefault(role, set()).add((kind, element))
    return out


def differences(want: States, have: States) -> list[tuple]:
    """(state, relation, "missing" | "extra", row) for every row that differs, `may_read` per role as
    (state, "may_read[<role>]", ..., (kind, id)). Empty when the replacement is accepted.

    Every state the replacement derives must be one the adapter maps, and `may_read` is compared wherever
    either side has it, so a grant in an unmapped state or an unexpected `may_read` is never ignored.
    Other relations the replacement adds are its own and are not compared."""
    out: list[tuple] = []
    for state in sorted(set(want) | set(have)):
        if state not in want:
            out.append((state, "*", "extra", ("the state",)))
            continue
        if state not in have:
            out.append((state, "*", "missing", ("the state",)))
            continue
        relations = want[state]
        if ACCESS in have[state]:
            relations = {ACCESS: set()} | relations
        for relation, rows in sorted(relations.items()):
            got = have[state].get(relation)
            if got is None:
                out.append((state, relation, "missing", ("the relation",)))
            elif relation == ACCESS:
                w, g = per_role(rows), per_role(got)
                for role in sorted(set(w) | set(g)):
                    a, b = w.get(role, set()), g.get(role, set())
                    out += [(state, f"{ACCESS}[{role}]", "missing", e) for e in sorted(a - b)]
                    out += [(state, f"{ACCESS}[{role}]", "extra", e) for e in sorted(b - a)]
            else:
                out += [(state, relation, "missing", r) for r in sorted(rows - got)]
                out += [(state, relation, "extra", r) for r in sorted(got - rows)]
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] != "freeze":
        raise SystemExit(__doc__)
    base, rest = Path(argv[0]), argv[2:]
    index = base / "index.json"
    sources = {p: v["source"] for p, v in json.loads(index.read_text(encoding="utf-8"))["packs"].items()} \
        if index.exists() else {}
    sources |= dict(a.split("=", 1) for a in rest if "=" in a)
    accept = {a for a in rest if "=" not in a}
    try:
        freeze(base, {p: (src, observe(ROOT / src)) for p, src in sorted(sources.items())}, accept)
    except Changed as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
