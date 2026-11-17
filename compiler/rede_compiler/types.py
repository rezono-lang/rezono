"""One semantic type model for the compiler (S3a, ticket B09).

A value's type is said once, here, and every consumer projects it to the name its own output uses: the engine's
SQL type, the schema bundle's attribute type, the rule IR's column type, or calc's `number`/`boolean`. Before
B09 each consumer kept its own table from SQL names. These projections give exactly the names those tables
gave, so no output changes.

The model covers the seven cases of S3: a typed scalar, a quantity with its unit, money, a date, an enum (closed;
an open enum is representable but no reader makes one yet), a reference to an element of another kind (a RowRef:
the kind, and its root's identifier type), and a derived value (computed by a calc rule or derived relation).
Cardinality, world and provenance stay on the slot or relation that holds the value: they are not part of a
value's type.

A type does not decide what is allowed. The checks where the pack is read stay where they are; this module only
says what a value is and how each output names it.

A unit of measure (P10.3, ticket D04) is declared by a pack, never here: `Unit` is what a declaration means, an exact
factor of its dimension's base unit and the dimension as exponents of base dimensions, with the algebra the
dimension checks of calc and rules need (`plus`, `times`, `over`, `power`). Money in whole minor units of one
currency is the base unit of the dimension `money <currency>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction

# The base of a stored value: what the engine holds. `number` is calc's exact fraction (a numerator and a
# denominator in the engine), never a stored slot type.
STRING, INTEGER, BOOLEAN, DATE, NUMBER = "string", "integer", "boolean", "date", "number"
SCALARS = (STRING, INTEGER, BOOLEAN, DATE)
# LinkML roots that are never a Rede type: money and quantities are whole numbers of a unit (W3).
FLOATING = frozenset({"float", "double", "decimal"})

_SQL = {STRING: "VARCHAR", INTEGER: "BIGINT", BOOLEAN: "BOOLEAN", DATE: "DATE"}
_FROM_SQL = {sql: base for base, sql in _SQL.items()}
_BUNDLE = {STRING: "text", INTEGER: "integer", BOOLEAN: "boolean", DATE: "date"}
# The rule IR (rules/*.dl, ir/rules.json) has text and whole-number columns only.
_RULE = {STRING: "string", INTEGER: "integer"}
# Calc reads whole numbers as exact fractions and booleans as booleans; nothing else is a calc value.
_CALC = {INTEGER: NUMBER, BOOLEAN: BOOLEAN, NUMBER: NUMBER}


@dataclass(frozen=True)
class Type:
    """The type of one value. `base` is what is stored; the other fields say what the value means."""
    base: str  # one of SCALARS, or NUMBER for a calc value
    range: str | None = None  # the schema's name as written: the LinkML type, enum or class
    enum: str | None = None  # an enum value of this enum
    open: bool = False  # an open enum: values beyond the declared ones (no reader sets it yet)
    target: str | None = None  # a RowRef: an element of this kind; `base` is its root's identifier type
    currency: str | None = None  # money: whole minor units of this ISO 4217 currency
    unit: str | None = None  # a quantity: a number of this unit, a unit the pack declares (`Unit`); no conversion
    derived: str | None = None  # a derived value: the calc rule or derived relation that computes it

    def __post_init__(self) -> None:
        if self.base not in SCALARS and self.base != NUMBER:
            raise ValueError(f"no such base type: {self.base!r}")

    @property
    def case(self) -> str:
        """Which of the S3 cases this is: ref, enum, derived, money, quantity, date or scalar. A derived value
        is `derived` whatever it computes; its unit or currency stays on the type."""
        if self.target is not None:
            return "ref"
        if self.enum is not None:
            return "enum"
        if self.derived is not None:
            return "derived"
        if self.currency is not None:
            return "money"
        if self.unit is not None:
            return "quantity"
        return "date" if self.base == DATE else "scalar"

    @property
    def sql(self) -> str:
        """The engine's column type. A calc number has none: the engine holds it as two BIGINT columns."""
        if self.base == NUMBER:
            raise ValueError("a calc number is stored as a fraction, not as one SQL column")
        return _SQL[self.base]

    @property
    def bundle(self) -> str:
        """The schema bundle's attribute type (contracts/bundle.yaml): an enum is `enum`, else the base."""
        return "enum" if self.enum is not None else _BUNDLE[self.base]

    @property
    def semantic(self) -> dict:
        """The schema bundle's semantic type (B10, contracts/bundle.yaml SemanticType): the case and every field
        this model knows, so a consumer reads what a value means instead of guessing it. A field without a value
        is left out; nothing is inferred from a name. The dimension of a unit is the pack's `Unit` (P10.3); the bundle
        does not carry it yet."""
        fields = {"case": self.case, "base": self.base, "range": self.range, "enum": self.enum,
                  "open": True if self.open else None, "target": self.target, "currency": self.currency,
                  "unit": self.unit, "derived": self.derived}
        return {k: v for k, v in fields.items() if v is not None}

    @property
    def rule(self) -> str | None:
        """The rule IR's column type, or None when a rule cannot hold such a value."""
        return _RULE.get(self.base)

    @property
    def calc(self) -> str | None:
        """Calc's type (`number` or `boolean`), or None when calc cannot read such a value. A reference or an
        enum is never a calc value, whatever its base."""
        if self.target is not None or self.enum is not None:
            return None
        return _CALC.get(self.base)


