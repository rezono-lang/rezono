"""The logical hash against the vectors of docs/reckon-data/l0.md §6.2 and the hash cases of §8."""

import copy
import json
import sys
import unicodedata
from pathlib import Path

import pytest
import yaml

from reckon_data.hash import EMPTY, H, HashError, hash_rows, hashes, schema_id

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "docs" / "reckon-data" / "cases"
FIXTURE = json.loads((CASES / "fixture.schema.json").read_text("utf-8"))
H06 = yaml.safe_load((CASES / "H06.yaml").read_text("utf-8"))


def without_why(rows):
    return [{k: v for k, v in r.items() if k != "$why"} for r in rows]


def test_h01_worked_vector():
    """§6.2 worked vector: schema id, hash rows of `Host`, table and dataset hashes."""
    rows = without_why(H06["input"]["$rows"])
    assert schema_id(FIXTURE) == H06["input"]["$schema"]
    assert hash_rows(FIXTURE, rows)["Host"] == [
        {"$key": ["host-a"], "memory_need": "429496729600",
         "owner": {"$reason": "not_assigned", "$state": "unknown"}},
        {"$key": ["host-b"], "memory_need": {"$reason": "", "$state": "unknown"},
         "owner": {"$reason": "", "$state": "not_applicable"}},
    ]
    h = hashes(FIXTURE, rows)
    assert h["tables"] == {
        "Host": "5f01b7b2c916915632d60dd32a77276760056b82ef7fe7590881bbd612e8850e",
        "Host__tags": "3f22d0ca85009e43891ca5f73f45b1577041da335db34ac7e1f17799eac013b4",
        "Team": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    }
    assert h["dataset"] == "d-25b682230808ec1686d53ff86a527112165de8249014a5b099b1b5f6b234a082"


def test_h02_order_is_not_significant():
    """Rows and members shuffled: the same dataset hash."""
    rows = without_why(H06["input"]["$rows"])
    shuffled = copy.deepcopy(rows[::-1])
    shuffled[1]["tags"].reverse()
    assert hashes(FIXTURE, shuffled)["dataset"] == hashes(FIXTURE, rows)["dataset"]


def counted(value):
    schema = {"reckon": "1.0", "pack": "c", "base": "https://c.example/", "kinds": {"Box": {
        "world": "closed", "id": {"type": "Text"},
        "slots": {"count": {"type": "Count", "card": "1", "states": ["known"]}}}},
        "types": {"Count": {"of": "Integer", "min": "0", "max": "100"}}}
    return hashes(schema, [{"$kind": "Box", "$id": "b", "count": value}])


def test_h03_integer_number_and_text_hash_alike():
    """W3: `count: 42` and `count: "42"` give one hash."""
    assert counted(42) == counted("42")


def ids(*names):
    schema = {"reckon": "1.0", "pack": "t", "base": "https://t.example/",
              "kinds": {"Tag": {"world": "open", "id": {"type": "Text"}, "slots": {}}}}
    return schema, [{"$kind": "Tag", "$id": n} for n in names]


def test_h04_no_unicode_normalisation():
    composed = unicodedata.normalize("NFC", "café")
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed
    assert hashes(*ids(composed))["dataset"] != hashes(*ids(decomposed))["dataset"]


def test_h05_hash_order_is_by_canonical_key_bytes():
    """`["a b"]` < `["a"]` < `["a-b"]`: the closing quote sorts after a space, before a hyphen."""
    rows = hash_rows(*ids("a", "a-b", "a b"))["Tag"]
    assert [r["$key"] for r in rows] == [["a b"], ["a"], ["a-b"]]


def test_h06_annotation_hash():
    expect = H06["expect"]
    h = hashes(FIXTURE, H06["input"]["$rows"])
    assert h["dataset"] == expect["dataset_hash"]
    assert h["side_tables"] == expect["side_tables"]
    assert h["annotation"] == expect["annotation_hash"]
    bare = hashes(FIXTURE, without_why(H06["input"]["$rows"]))
    assert bare["dataset"] == expect["without_why"]["dataset_hash"]
    assert bare["annotation"] == expect["without_why"]["annotation_hash"]


