"""The columnar form of Reckon Data: row JSON ↔ Arrow ↔ Parquet (docs/reckon-data/l0.md §4).

- `to_arrow(schema, rows, pin)`: one Arrow table per kind, per many-valued slot (a relation table) and per side
  table (`$why`, `$src`), with the `reckon` metadata on the schema and on every field (§4.2), states as columns
  (§4.3), the storage of §4.4 and the extension metadata of §4.5. A writer produces only valid output, so the rows
  are read by `l0.read_rows` first.
- `from_arrow(schema, tables)`: the rows back, in their normal form. A reader rejects what disagrees with the
  schema document: a float, another storage, extension metadata that does not restate the schema, a value beside
  a state, a null beside a known state. It takes everything from the schema document and the column names, so a
  file without field metadata (Parquet written without `ARROW:schema`, C04) reads the same.
- `write_parquet`, `read_parquet`: one Parquet file per table; pyarrow embeds `ARROW:schema`.
- `normal_rows(schema, rows)`: rows in the order and form every writer here produces (hash order, members in hash
  order), so a round trip is byte-equal in canonical JSON (T01).

The logical hash is `reckon_data.hash` on the rows; this module never hashes bytes. Exact values only: Arrow
decimals carry `decimal.Decimal`, never a float. Money literals are written with the ISO 4217 code
(`"EUR 12.30"`): the schema document does not name a currency symbol, so a symbol cannot be restored (l0.md Q18).
"""

import datetime
import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from rezono_canon import canonical_json

from reckon_data import l0

__all__ = ["ColumnarError", "arrow_type", "to_arrow", "from_arrow", "normal_rows", "write_parquet",
           "read_parquet"]

STATE_CODE = {"known": 0, "not_applicable": 1, "unknown": 2, "invalid": 3}  # §3.3
STATE_KEY = {"not_applicable": "$na", "unknown": "$unknown", "invalid": "$invalid"}
_DEC0 = pa.decimal128(38, 0)


class ColumnarError(l0.L0Error):
    """A columnar file that does not read as Reckon Data."""


def _fail(where: str, what: str):
    raise ColumnarError(f"{where}: {what}")


def _type_of(schema: dict, slot: dict):
    return None if "ref" in slot else l0._local_type(schema, slot["type"])


def arrow_type(schema: dict, slot: dict) -> pa.DataType:
    """The Arrow storage of a slot's values (§4.4), from `l0.storage`; never a float."""
    spelled = l0.storage(schema, slot)
    simple = {"utf8": pa.utf8(), "int64": pa.int64(), "bool": pa.bool_(), "date32": pa.date32(),
              'timestamp(us,"UTC")': pa.timestamp("us", tz="UTC"), "decimal128(38,0)": _DEC0}
    if spelled in simple:
        return simple[spelled]
    if spelled.startswith("decimal128(38,"):
        return pa.decimal128(38, int(spelled[len("decimal128(38,"):-1]))
    t = _type_of(schema, slot)
    if t["of"] == "Ratio":
        return pa.struct([("numerator", _DEC0), ("denominator", _DEC0)])
    if t["of"] == "Period":
        end = arrow_type(schema, {"type": t["over"]})
        return pa.struct([("from", end), ("to", end)])
    _fail(slot.get("type", "?"), f"storage {spelled} has no Arrow type here")


# ---------------------------------------------------------------------------------------------------------------
# values: payload ↔ Arrow


