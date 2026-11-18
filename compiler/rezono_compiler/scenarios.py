"""A pack's fact states: all of facts/ first, then each scenarios/*.yaml in order, cumulatively.

A scenario is a What-if: its records are added, and a record whose identifier already exists replaces
the earlier one, in whichever section of the root kind it was (a record also says which subkind its element
is in). The first state is named `0-<first fact file>`, the others after their scenario file; without facts/
the scenarios start from no records.
"""

from __future__ import annotations

from pathlib import Path

from . import emit, facts, seal
from .pack import Pack


def fact_states(pack: Pack, pack_dir: str | Path, diagnostics: bool = True) -> list[tuple[str, str, str | None, dict]]:
    """Every fact state: (state kind, name, file, rows): the main state, each cumulative scenario, and each
    diagnostic (with `diagnostics`). The one contract for building states, for the rules, explain and the
    schema operations alike.

    Rows are multisets: two equal records in the facts give two rows. The main state is every record of every
    file in facts/; a scenario record replaces the record of the same element before it, whatever section of
    the root kind it is in (a record also says which subkind its element is in), and every other record is
    added. Without facts/ the scenarios start from no records."""
    pack_dir = Path(pack_dir)
    out = []
    files = facts.files(pack_dir)
    base: list[tuple[str, object, dict]] = []
    for f in files:
        base += records(pack, f)
    if files:
        out.append(("facts", f"0-{files[0].stem}", None, rows_of(pack, base)))
    for f in sorted((pack_dir / "scenarios").glob("*.yaml")):
        new = records(pack, f)
        replaced = {(pack.root(kind), key) for kind, key, _ in new if key is not None}
        base = [r for r in base if (pack.root(r[0]), r[1]) not in replaced] + new
        out.append(("scenario", f.stem, f"scenarios/{f.name}", rows_of(pack, base)))
    if diagnostics:
        for f in sorted((pack_dir / "diagnostics").glob("*.yaml")):
            out.append(("diagnostic", f.stem, f"diagnostics/{f.name}", facts.load(pack, f)))
    return out


def states(pack: Pack, pack_dir: str | Path) -> list[tuple[str, dict[str, list[tuple]]]]:
    """The fact states the rules run on: (name, rows) of the main state and each scenario (fact_states)."""
    return [(name, rows) for _, name, _, rows in fact_states(pack, pack_dir, diagnostics=False)]


def records(pack: Pack, path: Path) -> list[tuple[str, object, dict]]:
    """(kind, id or None, record) for every record of a fact file, in file order, duplicates included."""
    out = []
    try:
        data = facts.document(path, pack)
    except facts.LoadError as e:
        raise facts.LoadError(f"{path.name}: {e}") from None
    if path.parent.name == "facts" and path.with_suffix(".sources.yaml").exists():
        from .sources import file_entries
        file_entries(pack, path, data)
    for kind, rs in data.items():
        if kind not in pack.kinds:
            raise facts.LoadError(f"{path.name}: unknown kind '{kind}'")
        ident = pack.kinds[pack.root(kind)].identifier
        out += [(kind, r.get(ident) if ident and isinstance(r, dict) else None, r) for r in rs]
    return out


def rows_of(pack: Pack, recs: list[tuple[str, object, dict]]) -> dict[str, list[tuple]]:
    by_kind: dict[str, list[dict]] = {}
    for kind, _, r in recs:
        by_kind.setdefault(kind, []).append(r)
    return facts.rows_of(pack, by_kind)


def rule_rows(pack: Pack, prog, rows: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
    """The rows of the base relations a rule program reads: fact rows, parameter rows, and the refused and
    accepted rows of a seal."""
    params = {t: [tuple(r.values()) for r in rs] for t, rs in emit.parameters(pack).items()}
    rows = rows | seal.rows(pack, rows)
    out = {}
    for name in prog.base_used():
        out[name] = sorted(set(rows.get(name, []) + params.get(name, [])), key=repr)
    return out
