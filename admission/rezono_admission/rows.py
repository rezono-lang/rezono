"""Part (a) of admission: the rows of a fact document, validated against a schema (ruling 2 of 11-11-2026).

A fact document is records per kind ({kind: [record, ...]}). `rows` gives the rows per engine table that the
compiler's loader gives (rezono_compiler.facts.rows_of; the parity test holds them equal byte for byte), and every
refusal, not only the first. A refusal is a code in L0's form (`^[a-z][a-z0-9_]*$`), where it was found, and the
hash of the schema it was judged against. A record with a refusal gives no rows; the records beside it are
still judged, so one pass names everything that is wrong.

This is what Reckon Data's L0 reader replaces later, behind the same interface; the step around it (step.py)
stays.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from urllib.parse import quote

from .schema import PYTHON, Schema, Slot

ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
TYPES = {"str": str, "int": int, "bool": bool, "date": datetime.date}

CODES = (
    "document_null",  # a null document: a file without records is {}
    "document_not_mapping",  # a document that is not records per kind
    "section_null",  # a null section: an empty relation is []
    "section_not_list",
    "unknown_kind",
    "kind_without_identifier",  # records of a kind whose root has no identifier: give them inlined
    "kind_abstract",
    "record_not_mapping",
    "record_without_identifier",
    "unknown_slot",
    "dictionary_value_not_record",  # LinkML's dictionary form with a value that is not a record
    "wrong_type",  # a value that is not of its slot's type
    "decision_missing",  # a record of a control kind that names no decision (DV1)
    "source_missing",  # a batch without a source (step.py)
    "control_unreviewed",  # a batch with records of a control kind that comes from no reviewed proposal (step.py)
)


@dataclass(frozen=True)
class Refusal:
    code: str
    where: str
    schema: str

    def as_dict(self) -> dict:
        return {"code": self.code, "where": self.where, "schema": self.schema}

    def diagnostic(self) -> dict:
        """The refusal in the diagnostic contract (contracts/diagnostic.yaml, D15): an error with its code and its
        place, left out for the whole document. A reader that has the file adds the span (the compiler's loader
        does); the schema hash stays in as_dict."""
        return {"code": self.code, "severity": "error"} | ({"where": self.where} if self.where else {})


class _Refused(Exception):
    def __init__(self, code: str, where: str):
        self.code, self.where = code, where


def rows(schema: Schema, data, *, on_record=None, on_row=None, context=None
         ) -> tuple[dict[str, list[tuple]], list[Refusal]]:
    """Records per kind as rows per engine table, sorted as the compiler sorts them, and every refusal. With a
    refusal of the document itself there are no rows. The generated tables of sealed kinds (decision E3,
    `<kind>__row_sha256`) are not made here: the bundle does not say yet which kinds are sealed.

    An observer, for a caller that needs to know where each row comes from (the compiler's sources): `on_record(
    kind, id, context)` is called for every record, inlined ones too, and returns the context of its rows and of
    the records inlined in it (a record of the document gets `context`); `on_row(table, row, kind, id, slot,
    context)` is called for every row as it is made, with `slot` None for a row of a kind's table. Both are
    optional and change nothing that is returned; an exception they raise is the caller's and passes through."""
    out: dict[str, list[tuple]] = {}
    refusals: list[Refusal] = []

    def refuse(code: str, where: str) -> None:
        refusals.append(Refusal(code, where, schema.sha256))

    if data is None:
        refuse("document_null", "")
        return {}, refusals
    if not isinstance(data, dict):
        refuse("document_not_mapping", "")
        return {}, refusals
    bad = False
    for kind, records in data.items():
        if records is None:
            refuse("section_null", str(kind))
            bad = True
        elif not isinstance(records, list):
            refuse("section_not_list", str(kind))
            bad = True
    if bad:
        return {}, refusals
    for kind, records in data.items():
        if kind not in schema.kinds:
            refuse("unknown_kind", str(kind))
            continue
        if schema.kinds[schema.root(kind)].identifier is None:
            refuse("kind_without_identifier", kind)
            continue
        for n, record in enumerate(records, 1):
            mine: dict[str, list[tuple]] = {}
            try:
                _add(schema, kind, record, None, mine, f"{kind}[{n}]", (on_record, on_row), context)
            except _Refused as r:
                refuse(r.code, r.where)
                continue
            for table, rs in mine.items():
                out.setdefault(table, []).extend(rs)
    return {t: sorted(r, key=repr) for t, r in sorted(out.items())}, refusals


def _add(schema: Schema, kind: str, record, derived_id: str | None, rows: dict, where: str,
         watch=(None, None), context=None):
    """One record of `kind` (and its inlined elements) into `rows`; the first refusal of the record is raised."""
    if schema.kinds[kind].abstract:
        raise _Refused("kind_abstract", where)
    if not isinstance(record, dict):
        raise _Refused("record_not_mapping", where)
    ident = schema.kinds[schema.root(kind)].identifier
    record = dict(record)
    if ident is not None and ident not in record:
        raise _Refused("record_without_identifier", where)
    eid = record.pop(ident) if ident is not None else derived_id
    if eid is None:
        raise _Refused("kind_without_identifier", where)
    eid = _typed(schema.kinds[schema.root(kind)].id_type, eid, f"{where}.{ident}")
    # A decided value names the decision that set it (DV1; Reckon Data L0 §3.7): without one it is no value.
    if schema.control(kind):
        given = record.get("decision")
        given = given if isinstance(given, list) else [given]
        if len(given) != 1 or given[0] in (None, ""):  # exactly one decision row, and not an empty one
            raise _Refused("decision_missing", f"{where}.decision")
    on_record, on_row = watch
    if on_record:
        context = on_record(kind, eid, context)
    for a in schema.ancestors(kind):
        rows.setdefault(a, []).append((eid,))
        if on_row:
            on_row(a, (eid,), kind, eid, None, context)
    for name, value in record.items():
        s = schema.slot(kind, name)
        if s is None:
            raise _Refused("unknown_slot", f"{where}.{name}")
        for n, v in enumerate(_values(schema, s, value, f"{where}.{name}"), 1):
            if s.inlined and isinstance(v, dict):
                v = _add(schema, s.target, v, embedded_id(eid, s, n if s.multivalued else None), rows,
                         f"{where}.{name}[{n}]", watch, context)
            row = (eid, _typed(s.type, v, f"{where}.{name}"))
            rows.setdefault(s.table, []).append(row)
            if on_row:
                on_row(s.table, row, kind, eid, name, context)
    return eid


def _values(schema: Schema, s: Slot, value, where: str) -> list:
    """The values of one slot in a record: a list gives one row per item; a multivalued inlined slot whose target
    has an identifier also takes LinkML's dictionary form (each key an element's id, each value its record)."""
    if isinstance(value, list):
        return value
    ident = schema.kinds[schema.root(s.target)].identifier if s.target else None
    if s.multivalued and s.inlined and ident and isinstance(value, dict) and ident not in value:
        out = []
        for key, rest in value.items():
            if rest is not None and not isinstance(rest, dict):
                raise _Refused("dictionary_value_not_record", f"{where}.{key}")
            out.append({**(rest or {}), ident: key})
        return out
    return [value]


def embedded_id(parent_id, slot: Slot, position: int | None = None) -> str:
    """The id of an embedded element: the parent's id escaped, the slot's element id, and in a list the
    element's position from 1. Escaping '%' and '/' keeps two parents or slots from giving one id."""
    base = f"{quote(str(parent_id), safe='')}/{slot.element}"
    return base if position is None else f"{base}/{position}"


def _typed(bundle_type: str, v, where: str):
    """The value in its engine type. A date may also be ISO text, because JSON has no dates."""
    t = TYPES[PYTHON[bundle_type]]
    if t is datetime.date and isinstance(v, str) and ISO_DATE.match(v):
        try:
            return datetime.date.fromisoformat(v)
        except ValueError:
            pass
    if not isinstance(v, t) or (t is int and isinstance(v, bool)) or (t is datetime.date and isinstance(v, datetime.datetime)):
        raise _Refused("wrong_type", where)
    return v
