"""Enumerate typed double-pushout step matches over keyed rows.

A keyed graph maps each relation to its rows of text values. A relation without ``__`` is a kind: the first
column of its rows is the identity of an element. A relation ``kind__slot`` holds rows whose first column is the
identity of the owning ``kind`` element. A later column refers to an element of the kinds that ``references``
names for that relation; without ``references`` any element with that identity counts as referenced.

The left graph ``L``, the interface ``K``, the right graph ``R`` and every guard are patterns: a value that starts
with ``?`` is a variable. ``K`` is contained in ``L`` and ``R``, and ``L`` in each guard. A match maps the rows of
``L`` injectively onto rows of the base. It is admissible when no guard extends it injectively, when no remaining
row still depends on a deleted element, and when every created row is fresh in the remaining context.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Literal, TypeAlias, TypedDict

Row: TypeAlias = tuple[str, ...]
Fact: TypeAlias = tuple[str, Row]
Graph: TypeAlias = Mapping[str, Iterable[Sequence[str]]]
Binding: TypeAlias = dict[str, str]


class Match(TypedDict):
    binding: list[tuple[str, str]]
    matched: list[Fact]
    removed: list[Fact]
    added: list[Fact]
    preserved: list[Fact]


class Matches(TypedDict):
    state: Literal["known", "unknown"]
    matches: list[Match]


def _facts(graph: Graph, name: str) -> frozenset[Fact]:
    facts = set()
    for relation, rows in graph.items():
        for row in rows:
            values = tuple(row)
            if not values or not all(isinstance(value, str) for value in values):
                raise ValueError(f"{name}: {relation} rows need at least one text column")
            facts.add((relation, values))
    return frozenset(facts)


def _variable(term: str) -> bool:
    return term.startswith("?")


def _ground(fact: Fact, binding: Binding) -> Fact:
    relation, row = fact
    if any(_variable(term) and term not in binding for term in row):
        raise ValueError(f"{relation}: a created row needs every variable bound by the left graph")
    return relation, tuple(binding.get(term, term) for term in row)


def _unify(pattern: Row, row: Row, binding: Binding) -> Binding | None:
    if len(pattern) != len(row):
        return None
    extended = dict(binding)
    for term, value in zip(pattern, row, strict=True):
        if not _variable(term):
            if term != value:
                return None
        elif extended.setdefault(term, value) != value:
            return None
    return extended


def _extensions(pattern: Sequence[Fact], index: Mapping[str, Sequence[Row]], binding: Binding,
                used: frozenset[Fact]) -> Iterator[tuple[Binding, frozenset[Fact]]]:
    """Yield every injective extension of ``binding`` that maps each pattern row onto a distinct base row."""
    if not pattern:
        yield binding, used
        return
    (relation, terms), rest = pattern[0], pattern[1:]
    for row in index.get(relation, ()):
        image = (relation, row)
        if image in used:
            continue
        extended = _unify(terms, row, binding)
        if extended is not None:
            yield from _extensions(rest, index, extended, used | {image})


def _ordered(facts: Iterable[Fact]) -> list[Fact]:
    # Bind the most constrained rows first; the order never changes which matches exist.
    return sorted(facts, key=lambda fact: (sum(map(_variable, fact[1])), fact))


def _dangling(context: frozenset[Fact], deleted: frozenset[Fact],
              references: Mapping[str, Iterable[str]] | None) -> bool:
    elements = {(relation, row[0]) for relation, row in deleted if "__" not in relation}
    if not elements:
        return False
    kinds = {kind for kind, _ in elements}
    for relation, row in context:
        owner, separator, _ = relation.partition("__")
        if separator and (owner, row[0]) in elements:
            return True
        targets = kinds if references is None else set(references.get(relation, ()))
        if any((kind, value) in elements for value in row[1:] for kind in targets):
            return True
    return False


def match_effects(base: Graph, left: Graph, keep: Graph, right: Graph, guards: Sequence[Graph] = (), *,
                  complete: bool, references: Mapping[str, Iterable[str]] | None = None) -> Matches:
    """Return every admissible match of ``left ← keep → right`` in ``base`` with its keyed row delta.

    Absence of a guard extension, of a dangling reference and of a duplicate identity is only decidable over a
    complete base, so an incomplete base yields an unknown state without matches.
    """
    facts = _facts(base, "base")
    if any(_variable(term) for _, row in facts for term in row):
        raise ValueError("base: rows must be ground")
    lhs, interface, rhs = _facts(left, "left"), _facts(keep, "keep"), _facts(right, "right")
    if not interface <= lhs or not interface <= rhs:
        raise ValueError("keep: the interface must be contained in the left and right graphs")
    conditions = [_facts(guard, f"guard {number}") for number, guard in enumerate(guards, 1)]
    if any(not lhs <= condition for condition in conditions):
        raise ValueError("guard: every guard must contain the left graph")
    if not complete:
        return {"state": "unknown", "matches": []}

    index: dict[str, list[Row]] = defaultdict(list)
    for relation, row in sorted(facts):
        index[relation].append(row)
    pattern = _ordered(lhs)
    deleted_pattern, created_pattern = lhs - interface, rhs - interface
    extensions = [_ordered(condition - lhs) for condition in conditions]

    matches: list[Match] = []
    for binding, matched in _extensions(pattern, index, {}, frozenset()):
        if any(next(_extensions(extra, index, binding, matched), None) for extra in extensions):
            continue
        deleted = frozenset(_ground(fact, binding) for fact in deleted_pattern)
        context = facts - deleted
        if _dangling(context, deleted, references):
            continue
        created = [_ground(fact, binding) for fact in created_pattern]
        if len(set(created)) != len(created) or context & set(created):
            continue
        after = context | set(created)
        matches.append({
            "binding": sorted(binding.items()),
            "matched": sorted(matched),
            "removed": sorted(facts - after),
            "added": sorted(after - facts),
            "preserved": sorted(facts & after),
        })
    matches.sort(key=lambda match: (match["matched"], match["binding"]))
    return {"state": "known", "matches": matches}