def scalar(base: str, range: str | None = None) -> Type:
    return Type(base, range)


def of_sql(sql: str, range: str | None = None) -> Type:
    """The scalar whose engine type is `sql`."""
    return Type(_FROM_SQL[sql], range)


def linkml(root: str) -> str | None:
    """The base of a LinkML root type (after following `typeof`), or None when Rede has no such type."""
    return root if root in _SQL else None


def money(currency: str, range: str | None = None) -> Type:
    """An amount in whole minor units of `currency` (cents for EUR): never a fraction (W3)."""
    return Type(INTEGER, range, currency=currency)


def quantity(unit: str, base: str = NUMBER, range: str | None = None) -> Type:
    """A number of `unit`, by its name; the pack's declaration of that name (`Unit`) says its dimension (P10.3)."""
    return Type(base, range, unit=unit)


def enum(name: str, open: bool = False) -> Type:
    """A value of the enum `name`, stored as its text key."""
    return Type(STRING, name, enum=name, open=open)


def ref(target: str, id_base: str) -> Type:
    """A reference to an element of kind `target`, stored as its root's identifier (`id_base`)."""
    if id_base not in (STRING, INTEGER):
        raise ValueError(f"an identifier is text or a whole number, not {id_base!r}")
    return Type(id_base, target, target=target)


def derived(by: str, base: str) -> Type:
    """A value computed by `by` (a calc rule or derived relation)."""
    return Type(base, derived=by)


def of_slot(slot) -> Type:
    """The type of a slot's value, from the fields the pack reader sets (`rede_compiler.pack.Slot`). A slot that
    is an arrow refers to an element; its `sql_type` is its target root's identifier type once the pack is
    checked (`pack.check`)."""
    if slot.arrow:
        return ref(slot.range, _FROM_SQL[slot.sql_type])
    if slot.enum:
        return enum(slot.enum)
    if slot.currency:
        return money(slot.currency, slot.range)
    if getattr(slot, "unit", None):
        return quantity(slot.unit, _FROM_SQL[slot.sql_type], slot.range)
    return of_sql(slot.sql_type, slot.range)


def rule_type(sql: str) -> str | None:
    """The rule IR's column type of an engine type: of an identifier, a subject or a column. None if a rule
    cannot hold it."""
    return _RULE.get(_FROM_SQL.get(sql, ""))


# Units (P10.3). A pack declares them on LinkML types (pack.units); here is only what a declaration means.
DIMENSION = re.compile(r"^[a-z][a-z0-9_]*$")  # the name of a base dimension, such as data or time
# The definition of a unit by another: an optional exact factor (`1024`, `1/1000`, `2^30`), a declared unit, and
# optionally `per` a declared unit, as Reckon writes `unit GiB = 2^30 B` and `unit EurPerHour = money EUR per hour`.
DEFINITION = re.compile(r"^(?:(?P<n>[1-9][0-9]*)(?:\^(?P<e>[0-9]+)|/(?P<d>[1-9][0-9]*))?\s+)?"
                        r"(?P<unit>[A-Za-z][A-Za-z0-9_]*)(?:\s+per\s+(?P<per>[A-Za-z][A-Za-z0-9_]*))?$")