def _to_column(schema: dict, slot: dict, value):
    """The Arrow value of one known row JSON value (§3.2, §4.4)."""
    if "ref" in slot:
        return l0._reference(schema, slot["ref"], value, "write")
    t = _type_of(schema, slot)
    if t is None:
        return value
    of = t["of"]
    payload = l0._typed(schema, t, slot, value, "write")
    if of == "Integer":
        kind = l0.storage(schema, slot)
        return int(payload) if kind == "int64" else Decimal(payload) if kind.startswith("decimal") else payload
    if of == "Quantity":
        return int(payload) if l0.storage(schema, slot) == "int64" else Decimal(payload)
    if of == "Money":
        return Decimal(payload).scaleb(-int(t.get("scale", "0")))
    if of == "Ratio":
        f = Fraction(payload)
        return {"numerator": Decimal(f.numerator), "denominator": Decimal(f.denominator)}
    if of == "Date":
        return datetime.date.fromisoformat(value)
    if of == "DateTime":
        return datetime.datetime.fromisoformat(value[:-1] + "+00:00")
    if of == "Period":
        over = {"type": t["over"]}
        end_type = l0._local_type(schema, t["over"])
        ends = [int(e) if end_type and l0._number_spelling(end_type) else e
                for e in (payload["from"], payload["to"])]
        return {"from": _to_column(schema, over, ends[0]), "to": _to_column(schema, over, ends[1])}
    return payload  # Text, Enum, Bool


