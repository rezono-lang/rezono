"""The columnar form (l0.md §4): row JSON ↔ Arrow ↔ Parquet, cases T01, T02, T04, C01–C04, A04, P01, P03, H02."""

import copy
import json

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from rede_canon import canonical_json
from test_l0 import FILES, FIXTURE, R01, THING, TREE, TREE_ROWS, TYPES, merge, schema_of

from reckon_data import arrow, l0
from reckon_data.hash import hashes


def round_trip(schema, rows, tmp_path, **parquet):
    tables = arrow.to_arrow(schema, rows)
    arrow.write_parquet(tables, tmp_path, **parquet)
    return arrow.from_arrow(schema, arrow.read_parquet(tmp_path))


def same(a, b):
    return [canonical_json(r) for r in a] == [canonical_json(r) for r in b]


def test_t01_r01_to_arrow_to_parquet_to_row_json(tmp_path):
    back = round_trip(FIXTURE, R01, tmp_path)
    assert same(back, arrow.normal_rows(FIXTURE, R01))
    assert hashes(FIXTURE, back) == hashes(FIXTURE, R01)


def test_the_tables_of_r01(tmp_path):
    tables = arrow.to_arrow(FIXTURE, R01, {"dataset": hashes(FIXTURE, R01)["dataset"], "manifest": "m-12"})
    assert list(tables) == ["$src", "$why", "Host", "Host__tags", "Team"]
    host = tables["Host"]
    assert host.schema.names == ["$id", "memory_need", "memory_need$state", "memory_need$reason", "owner",
                                 "owner$state", "owner$reason"]
    assert host.column("memory_need").to_pylist() == [429496729600, None]
    assert host.column("memory_need$state").to_pylist() == [0, 2]
    assert host.column("owner$state").to_pylist() == [2, 1]
    assert host.column("owner$reason").to_pylist() == ["not_assigned", ""]
    assert tables["Host__tags"].to_pylist() == [{"$id": "host-a", "tags": "gpu"}, {"$id": "host-a", "tags": "lab"}]
    meta = json.loads(host.schema.metadata[b"reckon"])
    assert meta == {"reckon": "1.0", "schema": l0.schema_id(FIXTURE), "table": "Host", "role": "kind",
                    "dataset": hashes(FIXTURE, R01)["dataset"], "manifest": "m-12"}
    f = host.schema.field("memory_need")
    assert f.metadata[b"ARROW:extension:name"] == b"reckon.quantity"
    assert json.loads(f.metadata[b"ARROW:extension:metadata"]) == {
        "type": "GiB", "unit": "GiB", "storage_unit": "B", "factor": "1073741824", "scale": "0"}
    assert tables["$why"].to_pylist() == [{"kind": "Host", "id": "host-a", "slot": "memory_need", "member": None,
                                           "proof": "rede:w/91c2"}]


# T02: every type × every state.
ALL = copy.deepcopy(TYPES)
for slot in ALL["kinds"]["Thing"]["slots"].values():
    slot["states"] = list(l0.STATES)
ALL = merge(ALL, {
    "types": {"Span": {"of": "Period", "over": "Count", "range": "closed"},
              "Count": {"of": "Integer", "min": "0", "max": "100"},
              "Mass": {"of": "Quantity", "dimension": "mass", "unit": "kg", "storage_unit": "g", "factor": "1000",
                       "scale": "0", "min": "0", "max": "1000"}},
    "kinds": {"Thing": {"slots": {
        "span": {"card": "?", "type": "Span", "states": ["known", "not_applicable"]},
        "count": {"card": "1", "type": "Count", "states": ["known"]},
        "mass": {"card": "1", "type": "Mass", "states": ["known", "unknown"]},
        "labels": {"card": "*", "type": "Text", "states": ["known", "unknown"]},
        "day": {"card": "1", "type": "Date", "states": ["known"]},
    }},
        "Plan": {"world": "closed", "id": {"type": "Text"}, "versioned": {"at": "Date", "known": "Date"},
                 "slots": {"owner": {"card": "?", "ref": "Team", "states": ["known", "not_applicable"]},
                           "regions": {"card": "*", "type": "Text", "states": ["known"]}}}},
})
KNOWN = dict(THING, price="EUR 12.30", rate="EUR 0.1740/h", span="1..5", count=7, mass="0.5 kg",
             labels=["b", "a b", "a"], day="2026-11-11",
             **{"$why": {"labels": {"a": "rede:w/1"}, "count": "rede:w/2"},
                "$src": {"$id": [{"kind": "pack", "name": "facts/things.yaml", "position": "t"}],
                         "price": [{"kind": "pack", "name": "facts/prices.yaml", "position": "t"},
                                   {"kind": "tool", "name": "pricer", "position": "2026-11-09"}]}})


