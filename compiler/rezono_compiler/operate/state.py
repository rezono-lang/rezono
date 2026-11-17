# --- The migration on states ---------------------------------------------------------------------------------

from __future__ import annotations

from collections import Counter
from urllib.parse import quote, unquote

from .model import Model


def embedded(m: Model, states_) -> set:
    """The ids of inlined elements without an identifier of their own: made from owner, kind and slot."""
    p = m.pack
    out = set()
    for *_, rows in states_:
        for k, kind in p.kinds.items():
            if p.kinds[p.root(k)].identifier is None:
                out |= {r[0] for r in rows.get(k, [])}
    return out


def id_map(ids: set, elements: dict[str, str], absorbed: str | None = None) -> dict:
    """Old derived id -> new, for the ids that change. `absorbed`: the element of an arrow whose derived
    elements a combine absorbs into their owner; what they own then hangs on the owner (they are not in the map:
    they go)."""
    out = {}

    def new(x):
        if x not in ids:
            return x
        if x not in out:
            parts = str(x).split("/")
            n = parts.pop() if len(parts) == 3 else None
            q, el = parts
            parent = new(unquote(q))
            if absorbed is not None and el == absorbed and n is None:
                out[x] = parent
            else:
                out[x] = f"{quote(str(parent), safe='')}/{elements.get(el, el)}" + (f"/{n}" if n else "")
        return out[x]

    for x in sorted(ids, key=str):
        new(x)
    gone = lambda x: absorbed is not None and str(x).split("/")[1:] == [absorbed]
    return {a: b for a, b in out.items() if a != b and not gone(a)}


def migrate(rows: dict[str, list[tuple]], tables: dict[str, str], values: dict[str, dict], ids: dict,
            arrows: set) -> dict[str, list[tuple]]:
    """M on one state: tables renamed, enum values and embedded ids mapped. `values`: table -> {old: new}."""
    out: dict[str, list[tuple]] = {}
    for t, rs in rows.items():
        vmap = values.get(t, {})
        for r in rs:
            r = (ids.get(r[0], r[0]),) + r[1:]
            if len(r) == 2:
                v = r[1]
                if t in arrows:
                    v = ids.get(v, v)
                v = vmap.get(v, v) if isinstance(v, str) else v
                r = (r[0], v)
            out.setdefault(tables.get(t, t), []).append(r)
    return out


def bag(rows: dict[str, list[tuple]]) -> dict[str, Counter]:
    return {t: Counter(map(repr, rs)) for t, rs in rows.items() if rs}


def difference(a: dict[str, list[tuple]], b: dict[str, list[tuple]]) -> list[tuple[str, list[tuple]]]:
    """Rows of `a` that `b` lacks, per table (as a multiset)."""
    out = []
    for t in sorted(a):
        have = Counter(map(repr, b.get(t, [])))
        missing = []
        for r in sorted(a[t], key=repr):
            if have[repr(r)]:
                have[repr(r)] -= 1
            else:
                missing.append(r)
        if missing:
            out.append((t, missing))
    return out


def text_of(v) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else ("true" if v is True else "false" if v is False else str(v))
