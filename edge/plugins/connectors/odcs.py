"""The ODCS data contract of a Reckon Data schema (docs/reckon-data/l0.md §2.5; lane M, M09).

The contract describes the columnar form of a view (§4): what a reader of the Parquet files may rely on. It is
made from the schema document alone, through the library's own writer (`reckon_data.arrow.to_arrow` on no rows),
so a table, a column, its storage and whether it may be null are never restated here. What ODCS cannot say is in
`odcs.losses.yaml`.

- **One schema object per table** (§4.1): a kind table, a relation table per many-valued slot, and the side
  tables `$why` and `$src`. Its `id` is the table name with `$` written `-`, so another element can point at it.
- **One property per column**, with `physicalType` in §4.4's spelling, the nearest ODCS `logicalType`, and
  `required` when the column is not nullable. The key columns are the primary key, in column order.
- **Quality rules** for what the library's reader checks and a column type does not say: the state codes a slot
  allows, a value that is null exactly beside a state, a reason beside the state it may label, the pattern of a
  text type, the values of a closed enum, the bounds of an integer, a quantity and money, the members of a set
  (only of an element whose set is known; at least one for `+`). A rule that needs two columns is SQL that counts
  the rows that break it (`mustBe: 0`), with every name quoted, so it runs as written.
- **A reference** inside the pack is a `foreignKey` relationship to the target's `$id` (not to a kind with
  subkinds, whose elements are spread over its table and theirs); a relation table points
  at its owner the same way.
- **What ODCS has no member for** goes in `customProperties`: `reckonTable` and `reckonField` (the Arrow metadata
  of §4.2, with the schema id and the pins), `reckonExtension` (§4.5: unit, money, a reference with its pins) and
  `reckonWorld` (open or closed). A `map` entry of the schema is an authoritative definition.
- `version` is the schema id with the pins it was given (§6.4): `s-…`, `s-…@d-…` or `s-…@m-…@d-…`. `id` is the
  schema's `base`: it stays the same for every schema of a lineage.

The ODCS version is one constant. Which version and which field mapping Rede settles on is open (Q12).

    python edge/plugins/connectors/odcs.py <schema.json>   # prints the contract as YAML
"""

import json
import re
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))  # reckon_data lives at the repository root

import pyarrow as pa  # noqa: E402
import yaml  # noqa: E402

from reckon_data import arrow, l0  # noqa: E402

ODCS_VERSION = "v3.2.0"  # Q12: the one place that names it
REASON_CODE = "^([a-z][a-z0-9_]*)?$"  # §2.3: empty, or a reason code
CUSTOM = ("reckonTable", "reckonField", "reckonExtension", "reckonWorld")


class OdcsError(l0.L0Error):
    """A schema document that has no ODCS contract here."""


def _fail(where: str, what: str):
    raise OdcsError(f"{where}: {what}")


def stable_id(name: str) -> str:
    """An ODCS stable id (`[A-Za-z0-9_-]+`) for a table or a column: `$` and every other character outside it
    become `-`. `contract` refuses a schema in which two names of one scope get the same id."""
    return re.sub(r"[^A-Za-z0-9_]", "-", name)


def _path(table: str, column: str) -> str:
    """The fully qualified reference to a column of this contract."""
    return f"schema/{stable_id(table)}/properties/{stable_id(column)}"


def _q(name: str) -> str:
    """A quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _text(value: str) -> str:
    """A SQL text literal."""
    return "'" + value.replace("'", "''") + "'"


def spelled(t: pa.DataType) -> str:
    """An Arrow type in §4.4's spelling, as `l0.storage` writes it."""
    if pa.types.is_struct(t):
        return "struct<" + ",".join(f"{f.name}:{spelled(f.type)}" for f in t) + ">"
    if pa.types.is_timestamp(t):
        return f'timestamp({t.unit},"{t.tz}")'
    if pa.types.is_decimal(t):
        return f"decimal128({t.precision},{t.scale})"
    for test, name in ((pa.types.is_string, "utf8"), (pa.types.is_boolean, "bool"), (pa.types.is_int8, "int8"),
                       (pa.types.is_int64, "int64"), (pa.types.is_date32, "date32")):
        if test(t):
            return name
    _fail(str(t), "an Arrow type that §4.4 does not name")