@dataclass(frozen=True)
class Unit:
    """A unit of measure: `factor` times the base of its dimension, and the dimension as sorted pairs of a base
    dimension and its exponent (none: a plain number). Two units are the same when factor and dimension are, so
    `Cents` and the minor unit of EUR are one; the name is only how a message names it."""
    name: str = field(compare=False)
    factor: Fraction = Fraction(1)
    dimension: tuple[tuple[str, int], ...] = ()

    @property
    def text(self) -> str:
        """The dimension in words: `data`, `money EUR`, `money EUR/time`, or `no dimension` for a plain number."""
        up = [d if e == 1 else f"{d}^{e}" for d, e in self.dimension if e > 0]
        down = [d if e == -1 else f"{d}^{-e}" for d, e in self.dimension if e < 0]
        if not up and not down:
            return "no dimension"
        return "·".join(up or ["1"]) + ("/" + "·".join(down) if down else "")

    @property
    def currency(self) -> str | None:
        """The currency when this is the minor unit of one (what `currency` on a slot means), else None."""
        if self.factor == 1 and len(self.dimension) == 1 and self.dimension[0][1] == 1 \
                and self.dimension[0][0].startswith("money "):
            return self.dimension[0][0][len("money "):]
        return None

    @property
    def plain(self) -> bool:
        """A plain number: no dimension and factor 1."""
        return not self.dimension and self.factor == 1

    def times(self, other: Unit) -> Unit:
        if other.plain or self.plain:
            return self if other.plain else other
        return Unit(f"{self.name}·{other.name}", self.factor * other.factor, _combine(self.dimension, other.dimension, 1))

    def over(self, other: Unit) -> Unit:
        if other.plain:
            return self
        return Unit(f"{'1' if self.plain else self.name}/{other.name}", self.factor / other.factor,
                    _combine(self.dimension, other.dimension, -1))

    def power(self, n: int) -> Unit:
        if self.plain or n == 1:
            return self
        return Unit(f"{self.name}^{n}", self.factor ** n, tuple((d, e * n) for d, e in self.dimension if e * n))

    def named(self, name: str) -> Unit:
        return Unit(name, self.factor, self.dimension)


PLAIN = Unit("a number without a unit")


def base_unit(name: str, dimension: str) -> Unit:
    """The base unit of a dimension: Reckon's `unit B = integer`, base of data."""
    return Unit(name, Fraction(1), ((dimension, 1),))


def money_unit(currency: str, name: str | None = None) -> Unit:
    """Whole minor units of `currency` (cents for EUR): the base unit of the dimension `money <currency>`."""
    return base_unit(name or currency, f"money {currency}")


def defined(name: str, text: str, declared: dict[str, Unit]) -> Unit:
    """The unit `name` defined as `text` (DEFINITION) by units already declared. Raises ValueError with what is
    wrong."""
    m = DEFINITION.match(text.strip())
    if not m:
        raise ValueError(f"{text!r} is no unit definition: write a whole factor, n/d or b^e, then a unit, "
                         "and optionally per a unit (such as 2^30 B)")
    n, e, d = int(m["n"] or 1), m["e"], m["d"]
    factor = Fraction(n) ** int(e) if e is not None else Fraction(n, int(d or 1))
    for u in (m["unit"], m["per"]):
        if u is not None and u not in declared:
            raise ValueError(f"{text!r}: {u} is no unit the pack declares")
    out = declared[m["unit"]]
    if m["per"] is not None:
        out = out.over(declared[m["per"]])
    return Unit(name, factor * out.factor, out.dimension)


def _combine(a: tuple, b: tuple, sign: int) -> tuple[tuple[str, int], ...]:
    out = dict(a)
    for d, e in b:
        out[d] = out.get(d, 0) + sign * e
    return tuple(sorted((d, e) for d, e in out.items() if e))
