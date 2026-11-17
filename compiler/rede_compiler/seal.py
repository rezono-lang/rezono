"""The seal (decision E3, docs/compiler.md#design-m3-the-seal): refused and accepted input of the sealed kind.

A close (PeriodClose) closes every period before its `closed_until` and lists the rows it closes in `covers`:
an arrow `element` to the row and the row's canonical hash. A close refuses an element when it closes the
element's period or covers the element, and it does not cover the element with its current hash. So every
close that applies must hold the row as it is now: a late, backdated, edited or moved row cannot slip into a
closed period, and a later close cannot lift the refusal of an earlier one. The engine never hashes: the loader
computes `<kind>__row_sha256` (`row_sha256`), over the attributes, the arrows and the subkinds of the element.
`<kind>__refused(id, period_close)` names every refused element and each close that refuses it;
`<kind>__accepted(id)` holds the others. Rules read the accepted rows, so a refused row never counts, and it is
never a missing row either (W1).

The relations come out of SQL (Feldera, in engine/integrity.sql) and out of `rows` (the batch backend,
which fills the rule database from the facts); a test holds them equal, and each pack's reference.py
computes them on its own. `close` makes the delta of a new close for the canonical writer.
"""

from __future__ import annotations

import datetime

from rede_canon import canonical_sha256

from .pack import CLOSE, CLOSED_UNTIL, COVERS, ELEMENT, SHA256, CompileError, Pack
from .sqltext import q