def _logical(t: pa.DataType) -> dict:
    """The nearest ODCS logical type. The storage is in `physicalType`; this is for a reader that knows ODCS only."""
    if pa.types.is_struct(t):
        return {"logicalType": "object", "properties": [_column(f) for f in t]}
    if pa.types.is_int8(t) or pa.types.is_int64(t):
        return {"logicalType": "integer", "logicalTypeOptions": {"format": "i8" if pa.types.is_int8(t) else "i64"}}
    if pa.types.is_decimal(t):
        return {"logicalType": "integer" if t.scale == 0 else "number"}
    for test, name in ((pa.types.is_string, "string"), (pa.types.is_boolean, "boolean"),
                       (pa.types.is_date32, "date"), (pa.types.is_timestamp, "timestamp")):
        if test(t):
            return {"logicalType": name}
    _fail(str(t), "an Arrow type that §4.4 does not name")


def _column(f: pa.Field) -> dict:
    return {"id": stable_id(f.name), "name": f.name, "physicalType": spelled(f.type), **_logical(f.type),
            "required": not f.nullable}


def _custom(**properties) -> list:
    return [{"property": name, "value": value} for name, value in properties.items()]


def _rule(rule_id: str, dimension: str, **members) -> dict:
    """One quality rule: the count of what breaks it must be 0."""
    kind = "sql" if "query" in members else "library"
    return {"id": rule_id, "type": kind, "dimension": dimension, **members, "mustBe": 0}


def _count(table: str, where: str) -> str:
    return f"SELECT COUNT(*) FROM {_q(table)} WHERE {where}"


def _reasons(schema: dict, state: str):
    """The reason codes a state may carry when the schema declares `reasons` (else None), and the core codes
    that label other states only (§2.3)."""
    foreign = sorted(c for c, states in l0.CORE_REASONS.items() if state not in states)
    declared = schema.get("reasons")
    if declared is None:
        return None, foreign
    allowed = {c for c, states in l0.CORE_REASONS.items() if state in states and c not in declared}
    allowed |= {c for c, r in declared.items() if state in r["states"] and c not in foreign}
    return sorted(allowed), foreign


def _reason_rule(schema: dict, table: str, slot_name: str, slot: dict) -> dict:
    """A reason is empty beside state 0, and beside another state it is empty or a code that state may carry."""
    state, reason = _q(f"{slot_name}$state"), _q(f"{slot_name}$reason")
    broken = [f"({state} = 0 AND {reason} <> '')"]
    for name in slot["states"]:
        if name == "known":
            continue
        allowed, foreign = _reasons(schema, name)
        code = arrow.STATE_CODE[name]
        if allowed is not None:
            listed = ", ".join(_text(c) for c in ["", *allowed])
            broken.append(f"({state} = {code} AND {reason} NOT IN ({listed}))")
        elif foreign:  # a core code labels its own states only
            broken.append(f"({state} = {code} AND {reason} IN ({', '.join(_text(c) for c in foreign)}))")
    return _rule("reason", "conformity", query=_count(table, " OR ".join(broken)))


