"""The logical hash of the publication (docs/publication/l0.md §6.2), on Rezono's one canonical hash.

Every hash here is `rezono_canon.canonical_sha256`: SHA-256 over the canonical JSON of a value
(docs/contracts.md#canonical-hash). This module only decides *which* value is hashed: the hash
rows of each table, their order, and the objects that combine table hashes into the dataset and
annotation hashes. It never hashes bytes of its own and never replaces `Snapshot.sha256`.

Input is a schema document (§2) and the rows of a dataset in row JSON (§3). The hash assumes a
dataset a reader has accepted; it checks only what the hash itself needs: a known state, a whole
stored integer for `Quantity` and `Money`, no `null`, and no two hash rows with one key.
"""

import re
from fractions import Fraction

from rezono_canon import CanonError, canonical_json, canonical_sha256

__all__ = [
    "HashError",
    "H",
    "CJ",
    "EMPTY",
    "schema_id",
    "hash_rows",
    "table_hash",
    "dataset_hash",
    "annotation_hash",
    "control_tables",
    "definition_hash",
    "hashes",
]


class HashError(ValueError):
    """A dataset the logical hash cannot be computed for."""


def H(value) -> str:
    """`canonical_sha256`, with a value the canon refuses (a float) as a `HashError`."""
    try:
        return canonical_sha256(value)
    except CanonError as e:
        raise HashError(str(e)) from e


def CJ(value) -> str:
    """`canonical_json`, with a value the canon refuses (a float) as a `HashError`."""
    try:
        return canonical_json(value)
    except CanonError as e:
        raise HashError(str(e)) from e


EMPTY = H([])  # 4f53cda1…b945, the hash of an empty table

_STATES = {"$na": "not_applicable", "$unknown": "unknown", "$invalid": "invalid"}
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")
_RATIO = re.compile(r"-?(0|[1-9][0-9]*)/[1-9][0-9]*")
_MONEY = re.compile(r"(?P<cur>\S+) (?P<num>-?(0|[1-9][0-9]*)(\.(?P<dec>[0-9]+))?)(/(?P<per>\S+))?")
_PACK_REF = re.compile(
    r"[a-z][a-z0-9]*(-[a-z0-9]+)*@s-[0-9a-f]{64}(@m-[0-9]+)?(@d-[0-9a-f]{64})?:[A-Z][A-Za-z0-9]*/"
)


def schema_id(document: dict) -> str:
    """`"s-" + H(document)` (§2.2)."""
    return "s-" + H(document)


def _state(value):
    """`(state, reason)` for a state object, `None` for a known value."""
    if isinstance(value, dict) and len(value) == 1:
        (k, reason), = value.items()
        if k in _STATES:
            if not isinstance(reason, str):
                raise HashError(f"reason of {k} is not text: {reason!r}")
            return _STATES[k], reason
    return None


def _state_object(state):
    return {"$state": state[0], "$reason": state[1]}


def _many(slot: dict) -> bool:
    return slot["card"] in ("*", "+")


def _type(schema: dict, name: str) -> dict:
    """The type a slot names: a local type, or a core type (`of` is the name itself)."""
    return schema.get("types", {}).get(name, {"of": name})


def _scaled(number: Fraction, scale: int, what: str) -> str:
    stored = number * 10**scale
    if stored.denominator != 1:
        raise HashError(f"{what}: the stored integer is not whole")
    return str(stored.numerator)


def _quantity(t: dict, text: str) -> str:
    """The stored integer (value × factor × 10^scale) as decimal text (§3.2)."""
    number, _, unit = text.partition(" ")
    if unit != t["unit"]:
        raise HashError(f"{text!r}: unit is not {t['unit']}")
    if _DECIMAL.fullmatch(number):
        value = Fraction(number)
    elif _RATIO.fullmatch(number):
        value = Fraction(number)
    else:
        raise HashError(f"{text!r}: not an exact decimal or fraction")
    return _scaled(value * Fraction(t.get("factor", "1")), int(t.get("scale", "0")), text)


def _money(t: dict, text: str) -> str:
    """The stored integer at `scale` as decimal text: the literal's digits (§3.2)."""
    m = _MONEY.fullmatch(text)
    scale = int(t.get("scale", "0"))
    if not m or len(m["dec"] or "") != scale or m["per"] != t.get("per"):
        raise HashError(f"{text!r}: not a money literal with {scale} decimals")
    return _scaled(Fraction(m["num"]), scale, text)


def _period(text: str):
    for sep in ("..<", ".."):
        a, found, b = text.partition(sep)
        if found:
            return {"from": a, "to": b}
    raise HashError(f"{text!r}: not a period")


def _payload(schema: dict, slot: dict, value):
    """The payload of one known value (§3.2): what columns and the hash hold."""
    if value is None:
        raise HashError("null never reaches the hash (H9)")
    if "ref" in slot:
        target = value["$ref"]
        if "." in slot["ref"]:  # another pack: the id is everything after the first `/` after <Kind>
            m = _PACK_REF.match(target)
            if not m:
                raise HashError(f"{target!r}: not a pack reference")
            return target[m.end():]
        return target
    t = _type(schema, slot["type"])
    of = t["of"]
    if of == "Quantity":
        return _quantity(t, value)
    if of == "Money":
        return _money(t, value)
    if of == "Period":
        return _period(value)
    if of == "Integer" and isinstance(value, int) and not isinstance(value, bool):
        return str(value)  # the normal text: 42 and "42" (LD2) are one payload, also as a member
    return value  # Text, Ratio, Date, DateTime, Bool, Enum