def text(v) -> str:
    """Canonical text of one value, as in a snapshot: an integer in decimal, a date ISO, a boolean true/false."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime.date):
        return v.isoformat()
    return str(v)


def owners(s, rows: dict[str, list[tuple]]) -> dict[str, dict]:
    """Per part kind: each part's sealed element, through its arrow and, for a part of a part, its owner's.
    A part whose owner is not there belongs to no element (that is a reference violation of its arrow)."""
    elements = {r[0] for r in rows.get(s.kind, [])}
    out: dict[str, dict] = {}
    for part in s.parts:  # an owner comes before its parts
        up = None if part.owner == s.kind else out[part.owner]
        out[part.kind] = {i: (v if up is None else up[v]) for i, v in rows.get(part.arrow.table, [])
                          if (v in elements if up is None else v in up)}
    return out


def row_sha256(pack: Pack, rows: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
    """The generated table `<kind>__row_sha256(id, v)` from the fact rows of the sealed kind: per table of the
    seal its values as text, sorted; a subkind's table has no values, so membership is the empty list. Per
    table of a part (`sealed_with`), the rows of the element's parts, each as [id, value] text, sorted; a
    table without a row for the element is left out, so a seal without parts hashes as before."""
    out = {}
    for s in pack.seals:
        by_id: dict = {}
        for t in s.tables:
            for r in rows.get(t, []):
                by_id.setdefault(r[0], {}).setdefault(t, []).extend(text(v) for v in r[1:])
        of = owners(s, rows)
        for part in s.parts:
            for t in part.tables:
                for r in rows.get(t, []):
                    if r[0] in of[part.kind]:
                        by_id.setdefault(of[part.kind][r[0]], {}).setdefault(t, []).append([text(v) for v in r])
        out[s.row_sha256] = sorted({(i, canonical_sha256({t: sorted(vs) for t, vs in by_id.get(i, {}).items()}))
                                    for (i,) in rows.get(s.kind, [])}, key=repr)
    return out


def views(pack: Pack) -> list[tuple[str, str]]:
    """(name, SELECT) of the refused and the accepted relation of the sealed kind. A pair (element, close)
    applies when the close closes the element's period or covers the element; it is refused unless that close
    covers the element with its current hash. The closes come in by a cross join, as the engine has no
    inequality join; PeriodClose is small. The anti-join is a LEFT JOIN, as for negation (no correlated
    subquery in the engine SQL)."""
    out = []
    for s in pack.seals:
        until, covers = q(f"{CLOSE}__{CLOSED_UNTIL}"), q(f"{CLOSE}__{COVERS}")
        element, sha = q(f"{s.cover}__{ELEMENT}"), q(f"{s.cover}__{SHA256}")
        applies = (f"SELECT p.id AS id, u.id AS period_close FROM {q(s.period.table)} AS p\n"
                   f"    CROSS JOIN {until} AS u WHERE p.v < u.v\n"
                   f"  UNION\n"
                   f"  SELECT k.id AS id, v.id AS period_close FROM {q(s.kind)} AS k\n"
                   f"    JOIN {element} AS e ON e.v = k.id\n"
                   f"    JOIN {covers} AS v ON v.v = e.id")
        held = (f"SELECT e.v AS id, v.id AS period_close FROM {element} AS e\n"
                f"    JOIN {sha} AS c ON c.id = e.id\n"
                f"    JOIN {q(s.row_sha256)} AS h ON h.id = e.v AND h.v = c.v\n"
                f"    JOIN {covers} AS v ON v.v = e.id")
        refused = (f"SELECT DISTINCT a.id AS id, a.period_close AS period_close\nFROM (\n  {applies}\n) AS a\n"
                   f"LEFT JOIN (\n  {held}\n) AS m ON m.id = a.id AND m.period_close = a.period_close\n"
                   f"WHERE m.id IS NULL")
        accepted = (f"SELECT DISTINCT e.id AS id FROM {q(s.kind)} AS e\n"
                    f"LEFT JOIN {q(s.refused)} AS r ON r.id = e.id WHERE r.id IS NULL")
        out += [(s.refused, refused), (s.accepted, accepted)]
        accepted_of = {s.kind: s.accepted} | {p.kind: p.accepted for p in s.parts}
        for p in s.parts:  # a part counts when the element it is part of does
            out.append((p.accepted, f"SELECT DISTINCT x.id AS id FROM {q(p.arrow.table)} AS x\n"
                                    f"JOIN {q(accepted_of[p.owner])} AS a ON a.id = x.v"))
    return out


def sql(pack: Pack) -> str:
    if not pack.seals:
        return ""
    return ("\n-- Seal (decision E3): refused and accepted input of the sealed kind; rules read the accepted rows.\n"
            + "".join(f"CREATE MATERIALIZED VIEW {q(n)} AS\n{body};\n\n" for n, body in views(pack)))


def rows(pack: Pack, data: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
    """The same relations computed from the fact rows ({table: [row]}, with `<kind>__row_sha256`)."""
    out: dict[str, list[tuple]] = {}
    for s in pack.seals:
        until = data.get(f"{CLOSE}__{CLOSED_UNTIL}", [])
        close_of = {}  # cover -> its closes (a cover belongs to one close)
        for v, c in data.get(f"{CLOSE}__{COVERS}", []):
            close_of.setdefault(c, set()).add(v)
        sha = {}
        for c, h in data.get(f"{s.cover}__{SHA256}", []):
            sha.setdefault(c, set()).add(h)
        hashes = {}
        for i, h in data.get(s.row_sha256, []):
            hashes.setdefault(i, set()).add(h)
        elements = {r[0] for r in data.get(s.kind, [])}
        applies = {(i, v) for i, p in data.get(s.period.table, []) for v, u in until if p < u}
        held = set()
        for c, e in data.get(f"{s.cover}__{ELEMENT}", []):
            for v in close_of.get(c, ()):
                if e in elements:
                    applies.add((e, v))
                if sha.get(c, set()) & hashes.get(e, set()):
                    held.add((e, v))
        refused = applies - held
        gone = {i for i, _ in refused}
        out[s.refused] = sorted(refused, key=repr)
        out[s.accepted] = sorted({(i,) for i in elements if i not in gone}, key=repr)
        ok = {s.kind: elements - gone}
        for p in s.parts:  # a part counts when the element it is part of does
            ok[p.kind] = {i for i, v in data.get(p.arrow.table, []) if v in ok[p.owner]}
            out[p.accepted] = sorted({(i,) for i in ok[p.kind]}, key=repr)
    return out


def close(pack: Pack, data: dict[str, list[tuple]], close_id: str, until: datetime.date, file: str) -> dict:
    """The delta (rede.delta/1) that inserts a close: every period before `until` is closed, and every
    accepted element with such a period is covered with its current hash. A refused element stays refused."""
    if not pack.seals:
        raise CompileError("close: the pack has no seal")
    s = pack.seals[0]
    accepted = {i for (i,) in rows(pack, data)[s.accepted]}
    hashes = dict(data.get(s.row_sha256, []))
    covers = [{ELEMENT: text(i), SHA256: hashes[i]}
              for i, p in sorted(data.get(s.period.table, []), key=lambda r: text(r[0])) if p < until and i in accepted]
    return {"format": "rede.delta/1", "changes": [
        {"op": "insert", "file": file, "kind": CLOSE, "key": close_id,
         "values": {CLOSED_UNTIL: until.isoformat(), COVERS: covers}}]}


READ = "may_read"  # std-access (O7): who sees an element


def check_rules(pack: Pack, doc: dict, errors: list[str]) -> None:
    """A rule that reads a table of the sealed kind (the kind, a subkind or one of their attributes and
    arrows), in any literal or aggregate, must read `<kind>__accepted` on the same element in a positive
    literal; otherwise a refused row would count. A read rule (`may_read`, std-access) is the exception: it
    decides who sees an element, so a refused row stays visible. No other rule may read `may_read`, which holds
    refused rows too. The other access relations grant rights, so they read accepted rows like any rule."""
    tables = {}
    for s in pack.seals:
        for x in (s, *s.parts):  # the sealed kind and each part: its kind, its subkinds and their tables
            for k in pack.kinds:
                if pack.root(k) == x.kind:
                    tables[k] = x
            tables.update({t: x for t in x.tables})
    for r in doc.get("rules", []):
        where = f"{r['origin']['file']}:{r['origin']['line']}: rule {r['id']}"
        atoms = r["body"] + r.get("aggregates", [])
        if r["head"]["relation"] == READ:
            continue
        for atom in atoms:
            if atom["relation"] == READ and pack.seals:
                errors.append(f"{where} reads {READ}, which holds refused rows of the sealed kind "
                              f"{pack.seals[0].kind} too")
        accepted = {(lit["relation"], lit["terms"][0]) for lit in r["body"] if lit["polarity"] == "positive"}
        for atom in atoms:
            s = tables.get(atom["relation"])
            if s and (s.accepted, atom["terms"][0]) not in accepted:
                term = atom["terms"][0].lstrip("?")
                what = "the sealed kind" if s in pack.seals else "the part"
                errors.append(f"{where} reads {atom['relation']} of {what} {s.kind} without "
                              f"{s.accepted}({term}); a refused row would count")