def _ceil(f: Fraction) -> int:
    return -(-f.numerator // f.denominator)


def _bound_rule(schema: dict, table: str, column: str, slot: dict, t: dict):
    """The bounds of the type and of the slot (the reader holds both), on the stored number. None when there is
    no bound or the storage cannot be compared: an integer stored as text, a ratio (`odcs.losses.yaml`)."""
    of = t["of"]
    if of not in ("Integer", "Quantity", "Money") or (of == "Integer" and l0.storage(schema, slot) == "utf8"):
        return None
    per_unit = Fraction(1)
    if of == "Quantity":
        per_unit = Fraction(t.get("factor", "1")) * 10 ** int(t.get("scale", "0"))
        if per_unit <= 0:
            _fail(slot["type"], "a quantity whose factor is not positive has no bounds on its stored integer")
    scale = int(t.get("scale", "0")) if of == "Money" else 0
    lows = [Fraction(s["min"]) for s in (t, slot) if "min" in s]
    highs = [Fraction(s["max"]) for s in (t, slot) if "max" in s]
    if not lows and not highs:
        return None

    def literal(f: Fraction, up: bool) -> str:
        """The nearest stored number inside the bound, as exact SQL: an integer, or a decimal at the scale."""
        whole = f * per_unit * 10**scale
        n = _ceil(whole) if up else whole.numerator // whole.denominator
        if not scale:
            return str(n)
        digits = str(abs(n)).rjust(scale + 1, "0")
        return ("-" if n < 0 else "") + digits[:-scale] + "." + digits[-scale:]

    broken = []
    if lows:
        broken.append(f"{_q(column)} < {literal(max(lows), True)}")
    if highs:
        broken.append(f"{_q(column)} > {literal(min(highs), False)}")
    return _rule("bounds", "conformity", query=_count(table, " OR ".join(broken)))


def _value_rules(schema: dict, table: str, column: str, slot: dict) -> list:
    """What the type of a value or member column adds that its storage does not say."""
    if "ref" in slot:
        return []
    t = l0._local_type(schema, slot["type"])
    if t is None:  # an imported type: its members are in the other pack's schema document
        return []
    rules = []
    if t["of"] == "Text" and "pattern" in t:  # the reader matches the whole text
        rules.append(_rule("pattern", "conformity", metric="invalidValues",
                           arguments={"pattern": f"^(?:{t['pattern']})$"}))
    elif t["of"] == "Enum":
        enum = schema["enums"][t["enum"]]
        if isinstance(enum, list):  # closed; an open enum may gain values, so its members are not a rule
            rules.append(_rule("values", "conformity", metric="invalidValues", arguments={"validValues": list(enum)}))
    bound = _bound_rule(schema, table, column, slot, t)
    return rules + ([bound] if bound else [])


def _same_key(keys: list) -> str:
    return " AND ".join(f"o.{_q(k)} = m.{_q(k)}" for k in keys)


def _foreign_key(to) -> dict:
    return {"type": "foreignKey", "to": to}


def _definitions(schema: dict, name: str) -> dict:
    """A `map` entry of the schema (§2.1) as an authoritative definition: the external term the name stands for."""
    iri = schema.get("map", {}).get(name)
    return {"authoritativeDefinitions": [{"url": iri, "type": "businessDefinition"}]} if isinstance(iri, str) else {}


def _check_ids(where: str, names: list):
    ids = {}
    for name in names:
        other = ids.setdefault(stable_id(name), name)
        if other != name:
            _fail(where, f"`{other}` and `{name}` get the same ODCS id `{stable_id(name)}`")


def contract(schema: dict, pin: dict | None = None) -> dict:
    """The ODCS contract of a schema document. `pin` is `to_arrow`'s: it MAY carry `dataset`, `manifest` and
    `table_hash`; an epoch pin needs its hash pin (§6.4)."""
    tables = arrow.to_arrow(schema, [], pin)  # checks the schema document and the pin
    sid = l0.schema_id(schema)
    pins = {k: pin[k] for k in ("manifest", "dataset") if pin and k in pin}
    _check_ids("schema", list(tables))
    objects = {}
    for name, table in tables.items():
        _check_ids(name, table.schema.names)
        meta = json.loads(table.schema.metadata[b"reckon"])
        columns = {}
        for f in table.schema:
            column = _column(f)
            md = f.metadata or {}
            extra = {"reckonField": json.loads(md[b"reckon"])}
            if b"ARROW:extension:name" in md:
                extra["reckonExtension"] = {"name": md[b"ARROW:extension:name"].decode("utf-8"),
                                            "metadata": json.loads(md[b"ARROW:extension:metadata"])}
            column["customProperties"] = _custom(**extra)
            columns[f.name] = column
        objects[name] = {"id": stable_id(name), "name": name, "physicalType": "table", "logicalType": "object",
                         "properties": columns, "customProperties": _custom(reckonTable=meta)}

    def add(table: str, column: str | None, member: str, item: dict):
        target = objects[table] if column is None else objects[table]["properties"][column]
        target.setdefault(member, []).append(item)

    for name, kind in schema["kinds"].items():
        keys = ["$id"] + [f.name for f in arrow._version_fields(kind)]
        objects[name]["customProperties"] += _custom(reckonWorld=kind["world"])
        objects[name].update(_definitions(schema, name))
        for position, key in enumerate(keys, start=1):
            objects[name]["properties"][key].update(primaryKey=True, primaryKeyPosition=position)
        id_type = l0._local_type(schema, kind["id"]["type"])
        if id_type is not None and id_type["of"] == "Text" and "pattern" in id_type:
            add(name, "$id", "quality", _value_rules(schema, name, "$id", {"type": kind["id"]["type"]})[0])
        for slot_name, slot in kind["slots"].items():
            if "inverse" in slot:  # the same relation as its forward slot; no table and no column (§4.1)
                continue
            many = slot["card"] in ("*", "+")
            stated = slot["states"] != ["known"]
            home = f"{name}__{slot_name}" if many else name
            objects[home]["properties"][slot_name].update(_definitions(schema, f"{name}.{slot_name}"))
            for rule in _value_rules(schema, home, slot_name, slot):
                add(home, slot_name, "quality", rule)
            # A foreign key names one row of one table. A versioned target has a row per version, a target in
            # another pack is not in this contract, and an element of a kind with subkinds is a row of that
            # kind's table or of a subkind's (§4.1): `reckonExtension` carries the target, and the loss list
            # says so.
            if ("ref" in slot and "." not in slot["ref"] and "versioned" not in schema["kinds"][slot["ref"]]
                    and not any(k.get("parent") == slot["ref"] for k in schema["kinds"].values())):
                add(home, slot_name, "relationships", _foreign_key(_path(slot["ref"], "$id")))
            if stated:
                codes = [arrow.STATE_CODE[s] for s in slot["states"]]
                add(name, f"{slot_name}$state", "quality",
                    _rule("states", "conformity", metric="invalidValues", arguments={"validValues": codes}))
                add(name, f"{slot_name}$reason", "quality", _reason_rule(schema, name, slot_name, slot))
                if "reasons" not in schema:  # every code of the right form is accepted (§2.3)
                    add(name, f"{slot_name}$reason", "quality",
                        _rule("reason-code", "conformity", metric="invalidValues", arguments={"pattern": REASON_CODE}))
            if stated and not many:
                value, state = _q(slot_name), _q(f"{slot_name}$state")
                add(name, slot_name, "quality", _rule("null-beside-state", "consistency", query=_count(
                    name, f"({value} IS NULL AND {state} = 0) OR ({value} IS NOT NULL AND {state} <> 0)")))
            if not many:
                continue
            objects[home]["customProperties"] += _custom(reckonWorld=slot.get("world", "closed"))
            for position, key in enumerate([*keys, slot_name], start=1):  # a set: the whole row is the key
                objects[home]["properties"][key].update(primaryKey=True, primaryKeyPosition=position)
            add(home, None, "relationships",
                {"type": "foreignKey", "from": [_path(home, k) for k in keys], "to": [_path(name, k) for k in keys]})
            # A member belongs to an element, and only to one whose set is known; `+` needs one for such an element.
            known = f"o.{_q(slot_name + '$state')} = 0" if stated else ""
            add(home, None, "quality", _rule("members", "consistency", query=(
                f"SELECT COUNT(*) FROM {_q(home)} AS m WHERE NOT EXISTS (SELECT 1 FROM {_q(name)} AS o "
                f"WHERE {' AND '.join(filter(None, [_same_key(keys), known]))})")))
            if slot["card"] == "+":
                add(home, None, "quality", _rule("at-least-one", "completeness", query=(
                    f"SELECT COUNT(*) FROM {_q(name)} AS o WHERE {known + ' AND ' if known else ''}NOT EXISTS "
                    f"(SELECT 1 FROM {_q(home)} AS m WHERE {_same_key(keys)})")))

    for item in objects.values():
        item["properties"] = list(item["properties"].values())
    return {
        "apiVersion": ODCS_VERSION,
        "kind": "DataContract",
        "id": schema["base"],
        "name": schema["pack"],
        "version": "".join([sid, *(f"@{pins[k]}" for k in ("manifest", "dataset") if k in pins)]),
        "schema": list(objects.values()),
    }


def to_yaml(schema: dict, pin: dict | None = None) -> str:
    """The contract as YAML, ODCS's own form: the same text for the same schema document and pin."""
    return yaml.safe_dump(contract(schema, pin), sort_keys=False, allow_unicode=True, default_flow_style=False,
                          width=2**31 - 1)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    sys.stdout.write(to_yaml(json.loads(Path(args[0]).read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