def stated(i, state, reason):
    row = {"$kind": "Thing", "$id": f"s{i}"}
    for name, slot in ALL["kinds"]["Thing"]["slots"].items():
        row[name] = {arrow.STATE_KEY[state]: reason} if state in slot["states"] else KNOWN[name]
    return row


ROWS_ALL = [KNOWN] + [stated(i, s, r) for i, (s, r) in enumerate(
    [("not_applicable", ""), ("unknown", "added_later"), ("invalid", "versions_overlap")])] + [
    {"$kind": "Plan", "$id": "p", "$valid": {"at": "2025-01-01..<2026-01-01"}, "$known": "2024-09-17",
     "owner": {"$ref": "team-a"}, "regions": ["eu"], "$why": {"owner": "rede:w/3"}},
    {"$kind": "Plan", "$id": "p", "$known": "2025-09-16", "owner": {"$na": ""}, "regions": []},
    {"$kind": "Team", "$id": "team-a"}, {"$kind": "Host", "$id": "h", "memory_need": "0.5 GiB",
                                          "owner": {"$ref": "team-a"}, "tags": []}]


def test_t02_every_type_and_every_state_round_trips(tmp_path):
    l0.check_schema(ALL)
    back = round_trip(ALL, ROWS_ALL, tmp_path)
    assert same(back, arrow.normal_rows(ALL, ROWS_ALL))
    assert hashes(ALL, back) == hashes(ALL, ROWS_ALL)


def test_a_money_symbol_reads_but_is_written_with_its_code(tmp_path):
    """Q18: the schema names no symbol, so `€ 12.30` comes back as `EUR 12.30`, with the same payload and hash."""
    rows = [dict(KNOWN, price="€ 12.30")]
    back = round_trip(ALL, rows, tmp_path)
    assert back[0]["price"] == "EUR 12.30"
    assert hashes(ALL, back)["dataset"] == hashes(ALL, rows)["dataset"]


def table_with(tables, name, column, array):
    t = tables[name]
    i = t.schema.get_field_index(column)
    return {**tables, name: t.set_column(i, t.schema.field(column).with_type(array.type), array)}


def test_c01_a_float_column_is_rejected():
    tables = arrow.to_arrow(FIXTURE, R01)
    bad = table_with(tables, "Host", "memory_need", pa.array([429496729600.0, None], pa.float64()))
    with pytest.raises(l0.L0Error, match="floating-point"):
        arrow.from_arrow(FIXTURE, bad)


def test_c02_a_null_with_state_known_is_rejected():
    tables = arrow.to_arrow(FIXTURE, R01)
    bad = table_with(tables, "Host", "memory_need$state", pa.array([0, 0], pa.int8()))
    with pytest.raises(l0.L0Error, match="null value with state 0"):
        arrow.from_arrow(FIXTURE, bad)
    bad = table_with(tables, "Host", "memory_need$state", pa.array([2, 2], pa.int8()))
    with pytest.raises(l0.L0Error, match="a value with state 2"):
        arrow.from_arrow(FIXTURE, bad)


def test_c03_a_decimal_of_another_scale_is_rejected():
    schema = schema_of(FILES["A03"])
    rows = [dict(r, price="EUR 12.30") for r in R01]
    tables = arrow.to_arrow(schema, rows)
    f = tables["Host"].schema.field("price")
    bad = {**tables, "Host": tables["Host"].set_column(
        tables["Host"].schema.get_field_index("price"), f.with_type(pa.decimal128(18, 4)),
        pa.array([v * 1 for v in tables["Host"].column("price").to_pylist()], pa.decimal128(18, 4)))}
    with pytest.raises(l0.L0Error, match="storage scale 4 differs from the schema's scale 2"):
        arrow.from_arrow(schema, bad)


def test_c04_parquet_without_arrow_schema_reads_by_name(tmp_path):
    back = round_trip(FIXTURE, R01, tmp_path, store_schema=False)
    assert pq.read_schema(tmp_path / "Host.parquet").field("memory_need").metadata is None
    assert same(back, arrow.normal_rows(FIXTURE, R01))


