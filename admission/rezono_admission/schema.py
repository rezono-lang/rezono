"""The schema admission judges rows against: the pack's archived schema bundle (contracts/bundle.yaml), addressed
by its hash, as the gate reads it (C3). Nothing here reads a pack's sources or imports the compiler: a fact never
needs the compiler (ruling 2 of 11-11-2026).

What admission needs of the bundle: per kind its parent, whether it is abstract, its identifier, the type of its
ids, and its plane (`control` for a kind of decided values, DV1, with the owner who reviews a change); per slot
(an attribute or an arrow, declared on a kind and inherited by its subkinds) its table, its type, whether it is
multivalued, and for an arrow its target and whether it is inlined.
"""

from __future__ import annotations

from dataclasses import dataclass

from rezono_canon import canonical_sha256

# The bundle's attribute types and the Python type a fact value has in each (contracts/bundle.yaml). An enum
# value is text; money and quantities are integers of their unit.
PYTHON = {"text": "str", "enum": "str", "integer": "int", "boolean": "bool", "date": "date"}


@dataclass(frozen=True)
class Slot:
    kind: str  # the kind that declares it
    name: str
    table: str
    multivalued: bool
    type: str  # one of PYTHON's keys; for an arrow the id type of its target's root kind
    target: str | None = None  # an arrow's target kind
    inlined: bool = False

    @property
    def element(self) -> str:
        return f"{self.kind}.{self.name}"


@dataclass(frozen=True)
class Kind:
    id: str
    parent: str | None
    abstract: bool
    identifier: str | None
    id_type: str
    plane: str | None = None  # "control" for a kind of decided values (DV1); a data-plane kind has none
    owner: str | None = None  # who reviews a change to a control kind


class Schema:
    """A schema bundle as admission reads it. `sha256` is the bundle's canonical hash: every refusal names it."""

    def __init__(self, bundle: dict):
        if bundle.get("format") != "rede.schema-bundle/1":
            raise ValueError("not a schema bundle (format rede.schema-bundle/1)")
        self.sha256 = canonical_sha256(bundle)
        self.pack = bundle["pack"]["id"]
        self.kinds = {k["id"]: Kind(k["id"], k.get("parent"), bool(k.get("abstract")), k.get("identifier"),
                                    k["id_type"], k.get("plane"), k.get("owner")) for k in bundle["kinds"]}
        self.slots: dict[str, dict[str, Slot]] = {k: {} for k in self.kinds}
        for a in bundle.get("attributes", []):
            self.slots[a["kind"]][a["name"]] = Slot(a["kind"], a["name"], a["table"], bool(a.get("multivalued")),
                                                    a["type"])
        for a in bundle.get("arrows", []):
            target = a["target"]
            self.slots[a["kind"]][a["name"]] = Slot(a["kind"], a["name"], a["table"], bool(a.get("multivalued")),
                                                    self.kinds[self.root(target)].id_type, target,
                                                    bool(a.get("inlined")))

    def ancestors(self, kind: str) -> list[str]:
        """The kind itself, then its parent, up to the root."""
        out = []
        while kind:
            out.append(kind)
            kind = self.kinds[kind].parent
        return out

    def root(self, kind: str) -> str:
        return self.ancestors(kind)[-1]

    def control(self, kind: str) -> bool:
        """Whether a kind holds decided values (DV1): it or a kind above it says `plane: control`."""
        return any(self.kinds[k].plane == "control" for k in self.ancestors(kind))

    def slot(self, kind: str, name: str) -> Slot | None:
        """A slot of a kind, declared there or inherited."""
        for k in self.ancestors(kind):
            if name in self.slots[k]:
                return self.slots[k][name]
        return None
