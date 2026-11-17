"""Typed element identity (B11, S4; #394 A2): an element is its root kind and its id, never its id alone.

Two elements of unrelated kinds may have equal ids: the zone "x" and the server "x" are two elements. Wherever
views and mappings see elements, they see the pair (root kind, id), so equal ids never collapse. Along
inheritance the identity stays one: an element of a subkind is the element of its root with that id, so a union
of a kind and its parent holds it once.

A union of source kinds (a theory kind populated from several branches) takes in each element deterministically:

- its identity is (root, id), the root being the kind name the pack declares, not an engine table name, so
  source identity stays apart from physical names;
- in the rule IR, a union over one root is the id alone: the root is fixed, so its column would be a constant
  (one-to-one, nothing is lost); a union over several roots is the pair, the root as a text constant first;
- all roots of a union share one identifier type: no conversion or encoder is chosen.

This module says what an element is and how a union holds it. It loads nothing and runs nothing; the lowering of
views (`view_rules`) and the mappings use it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from . import types
from .pack import Pack


class IdentityError(ValueError):
    """An element or union without one typed identity."""


@dataclass(frozen=True, order=True)
class Identity:
    """One element: its root kind and its id (text or a whole number, the root's identifier type)."""
    root: str
    id: str | int


def id_base(pack: Pack, kind: str) -> str:
    """The base type of the identifier of `kind`'s root: text or a whole number."""
    if kind not in pack.kinds:
        raise IdentityError(f"unknown kind '{kind}'")
    root = pack.root(kind)
    try:
        return types.ref(kind, types.of_sql(pack.kinds[root].id_type).base).base
    except (KeyError, ValueError) as e:
        raise IdentityError(f"kind '{kind}': its root '{root}' has no text or whole-number identifier") from e


def of(pack: Pack, kind: str, value) -> Identity:
    """The element of `kind` with id `value`: its root and the id, checked against the root's identifier type."""
    base = id_base(pack, kind)
    if isinstance(value, bool) or not isinstance(value, int if base == types.INTEGER else str):
        raise IdentityError(f"kind '{kind}': {value!r} is not an identifier of type {base}")
    return Identity(pack.root(kind), value)


@dataclass(frozen=True)
class Union:
    """How a union of source kinds holds its elements: the distinct roots (sorted) and their identifier type."""
    roots: tuple[str, ...]
    id_type: str  # the engine type of the identifier: VARCHAR or BIGINT

    @property
    def tagged(self) -> bool:
        """True if the root is part of an element's key: the union spans more than one root."""
        return len(self.roots) > 1

    def columns(self, prefix: str = "") -> tuple[tuple[str, str], ...]:
        """The rule IR key columns (name, type) of one element of the union."""
        rule = types.rule_type(self.id_type)
        return ((f"{prefix}kind", "string"), (f"{prefix}id", rule)) if self.tagged else ((f"{prefix}id", rule),)

    def terms(self, root: str, var: str) -> tuple[str, ...]:
        """The rule IR terms of an element of `root` whose id is the variable `var`."""
        self._has(root)
        return (root, var) if self.tagged else (var,)

    def key(self, element: Identity) -> tuple:
        """The key of `element` in the union's relation."""
        self._has(element.root)
        return (element.root, element.id) if self.tagged else (element.id,)

    def element(self, key: tuple) -> Identity:
        """The element a key of the union's relation stands for: the inverse of `key`."""
        if self.tagged:
            root, value = key
            self._has(root)
            return Identity(root, value)
        (value,) = key
        return Identity(self.roots[0], value)

    def _has(self, root: str) -> None:
        if root not in self.roots:
            raise IdentityError(f"'{root}' is not a root of the union {list(self.roots)}")


def union(pack: Pack, kinds: Iterable[str]) -> Union:
    """The identity of a union of the source kinds `kinds` of `pack`."""
    kinds = tuple(kinds)
    if not kinds:
        raise IdentityError("a union needs at least one source kind")
    for kind in kinds:
        id_base(pack, kind)
    roots = tuple(sorted({pack.root(k) for k in kinds}))
    id_types = sorted({pack.kinds[r].id_type for r in roots})
    if len(id_types) != 1:
        raise IdentityError(f"the roots {list(roots)} have different identifier types {id_types}; "
                            "no conversion is selected")
    return Union(roots, id_types[0])


def injection(pack: Pack, kinds: Iterable[str], var: str = "?v0") -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The deterministic injection of a union of source kinds, as (source kind, head terms) per branch in the
    given order: each element of the branch enters as `terms(root, var)` of the union. A rule
    `head(terms) :- kind(var)` per branch populates the union; equal ids of different roots stay two keys."""
    kinds = tuple(kinds)
    u = union(pack, kinds)
    return tuple((k, u.terms(pack.root(k), var)) for k in kinds)