def test_a04_t04_duckdb_reads_the_storage_values_as_written(tmp_path):
    arrow.write_parquet(arrow.to_arrow(ALL, ROWS_ALL), tmp_path)
    host = duckdb.sql(f"select \"$id\", memory_need from '{(tmp_path / 'Host.parquet').as_posix()}'").fetchall()
    assert host == [("h", 536870912)]
    thing = duckdb.sql(f"select price, mass, epoch_us(seen) from '{(tmp_path / 'Thing.parquet').as_posix()}' "
                       "where \"$id\" = 't'").fetchall()[0]
    assert str(thing[0]) == "12.30" and thing[1] == 500 and thing[2] == 1794210000500000
    described = duckdb.sql(f"describe select price from '{(tmp_path / 'Thing.parquet').as_posix()}'").fetchall()
    assert described[0][1] == "DECIMAL(38,2)"


def test_h02_dictionary_encoded_parquet_reads_the_same(tmp_path):
    arrow.write_parquet(arrow.to_arrow(FIXTURE, R01), tmp_path)
    tables = {p.stem: pq.read_table(p, read_dictionary=["$id", "tags"] if p.stem == "Host__tags" else ["$id"])
              for p in tmp_path.glob("*.parquet")}
    assert pa.types.is_dictionary(tables["Host"].schema.field("$id").type)
    assert hashes(FIXTURE, arrow.from_arrow(FIXTURE, tables)) == hashes(FIXTURE, R01)


@pytest.mark.xfail(strict=True, reason="conformance case P01 was held back by the split filter")
def test_p01_the_pin_survives_arrow_and_parquet(tmp_path):
    case = FILES["P01"]
    schema = schema_of(case)
    rows = [case["input"]]
    tables = arrow.to_arrow(schema, rows)
    md = tables["Host"].schema.field("zone").metadata
    assert json.loads(md[b"ARROW:extension:metadata"]) == case["expect"]["arrow_ref_metadata"]
    assert tables["Host"].column("zone").to_pylist() == ["dmz"]
    assert round_trip(schema, rows, tmp_path) == arrow.normal_rows(schema, rows)


def test_p03_an_epoch_pin_needs_its_hash_pin():
    with pytest.raises(l0.L0Error, match="`manifest` without `dataset`"):
        arrow.to_arrow(FIXTURE, R01, {"manifest": "m-12"})


def test_a_writer_writes_only_valid_rows():
    with pytest.raises(l0.L0Error, match="not the shortest exact decimal"):
        arrow.to_arrow(FIXTURE, [dict(R01[0], memory_need="400.0 GiB")])


def test_metadata_of_another_schema_is_rejected():
    tables = arrow.to_arrow(FIXTURE, R01)
    other = merge(FIXTURE, {"base": "https://rezono.example/other/"})
    with pytest.raises(l0.L0Error, match="`schema` is not the id"):
        arrow.from_arrow(other, tables)


def test_a_member_beside_a_state_is_rejected():
    rows = [dict(KNOWN, labels={"$unknown": ""})]
    tables = arrow.to_arrow(ALL, rows)
    rel = tables["Thing__labels"]
    extra = pa.table({"$id": ["t"], "labels": ["x"]}, schema=rel.schema)
    with pytest.raises(l0.L0Error, match="a member beside the state"):
        arrow.from_arrow(ALL, {**tables, "Thing__labels": pa.concat_tables([rel, extra])})


def test_control_tables_say_plane_control():
    schema = schema_of(FILES["G01"])
    rows = FILES["G04"]["input"][0]
    tables = arrow.to_arrow(schema, rows)
    assert json.loads(tables["ZoneRule"].schema.metadata[b"reckon"])["plane"] == "control"
    assert "plane" not in json.loads(tables["Host"].schema.metadata[b"reckon"])
    assert same(arrow.from_arrow(schema, tables), arrow.normal_rows(schema, rows))


def test_no_float_type_occurs_anywhere():
    for t in arrow.to_arrow(ALL, ROWS_ALL).values():
        for f in t.schema:
            types = [f.type] + [f.type.field(i).type for i in range(f.type.num_fields)]
            assert not any(pa.types.is_floating(x) for x in types), f


# §4.6: one file per table and form, by the rule a reader finds it by; side tables in the fixed order of §4.1.
SOURCE_A = {"kind": "pack", "name": "facts/a.yaml", "position": "a"}
SOURCE_B = {"kind": "pack", "name": "facts/b.yaml", "position": "b"}
ANNOTATED = [
    {**R01[0], "$why": {"memory_need": "rede:w/91c2", "tags": {"lab": "rede:w/02", "gpu": "rede:w/01"}},
     "$src": {"memory_need": [SOURCE_A, SOURCE_B], "$id": [SOURCE_A]}},
    {**R01[1], "$why": {"$id": "rede:w/03"}},
]