sys.path.insert(0, str(ROOT / "canon" / "tests"))
from decode import decode  # noqa: E402  the typed-leaf decoder of the canon vectors

VECTORS = json.loads((ROOT / "contracts" / "fixtures" / "canon" / "vectors.json").read_text("utf-8"))


@pytest.mark.parametrize("v", [v for v in VECTORS["valid"] if v.get("only", "python") == "python"],
                         ids=lambda v: v["name"])
def test_h07_canon_vectors(v):
    """The hash here is Rede's one canonical hash: every canon vector hashes as in the file."""
    assert H(decode(v["input"])) == v["sha256"]


PLAN = {"reckon": "1.0", "pack": "p", "base": "https://p.example/", "kinds": {"Plan": {
    "world": "closed", "id": {"type": "Text"}, "versioned": {"at": "Date", "known": "Date"},
    "slots": {"hourly_price": {"type": "Euro", "card": "1", "states": ["known"]},
              "zones": {"type": "Text", "card": "*", "states": ["known"]}}}},
    "types": {"Euro": {"of": "Money", "currency": "EUR", "scale": "4", "per": "h"}}}


def plan(valid, known, price, zones=()):
    return {"$kind": "Plan", "$id": "scw-pro2-m", "$valid": {"at": valid}, "$known": known,
            "hourly_price": price, "zones": list(zones)}


def test_v02_versions_are_keyed_by_valid_and_known():
    rows = [plan("2026-01-01..", "2025-09-16", "€ 0.1610/h", ["nl-ams"]),
            plan("2025-01-01..<2026-01-01", "2024-09-17", "€ 0.1740/h")]
    t = hash_rows(PLAN, rows)
    assert [r["$key"] for r in t["Plan"]] == [
        ["scw-pro2-m", '{"at":"2025-01-01..<2026-01-01"}', "2024-09-17"],
        ["scw-pro2-m", '{"at":"2026-01-01.."}', "2025-09-16"],
    ]
    assert [r["hourly_price"] for r in t["Plan"]] == ["1740", "1610"]
    assert t["Plan__zones"] == [{"$key": ["scw-pro2-m", '{"at":"2026-01-01.."}', "2025-09-16", "nl-ams"]}]


def test_versioned_side_tables_carry_valid_and_known():
    row = plan("2026-01-01..", "2025-09-16", "€ 0.1610/h", ["nl-ams"])
    row["$why"] = {"zones": {"nl-ams": "rede:w/1"}}
    row["$src"] = {"hourly_price": [{"uri": "https://example.org/prices"}]}
    t = hash_rows(PLAN, [row])
    v, k = '{"at":"2026-01-01.."}', "2025-09-16"
    assert t["$why"] == [{"$key": ["Plan", "scw-pro2-m", "zones", "nl-ams", v, k], "proof": "rede:w/1"}]
    assert t["$src"] == [{"$key": ["Plan", "scw-pro2-m", "hourly_price", "", v, k,
                                   '{"uri":"https://example.org/prices"}']}]


def test_empty_tables_are_listed():
    h = hashes(FIXTURE, [])
    assert h["tables"] == {"Host": EMPTY, "Host__tags": EMPTY, "Team": EMPTY}
    assert h["side_tables"] == {"$why": EMPTY, "$src": EMPTY}


def test_two_rows_with_one_key_are_refused():
    with pytest.raises(HashError, match="two hash rows"):
        hash_rows(*ids("a", "a"))


def test_duplicate_members_are_refused():
    rows = without_why(H06["input"]["$rows"])
    rows[0]["tags"] = ["gpu", "gpu"]
    with pytest.raises(HashError, match="two hash rows"):
        hashes(FIXTURE, rows)


def test_a_stored_integer_must_be_whole():
    schema = copy.deepcopy(FIXTURE)
    schema["types"]["GiB"]["factor"] = "1/3"
    rows = without_why(H06["input"]["$rows"])
    with pytest.raises(HashError, match="not whole"):
        hashes(schema, rows)