def _member(payload) -> str:
    """A relation member as a key part: the payload if it is text, else its canonical JSON."""
    return payload if isinstance(payload, str) else CJ(payload)


def _version(kind: dict, row: dict) -> list:
    """`[CJ($valid), known]` for a versioned kind (§6.2 step 1), `[]` otherwise."""
    if "versioned" not in kind:
        return []
    known = row.get("$known", "") if "known" in kind["versioned"] else ""
    return [CJ(row.get("$valid", {})), known]


def _sorted(rows: list, table: str) -> list:
    """Hash order: by the UTF-8 bytes of `CJ($key)` (step 3). Two rows with one key: invalid."""
    keyed = sorted(((CJ(r["$key"]).encode("utf-8"), r) for r in rows), key=lambda kr: kr[0])
    for (a, _), (b, _) in zip(keyed, keyed[1:]):
        if a == b:
            raise HashError(f"{table}: two hash rows with key {a.decode('utf-8')}")
    return [r for _, r in keyed]


def hash_rows(schema: dict, rows: list) -> dict:
    """The sorted hash rows of every table: kind tables, relation tables, `$why` and `$src`."""
    tables = {}
    for name, kind in schema["kinds"].items():
        tables[name] = []
        for slot_name, slot in kind["slots"].items():
            if _many(slot) and "inverse" not in slot:
                tables[f"{name}__{slot_name}"] = []
    side = {"$why": [], "$src": []}

    for row in rows:
        name = row["$kind"]
        kind = schema["kinds"].get(name)
        if kind is None:
            raise HashError(f"unknown kind {name!r}")
        version = _version(kind, row)
        key = [row["$id"], *version]
        hrow = {"$key": key}
        members = {}  # slot -> member key parts, for the side tables
        for slot_name, slot in kind["slots"].items():
            if "inverse" in slot:
                continue
            if slot_name not in row:
                raise HashError(f"{name}/{row['$id']}: slot {slot_name} is absent; write its state")
            value = row[slot_name]
            state = _state(value)
            if not _many(slot):
                hrow[slot_name] = _state_object(state) if state else _payload(schema, slot, value)
            elif state:
                hrow[slot_name] = _state_object(state)
            else:
                ms = [_member(_payload(schema, slot, v)) for v in value]
                members[slot_name] = ms
                tables[f"{name}__{slot_name}"].extend({"$key": [row["$id"], *version, m]} for m in ms)
        tables[name].append(hrow)

        v, k = version if version else ["", ""]
        for slot_name, proof in row.get("$why", {}).items():
            slot = kind["slots"].get(slot_name, {})
            if slot_name != "$id" and _many(slot):  # member payload -> URI
                for m, uri in proof.items():
                    side["$why"].append({"$key": [name, row["$id"], slot_name, m, v, k], "proof": uri})
            else:
                side["$why"].append({"$key": [name, row["$id"], slot_name, "", v, k], "proof": proof})
        for slot_name, sources in row.get("$src", {}).items():
            for source in sources:  # one hash row per Source object
                side["$src"].append({"$key": [name, row["$id"], slot_name, "", v, k, CJ(source)]})

    out = {t: _sorted(rs, t) for t, rs in tables.items()}
    out.update({t: _sorted(rs, t) for t, rs in side.items()})
    return out


def table_hash(rows: list) -> str:
    """`H([row, …])` over hash rows in hash order (step 4)."""
    return H(rows)


def dataset_hash(schema_ref: str, table_hashes: dict) -> str:
    """`"d-" + H({"schema", "tables"})` over every kind and relation table, empty ones too (step 5)."""
    return "d-" + H({"schema": schema_ref, "tables": table_hashes})


def annotation_hash(dataset: str, why: str, src: str) -> str:
    """`H({"dataset", "tables": {"$src", "$why"}})`: the side tables, outside the dataset hash."""
    return H({"dataset": dataset, "tables": {"$src": src, "$why": why}})


def control_tables(schema: dict) -> list:
    """The kind and relation tables of the control kinds (l0.md §3.7), also empty ones."""
    return [t for name, kind in schema["kinds"].items() if kind.get("plane") == "control"
            for t in [name] + [f"{name}__{s}" for s, slot in kind["slots"].items()
                               if _many(slot) and "inverse" not in slot]]


def definition_hash(schema_ref: str, table_hashes: dict, control: list) -> str:
    """`"c-" + H({"schema", "tables"})` over the control kinds' tables only (§3.7): never changes with a fact."""
    return "c-" + H({"schema": schema_ref, "tables": {t: table_hashes[t] for t in control}})


def hashes(schema: dict, rows: list) -> dict:
    """Every hash of §6.2 for one dataset: tables, side tables, dataset, annotation, and definition (§3.7)."""
    rows_by_table = hash_rows(schema, rows)
    side = {t: table_hash(rows_by_table.pop(t)) for t in ("$why", "$src")}
    tables = {t: table_hash(rs) for t, rs in rows_by_table.items()}
    dataset = dataset_hash(schema_id(schema), tables)
    return {
        "schema": schema_id(schema),
        "tables": tables,
        "dataset": dataset,
        "side_tables": side,
        "annotation": annotation_hash(dataset, side["$why"], side["$src"]),
        "definition": definition_hash(schema_id(schema), tables, control_tables(schema)),
    }