def _decimal_text(f: Fraction) -> str:
    """The shortest exact decimal of `f`, or `n/d` when it has none (§3.2)."""
    if f.denominator == 1:
        return str(f.numerator)
    d = f.denominator
    twos = fives = 0
    while d % 2 == 0:
        d, twos = d // 2, twos + 1
    while d % 5 == 0:
        d, fives = d // 5, fives + 1
    if d != 1:
        return f"{f.numerator}/{f.denominator}"
    places = max(twos, fives)
    digits = str(abs(f.numerator) * 10**places // f.denominator).rjust(places + 1, "0")
    text = (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")
    return ("-" if f < 0 else "") + text


def _from_column(schema: dict, slot: dict, value, where: str):
    """The row JSON value of one Arrow value of a known slot; the inverse of `_to_column`."""
    if value is None:
        _fail(where, "a null value with state 0 (known)")
    if isinstance(value, float):
        _fail(where, f"{value!r} is a float")
    if "ref" in slot:
        ref = slot["ref"]
        if "." not in ref:
            return {"$ref": value}
        prefix, kind = ref.split(".", 1)
        imp = schema["imports"][prefix]
        pins = "".join(f"@{imp[k]}" for k in ("manifest", "dataset") if k in imp)
        return {"$ref": f"{imp['pack']}@{imp['schema']}{pins}:{kind}/{value}"}
    t = _type_of(schema, slot)
    if t is None:
        return value
    of = t["of"]
    if of == "Integer":
        number = int(value)
        return number if l0._number_spelling(t) else str(number)
    if of == "Quantity":
        per_unit = Fraction(t.get("factor", "1")) * 10 ** int(t.get("scale", "0"))
        return f"{_decimal_text(Fraction(int(value)) / per_unit)} {t['unit']}"
    if of == "Money":
        scale = int(t.get("scale", "0"))
        if not isinstance(value, Decimal) or -value.as_tuple().exponent != scale:
            _fail(where, f"{value!r} is not a decimal at scale {scale}")
        return f"{t['currency']} {value}" + (f"/{t['per']}" if "per" in t else "")
    if of == "Ratio":
        n, d = int(value["numerator"]), int(value["denominator"])
        return str(n) if d == 1 else f"{n}/{d}"
    if of == "Date":
        return value.isoformat()
    if of == "DateTime":  # a UTC instant: the column type was checked, and `_records` drops the zone name
        if value.tzinfo is not None and value.utcoffset() != datetime.timedelta(0):
            _fail(where, "a time not in UTC")
        text = value.strftime("%Y-%m-%dT%H:%M:%S")
        if value.microsecond:
            text += ("." + f"{value.microsecond:06d}").rstrip("0")
        return text + "Z"
    if of == "Period":
        over = {"type": t["over"]}
        sep = "..<" if t["range"] == "half_open" else ".."
        a, b = (_from_column(schema, over, value[end], where) for end in ("from", "to"))
        return f"{a}{sep}{b}"
    return value  # Text, Enum, Bool


# ---------------------------------------------------------------------------------------------------------------
# row JSON → Arrow


def _member_key(schema: dict, slot: dict, member) -> bytes:
    payload = l0._known(schema, slot, member, "member")
    return canonical_json(payload if isinstance(payload, str) else canonical_json(payload)).encode("utf-8")


def _key(kind: dict, row: dict) -> list:
    if "versioned" not in kind:
        return [row["$id"]]
    return [row["$id"], canonical_json(row.get("$valid", {})), row.get("$known", "")]


def normal_rows(schema: dict, rows: list) -> list:
    """The rows in hash order (§6.2 step 3, per kind in schema order), members in hash order (§3.3)."""
    out = []
    for name, kind in schema["kinds"].items():
        mine = [r for r in rows if r["$kind"] == name]
        for row in sorted(mine, key=lambda r: canonical_json(_key(kind, r)).encode("utf-8")):
            new = dict(row)
            for slot_name, slot in kind["slots"].items():
                if slot["card"] in ("*", "+") and isinstance(row.get(slot_name), list):
                    new[slot_name] = sorted(row[slot_name], key=lambda m, s=slot: _member_key(schema, s, m))
            out.append(new)
    return out


def _state(value):
    s = l0._state_of(value)
    return s if s and s[0] else None


def _field(name: str, typ: pa.DataType, nullable: bool, meta: dict, ext=None) -> pa.Field:
    md = {"reckon": canonical_json(meta)}
    if ext:
        md["ARROW:extension:name"] = ext[0]
        md["ARROW:extension:metadata"] = canonical_json(ext[1])
    return pa.field(name, typ, nullable=nullable, metadata=md)


def _version_fields(kind: dict) -> list:
    if "versioned" not in kind:
        return []
    fields = [_field("$valid", pa.utf8(), False, {"slot": "$valid", "role": "valid", "type": "Text"})]
    if "known" in kind["versioned"]:
        k = kind["versioned"]["known"]
        typ = pa.date32() if k == "Date" else pa.timestamp("us", tz="UTC")
        fields.append(_field("$known", typ, False, {"slot": "$known", "role": "known", "type": k}))
    return fields


def _version_values(schema: dict, kind: dict, row: dict) -> list:
    if "versioned" not in kind:
        return []
    out = [canonical_json(row.get("$valid", {}))]
    if "known" in kind["versioned"]:
        out.append(_to_column(schema, {"type": kind["versioned"]["known"]}, row["$known"]))
    return out


def _slot_meta(slot_name: str, slot: dict, role: str) -> dict:
    """Field metadata `reckon` (§4.2): slot, role and type, plus `ref` for a reference (whose ids are text)."""
    meta = {"slot": slot_name, "role": role, "type": slot.get("type", "Text")}
    if "ref" in slot:
        meta["ref"] = slot["ref"]
    return meta


def _side_key(d: list, src: bool) -> bytes:
    """The hash key of one side-table row `[kind, id, slot, member, proof|source, valid, known]` (§6.2 step 6): a
    null column is `""`, and a `$src` row adds its source. Rows written in this order are written in hash order."""
    kind, id_, slot, member, last, valid, known = d
    key = [kind, id_, slot, member or "", valid or "", known or ""] + ([last] if src else [])
    return canonical_json(key).encode("utf-8")


def to_arrow(schema: dict, rows: list, pin: dict | None = None) -> dict:
    """One Arrow table per kind, relation and side table (§4.1), with the `reckon` metadata (§4.2).

    `pin` MAY carry `dataset`, `table_hash` (a map table → hash) and `manifest`; an epoch pin needs its hash pin.
    """
    sid = l0.check_schema(schema)
    l0.read_rows(schema, rows)
    rows = normal_rows(schema, rows)
    pin = dict(pin or {})
    hashes_by_table = pin.pop("table_hash", {})
    versioned = any("versioned" in k for k in schema["kinds"].values())

    def meta(table: str, role: str, control: bool) -> dict:
        m = {"reckon": "1.0", "schema": sid, "table": table, "role": role, **pin}
        if control:
            m["plane"] = "control"
        if table in hashes_by_table:
            m["table_hash"] = hashes_by_table[table]
        l0.check_table_metadata(schema, m)
        return {"reckon": canonical_json(m)}

    out = {}
    for name, kind in schema["kinds"].items():
        control = kind.get("plane") == "control"
        mine = [r for r in rows if r["$kind"] == name]
        id_type = kind["id"]["type"]
        fields = [_field("$id", pa.utf8(), False, {"slot": "$id", "role": "id", "type": id_type})]
        fields += _version_fields(kind)
        cols = [[r["$id"] for r in mine]] + [list(c) for c in zip(*(_version_values(schema, kind, r) for r in mine))]
        if not mine:
            cols += [[] for _ in _version_fields(kind)]
        for slot_name, slot in sorted(kind["slots"].items()):  # §4.1: in name order, as the schema id reads them
            if "inverse" in slot:
                continue
            many = slot["card"] in ("*", "+")
            stated = slot["states"] != ["known"]
            if not many:
                ext = l0._expected_extension(schema, slot)
                fields.append(_field(slot_name, arrow_type(schema, slot), stated,
                                     _slot_meta(slot_name, slot, "value"), ext))
                cols.append([None if _state(r[slot_name]) else _to_column(schema, slot, r[slot_name])
                             for r in mine])
            if stated:
                states = [_state(r[slot_name]) for r in mine]
                fields.append(_field(f"{slot_name}$state", pa.int8(), False,
                                     {"slot": slot_name, "role": "state", "type": "Text"}))
                cols.append([STATE_CODE[s[0]] if s else 0 for s in states])
                fields.append(_field(f"{slot_name}$reason", pa.utf8(), False,
                                     {"slot": slot_name, "role": "reason", "type": "Text"}))
                cols.append([s[1] if s else "" for s in states])
            if many:
                rel = f"{name}__{slot_name}"
                rf = [_field("$id", pa.utf8(), False, {"slot": slot_name, "role": "owner", "type": id_type})]
                rf += _version_fields(kind)
                rf.append(_field(slot_name, arrow_type(schema, slot), False, _slot_meta(slot_name, slot, "member"),
                                 l0._expected_extension(schema, slot)))
                data = [[r["$id"], *_version_values(schema, kind, r), _to_column(schema, slot, m)]
                        for r in mine if isinstance(r[slot_name], list) for m in r[slot_name]]
                out[rel] = pa.table([pa.array([d[i] for d in data], f.type) for i, f in enumerate(rf)],
                                    schema=pa.schema(rf, metadata=meta(rel, "relation", control)))
        out[name] = pa.table([pa.array(c, f.type) for c, f in zip(cols, fields)],
                             schema=pa.schema(fields, metadata=meta(name, "kind", control)))

    for table, last in (("$why", "proof"), ("$src", "source")):
        columns = ["kind", "id", "slot", "member", last] + (["valid", "known"] if versioned else [])
        data = []
        for r in rows:
            kind = schema["kinds"][r["$kind"]]
            v = canonical_json(r.get("$valid", {})) if "versioned" in kind else None
            k = r.get("$known")
            if table == "$why":
                for slot_name, proof in r.get("$why", {}).items():
                    if isinstance(proof, dict):
                        data += [[r["$kind"], r["$id"], slot_name, m, u, v, k] for m, u in proof.items()]
                    else:
                        data.append([r["$kind"], r["$id"], slot_name, None, proof, v, k])
            else:
                data += [[r["$kind"], r["$id"], slot_name, None, canonical_json(s), v, k]
                         for slot_name, sources in r.get("$src", {}).items() for s in sources]
        data.sort(key=lambda d, src=table == "$src": _side_key(d, src))  # §4.1: hash order, as §6.2 step 6
        fields = [_field(c, pa.utf8(), c in ("member", "valid", "known"), {"slot": c, "role": "value", "type": "Text"})
                  for c in columns]
        out[table] = pa.table([pa.array([d[i] for d in data], pa.utf8()) for i in range(len(columns))],
                              schema=pa.schema(fields, metadata=meta(table, table[1:], False)))
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------------------------------------------
# Arrow → row JSON


def _check_column(schema: dict, kind_name: str, slot: dict, f: pa.Field, where: str):
    """The storage and, when the field carries it, the extension of one value or member column (§4.4, §4.5)."""
    if pa.types.is_floating(f.type):
        _fail(where, f"{f.type}: floating-point types MUST NOT occur")
    md = f.metadata or {}
    desc = {"name": "x", "storage": str(f.type)}
    expected = l0._expected_extension(schema, slot)
    if b"ARROW:extension:name" in md:
        desc["extension"] = {"name": md[b"ARROW:extension:name"].decode(),
                             "metadata": json.loads(md.get(b"ARROW:extension:metadata", b"{}"))}
    elif expected is not None:
        if b"reckon" in md:  # a writer's field without the extension it MUST carry
            _fail(where, f"the column needs the extension `{expected[0]}`")
        desc["extension"] = {"name": expected[0], "metadata": expected[1]}  # no field metadata (C04)
    probe = {**schema, "kinds": {**schema["kinds"], "_": {"world": "open", "id": {"type": "Text"},
                                                           "slots": {"x": slot}}}}
    try:
        l0.check_field(probe, "_", desc)
    except l0.L0Error as e:
        _fail(where, str(e).split(": ", 1)[1])


def _naive(typ: pa.DataType) -> pa.DataType:
    """The type with every `timestamp(us, "UTC")` as a plain `timestamp(us)`: the same instants, read without a
    time zone database (the column types are checked against the schema first)."""
    if pa.types.is_timestamp(typ) and typ.tz == "UTC":
        return pa.timestamp(typ.unit)
    if pa.types.is_struct(typ):
        return pa.struct([typ.field(i).with_type(_naive(typ.field(i).type)) for i in range(typ.num_fields)])
    return typ


def _records(t: pa.Table) -> list:
    return t.cast(pa.schema([f.with_type(_naive(f.type)) for f in t.schema], metadata=t.schema.metadata)).to_pylist()


def _check_versions(kind: dict, t: pa.Table, name: str):
    for f in _version_fields(kind):
        if t.schema.field(f.name).type != f.type:
            _fail(name, f"`{f.name}` is {t.schema.field(f.name).type}, not {f.type}")


def _table_meta(schema: dict, t: pa.Table, name: str, role: str):
    md = t.schema.metadata or {}
    if b"reckon" not in md:
        _fail(name, "the table has no `reckon` metadata")
    meta = json.loads(md[b"reckon"])
    l0.check_table_metadata(schema, meta)
    if meta["table"] != name or meta["role"] != role:
        _fail(name, f"the metadata names table {meta['table']!r} as {meta['role']!r}")
    for f in t.schema:
        if pa.types.is_floating(f.type):
            _fail(f"{name}.{f.name}", f"{f.type}: floating-point types MUST NOT occur")


def _version_of(schema: dict, kind: dict, rec: dict, where: str) -> dict:
    out = {}
    if "versioned" not in kind:
        return out
    valid = l0.loads(rec["$valid"])
    if valid:
        out["$valid"] = valid
    if "known" in kind["versioned"]:
        out["$known"] = _from_column(schema, {"type": kind["versioned"]["known"]}, rec["$known"], where)
    return out


def from_arrow(schema: dict, tables: dict) -> list:
    """The rows of a dataset read from its Arrow tables (§4), in normal order; then read as row JSON."""
    l0.check_schema(schema)
    rows, by_key = [], {}
    for name, kind in schema["kinds"].items():
        t = tables.get(name)
        if t is None:
            _fail(name, "the kind table is missing")
        _table_meta(schema, t, name, "kind")
        want = ["$id"] + [f.name for f in _version_fields(kind)]
        for slot_name, slot in sorted(kind["slots"].items()):  # the order to_arrow writes (§4.1)
            if "inverse" in slot:
                continue
            if slot["card"] in ("1", "?"):
                want.append(slot_name)
                _check_column(schema, name, slot, t.schema.field(slot_name) if slot_name in t.schema.names
                              else _fail(name, f"column `{slot_name}` is missing"), f"{name}.{slot_name}")
            if slot["states"] != ["known"]:
                want += [f"{slot_name}$state", f"{slot_name}$reason"]
        if t.schema.names != want:
            _fail(name, f"columns {t.schema.names} are not {want}")
        _check_versions(kind, t, name)
        for rec in _records(t):
            where = f"{name}/{rec['$id']}"
            row = {"$kind": name, "$id": rec["$id"], **_version_of(schema, kind, rec, where)}
            for slot_name, slot in kind["slots"].items():
                if "inverse" in slot:
                    continue
                code = rec.get(f"{slot_name}$state", 0)
                if code not in (0, 1, 2, 3):
                    _fail(where, f"`{slot_name}$state` {code} is not a state code")
                state = l0.STATES[code]
                if state != "known":
                    if slot["card"] in ("1", "?") and rec[slot_name] is not None:
                        _fail(where, f"`{slot_name}` has a value with state {code}")
                    row[slot_name] = {STATE_KEY[state]: rec[f"{slot_name}$reason"]}
                elif slot["card"] in ("1", "?"):
                    row[slot_name] = _from_column(schema, slot, rec[slot_name], f"{where}.{slot_name}")
                else:
                    if rec.get(f"{slot_name}$reason", "") != "":
                        _fail(where, f"`{slot_name}$reason` beside state 0")
                    row[slot_name] = []
            rows.append(row)
            by_key[(name, *_key(kind, row))] = row
        for slot_name, slot in kind["slots"].items():
            if slot["card"] not in ("*", "+") or "inverse" in slot:
                continue
            rel = f"{name}__{slot_name}"
            rt = tables.get(rel)
            if rt is None:
                _fail(rel, "the relation table is missing")
            _table_meta(schema, rt, rel, "relation")
            want = ["$id"] + [f.name for f in _version_fields(kind)] + [slot_name]
            if rt.schema.names != want:
                _fail(rel, f"columns {rt.schema.names} are not {want}")
            _check_column(schema, name, slot, rt.schema.field(slot_name), f"{rel}.{slot_name}")
            _check_versions(kind, rt, rel)
            for rec in _records(rt):
                where = f"{rel}/{rec['$id']}"
                owner = by_key.get((name, *_key(kind, {"$id": rec["$id"], **_version_of(schema, kind, rec, where)})))
                if owner is None:
                    _fail(where, "a member of no element")
                if not isinstance(owner[slot_name], list):
                    _fail(where, f"a member beside the state {owner[slot_name]}")
                owner[slot_name].append(_from_column(schema, slot, rec[slot_name], where))
    for table, last in (("$why", "proof"), ("$src", "source")):
        t = tables.get(table)
        if t is None:
            _fail(table, "the side table is missing")
        _table_meta(schema, t, table, table[1:])
        for rec in _records(t):
            kind = schema["kinds"].get(rec["kind"])
            if kind is None:
                _fail(table, f"kind {rec['kind']!r} is not in the schema")
            version = {"$id": rec["id"]}
            if "versioned" in kind:  # side tables keep `$valid` and `$known` as their row JSON text
                valid = l0.loads(rec["valid"] or "{}")
                version.update({"$valid": valid} if valid else {})
                if "known" in kind["versioned"]:
                    version["$known"] = rec["known"]
            row = by_key.get((rec["kind"], *_key(kind, version)))
            if row is None:
                _fail(table, f"{rec['kind']}/{rec['id']} is not a row of the dataset")
            if table == "$why":
                if rec["member"] is None:
                    row.setdefault("$why", {})[rec["slot"]] = rec["proof"]
                else:
                    row.setdefault("$why", {}).setdefault(rec["slot"], {})[rec["member"]] = rec["proof"]
            else:
                row.setdefault("$src", {}).setdefault(rec["slot"], []).append(l0.loads(rec["source"]))
    for row in rows:
        for sources in row.get("$src", {}).values():
            sources.sort(key=canonical_json)
    rows = normal_rows(schema, rows)
    l0.read_rows(schema, rows)
    return rows


# ---------------------------------------------------------------------------------------------------------------
# Parquet


def _parquet(t: pa.Table, sink, store_schema: bool):
    with pq.ParquetWriter(sink, t.schema, store_schema=store_schema, compression="zstd") as w:
        w.write_table(t)
        if not store_schema:  # §4.2: the file metadata carries `reckon` also without `ARROW:schema`
            w.add_key_value_metadata({"reckon": t.schema.metadata[b"reckon"].decode("utf-8")})


def write_parquet(tables: dict, out: Path, *, store_schema: bool = True) -> list:
    """One Parquet file per table, `<table>.parquet`; `store_schema` embeds `ARROW:schema` (§4.2)."""
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, t in tables.items():
        path = out / f"{name}.parquet"
        _parquet(t, path, store_schema)
        paths.append(path)
    return paths


def read_parquet(directory: Path) -> dict:
    """The tables of `write_parquet`, by table name."""
    return {p.stem: pq.read_table(p) for p in sorted(directory.glob("*.parquet"))}


# ---------------------------------------------------------------------------------------------------------------
# One file per table (§4.6)

FORMS = ("arrow", "parquet")


def file_name(table: str, form: str) -> str:
    """The file of one table in one columnar form (§4.6): `table.<name>.arrow` or `table.<name>.parquet`, with `$`
    written `_` (`$why` → `table._why.arrow`)."""
    if form not in FORMS:
        raise ValueError(f"{form}: not a columnar form ({', '.join(FORMS)})")
    return f"table.{table.replace('$', '_')}.{form}"


def table_bytes(t: pa.Table, form: str) -> bytes:
    """One table as the bytes of an Arrow IPC file or a Parquet file (zstd, `ARROW:schema` embedded). Deterministic:
    the same table and the same pinned pyarrow give the same bytes."""
    sink = pa.BufferOutputStream()
    if form == "arrow":
        with pa.ipc.new_file(sink, t.schema) as w:
            w.write_table(t)
    elif form == "parquet":
        _parquet(t, sink, True)
    else:
        raise ValueError(f"{form}: not a columnar form ({', '.join(FORMS)})")
    return sink.getvalue().to_pybytes()


def read_table_bytes(data: bytes, form: str) -> pa.Table:
    """The table in the bytes of `table_bytes`."""
    if form == "arrow":
        return pa.ipc.open_file(pa.BufferReader(data)).read_all()
    if form == "parquet":
        return pq.read_table(pa.BufferReader(data))
    raise ValueError(f"{form}: not a columnar form ({', '.join(FORMS)})")


def to_files(schema: dict, rows: list, pin: dict | None = None) -> dict:
    """Every table of `to_arrow` as one file per table and form, by `file_name`, tables in name order, Arrow before
    Parquet. Raises ColumnarError if two tables would give one file name: the mapping is checked, not assumed."""
    out = {}
    for table, t in to_arrow(schema, rows, pin).items():
        for form in FORMS:
            name = file_name(table, form)
            if name in out:
                _fail(table, f"another table is also written as {name}")
            out[name] = table_bytes(t, form)
    return out


def from_files(schema: dict, files: dict, form: str) -> list:
    """The rows of a dataset read from its files of one form (`to_files`), as `from_arrow` reads them."""
    names = {file_name(table, form): table for table in table_names(schema)}
    missing = sorted(set(names) - set(files))
    if missing:
        _fail(missing[0], "the table's file is missing")
    return from_arrow(schema, {table: read_table_bytes(files[n], form) for n, table in names.items()})


def table_names(schema: dict) -> list:
    """Every table a dataset of `schema` has (§4.1): kind tables, relation tables, `$why` and `$src`."""
    out = ["$why", "$src"]
    for name, kind in schema["kinds"].items():
        out.append(name)
        out += [f"{name}__{s}" for s, slot in kind["slots"].items()
                if slot["card"] in ("*", "+") and "inverse" not in slot]
    return sorted(out)