def test_null_never_reaches_the_hash():
    rows = without_why(H06["input"]["$rows"])
    rows[0]["memory_need"] = None
    with pytest.raises(HashError, match="null"):
        hashes(FIXTURE, rows)


def test_an_absent_slot_is_refused():
    rows = without_why(H06["input"]["$rows"])
    del rows[1]["owner"]
    with pytest.raises(HashError, match="absent"):
        hashes(FIXTURE, rows)


def test_a_reference_to_another_pack_hashes_its_target_id():
    schema = copy.deepcopy(FIXTURE)
    schema["kinds"]["Host"]["slots"]["owner"]["ref"] = "org.Team"
    rows = without_why(H06["input"]["$rows"])
    local = hashes(FIXTURE, [dict(rows[0], owner={"$ref": "team-x/1"})])
    pinned = "org@s-" + "a" * 64 + "@m-12@d-" + "b" * 64 + ":Team/team-x/1"
    other = hashes(schema, [dict(rows[0], owner={"$ref": pinned})])
    assert other["tables"]["Host"] == local["tables"]["Host"]


def members(type_, values):
    schema = {"reckon": "1.0", "pack": "t", "base": "https://t.example/",
              "kinds": {"Box": {"world": "closed", "id": {"type": "Text"},
                                "slots": {"n": {"type": type_, "card": "*"}}}},
              "types": {"Digit": {"of": "Integer", "min": "0", "max": "9"}}}
    return schema, [{"$kind": "Box", "$id": "a", "n": values}]


def test_a_bounded_integer_member_is_its_normal_text():
    """§6.2 step 2: `m` is the payload's text, so `[4]` keys as `"4"`, not as `CJ(4)`."""
    rows = hash_rows(*members("Digit", [4]))
    assert rows["Box__n"] == [{"$key": ["a", "4"]}]


def test_a_bounded_and_an_unbounded_integer_member_hash_alike():
    """LD2 spells a bounded Integer as a number and any other as a string; the relation table is one."""
    bounded = hashes(*members("Digit", [4]))["tables"]["Box__n"]
    unbounded = hashes(*members("Integer", ["4"]))["tables"]["Box__n"]
    assert bounded == unbounded


def test_a_float_in_a_key_or_member_is_a_hash_error():
    with pytest.raises(HashError):
        hash_rows(*members("Digit", [1.5]))
    schema, rows = ids("a")
    rows[0]["$id"] = 1.5
    with pytest.raises(HashError):
        hash_rows(schema, rows)


def test_a_subkind_is_a_kind_table_of_its_own_and_the_hash_rule_is_the_same():
    """RV-K26 (§2.1 `parent`, §4.1): an element of a subkind is one hash row, in the subkind's table, with every
    slot; its sets are the subkind's relation tables. `parent` is in the schema id and nowhere else: a verifier
    that does not know the member gets the same table hashes."""
    from reckon_data.tests.test_l0 import TREE, TREE_ROWS

    rows = hash_rows(TREE, TREE_ROWS)
    assert rows["Host"] == [{"$key": ["host-a"], "memory_need": "429496729600", "owner": "ops"}]
    assert rows["Server"] == [{"$key": ["srv-1"], "memory_need": "68719476736", "rack": "r1",
                               "owner": {"$reason": "", "$state": "not_applicable"}}]
    assert rows["Host__tags"] == [{"$key": ["host-a", "lab"]}] and rows["Server__tags"] == [{"$key": ["srv-1", "gpu"]}]
    assert rows["Team__runs"] == [{"$key": ["ops", "host-a"]}, {"$key": ["ops", "srv-1"]}]
    plain = copy.deepcopy(TREE)
    del plain["kinds"]["Server"]["parent"]
    assert schema_id(plain) != schema_id(TREE)
    assert hashes(plain, TREE_ROWS)["tables"] == hashes(TREE, TREE_ROWS)["tables"]