def test_one_file_per_table_and_form():
    pin = {"dataset": hashes(FIXTURE, ANNOTATED)["dataset"], "manifest": "m-12"}
    files = arrow.to_files(FIXTURE, ANNOTATED, pin)
    assert list(files) == [f"table.{t}.{f}" for t in ("_src", "_why", "Host", "Host__tags", "Team")
                           for f in ("arrow", "parquet")]
    for form in arrow.FORMS:
        back = arrow.from_files(FIXTURE, {n: b for n, b in files.items() if n.endswith(form)}, form)
        assert same(back, arrow.normal_rows(FIXTURE, ANNOTATED))
        assert hashes(FIXTURE, back) == hashes(FIXTURE, ANNOTATED)
    assert arrow.to_files(FIXTURE, ANNOTATED, pin) == files  # the same rows, the same bytes


def test_the_side_tables_are_written_in_hash_order():
    shuffled = [
        {**ANNOTATED[1]},
        {**ANNOTATED[0], "$why": dict(reversed([*ANNOTATED[0]["$why"].items()])),
         "$src": {"$id": [SOURCE_A], "memory_need": [SOURCE_A, SOURCE_B]}},
    ]
    shuffled[1]["$why"]["tags"] = dict(reversed([*shuffled[1]["$why"]["tags"].items()]))
    assert arrow.to_files(FIXTURE, shuffled) == arrow.to_files(FIXTURE, ANNOTATED)
    why = arrow.to_arrow(FIXTURE, ANNOTATED)["$why"].to_pylist()
    assert [(r["id"], r["slot"], r["member"]) for r in why] == [
        ("host-a", "memory_need", None), ("host-a", "tags", "gpu"), ("host-a", "tags", "lab"),
        ("host-b", "$id", None)]
    src = arrow.to_arrow(FIXTURE, ANNOTATED)["$src"].to_pylist()
    assert [(r["slot"], json.loads(r["source"])["position"]) for r in src] == [
        ("$id", "a"), ("memory_need", "a"), ("memory_need", "b")]


def test_the_file_names_follow_the_rule():
    assert arrow.file_name("$why", "arrow") == "table._why.arrow"
    assert arrow.file_name("Host__tags", "parquet") == "table.Host__tags.parquet"
    with pytest.raises(ValueError):
        arrow.file_name("Host", "csv")


def test_two_tables_with_one_file_name_are_refused(monkeypatch):
    monkeypatch.setattr(arrow, "file_name", lambda table, form: f"table.same.{form}")
    with pytest.raises(arrow.ColumnarError, match="also written as table.same.arrow"):
        arrow.to_files(FIXTURE, R01)


def test_a_missing_file_is_refused():
    files = {n: b for n, b in arrow.to_files(FIXTURE, R01).items() if n.endswith(".arrow") and "Team" not in n}
    with pytest.raises(arrow.ColumnarError, match="table.Team.arrow"):
        arrow.from_files(FIXTURE, files, "arrow")


def test_a_subkind_is_a_table_of_its_own_with_the_columns_it_restates(tmp_path):
    """RV-K26 (§4.1): an element of a subkind is one row of the subkind's table; a reference to the parent kind
    holds its id as any other, so the tables read back to the same rows and hashes."""
    tables = arrow.to_arrow(TREE, TREE_ROWS)
    assert list(tables) == ["$src", "$why", "Host", "Host__tags", "Server", "Server__tags", "Team", "Team__runs"]
    assert tables["Host"].column("$id").to_pylist() == ["host-a"]
    assert tables["Server"].schema.names == [*tables["Host"].schema.names, "rack"]
    assert tables["Server"].to_pylist() == [{
        "$id": "srv-1", "memory_need": 68719476736, "memory_need$state": 0, "memory_need$reason": "", "owner": None,
        "owner$state": 1, "owner$reason": "", "rack": "r1"}]
    runs = tables["Team__runs"].schema.field("runs")
    assert json.loads(runs.metadata[b"ARROW:extension:metadata"]) == {"kind": "Host"}
    assert tables["Team__runs"].column("runs").to_pylist() == ["host-a", "srv-1"]
    back = round_trip(TREE, TREE_ROWS, tmp_path)
    assert same(back, arrow.normal_rows(TREE, TREE_ROWS))
    assert hashes(TREE, back) == hashes(TREE, TREE_ROWS)


def test_an_element_in_the_table_of_a_subkind_and_of_its_parent_is_rejected():
    tables = arrow.to_arrow(TREE, TREE_ROWS)
    twice = arrow.to_arrow(TREE, [dict(TREE_ROWS[0], **{"$id": "srv-1"}), TREE_ROWS[2]])
    with pytest.raises(l0.L0Error, match="written once, at its most specific kind"):
        arrow.from_arrow(TREE, {**tables, "Host": twice["Host"], "Host__tags": twice["Host__tags"]})
