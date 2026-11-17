"""The epoch statement of one role (rezono_publication.statement; docs/ring2/signing.md).

On the collection of l0.md §3.1 (case R01 with the fixture schema): the row tree against the RFC 9162 test
vectors (the oracle of signing.md, "How it is checked"), the statement's bytes, and the reader's check: a changed
byte in any object, the statement or the index is refused and named. The acceptance on a published pack, with
the two-world test of O8, is the pack's own (examples/subsidy/test_subsidy_forms.py).
"""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from rezono_publication import l0
from rezono_publication import statement as st
from rezono_publication.hash import EMPTY, hashes

CASES = Path(__file__).resolve().parents[2] / "docs" / "publication" / "cases"
SCHEMA = json.loads((CASES / "fixture.schema.json").read_text("utf-8"))
ROWS = yaml.safe_load((CASES / "R01.yaml").read_text("utf-8"))["input"]["$rows"]

# RFC 9162 §2.1.1 test vectors, as RFC 6962's reference implementation (certificate-transparency) publishes them:
# the leaf inputs and the tree head after each of the first eight leaves.
LEAVES = [bytes.fromhex(x) for x in ("", "00", "10", "2021", "3031", "40414243", "5051525354555657",
                                     "606162636465666768696a6b6c6d6e6f")]
HEADS = [
    "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125",
    "aeb6bcfe274b70a14fb067a5e5578264db0fa9b51af5e0ba159158f329e06e77",
    "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    "4e3bbb1f7b478dcfe71fb631631519a3bca12c9aefca1612bfce4c13a86264d4",
    "76e67dadbcdf1e10e1b74ddc608abd2f98dfb16fbce75277b5232a127f2087ef",
    "ddb89be403809e325750d3d263cd78929c2942b7942a34b77e122c9594a74c8c",
    "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328",
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.mark.parametrize("n", range(1, 9))
def test_the_row_tree_is_rfc_9162_s_merkle_tree_hash(n):
    assert st.tree_root(LEAVES[:n]) == HEADS[n - 1]


def test_an_empty_table_s_root_is_the_hash_of_nothing():
    assert st.tree_root([]) == hashlib.sha256(b"").hexdigest()
    assert st.tree_root([]) != EMPTY  # the tree of no rows is not the table hash of no rows; both are listed


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "statement.yaml"
FIXTURE = ROOT / "contracts" / "fixtures" / "statement" / "EpochStatement" / "valid" / "r01-guest.yaml"


def published() -> tuple[bytes, dict, dict[str, bytes]]:
    """A role's form of R01 as the publisher lays it out: the objects, the statement, the index naming both. The
    manifest's knowledge time has an offset, as `git log --format=%cI` writes it on the publish path, and the role
    reads a slot relation (`kind__slot`)."""
    rows = l0.read_collection(SCHEMA, {"$schema": l0.check_schema(SCHEMA), "$rows": ROWS})
    h = hashes(SCHEMA, rows)
    objects = {
        "schema.json": json.dumps(SCHEMA, sort_keys=True, separators=(",", ":")).encode(),
        "rows.json": json.dumps({"$schema": h["schema"], "$rows": ROWS}, sort_keys=True).encode(),
        "hashes.json": json.dumps(h, sort_keys=True).encode(),
    }
    index = {
        "pack": "toy", "role": "guest", "schema": h["schema"], "dataset": h["dataset"],
        "manifest": {"id": "m-3", "epoch": 3, "knowledge_time": "2026-01-01T01:00:00+01:00",
                     "definition_sha256": "a" * 64,
                     "compiled": [{"file": "bundle/schema-bundle.json", "sha256": "b" * 64}], "role": "guest"},
        "sources": [{"relation": "host", "sha256": "c" * 64}, {"relation": "host__tags", "sha256": "e" * 64}],
        "objects": [{"name": n, "sha256": sha(b)} for n, b in objects.items()],
    }
    data = st.dumps(st.make(index, objects, SCHEMA, rows))
    index["objects"].append({"name": st.NAME, "sha256": sha(data)})
    return data, index, objects


def test_a_statement_says_what_its_files_say():
    data, index, objects = published()
    assert st.verify(data, index, objects) == []
    s = json.loads(data)
    assert s["_type"] == st.STATEMENT_TYPE and s["predicateType"] == st.PREDICATE_TYPE
    assert [x["name"] for x in s["subject"]] == sorted(objects)
    p = s["predicate"]
    assert (p["manifest"], p["epoch"], p["role"]) == ("m-3", "3", "guest")  # the epoch as text
    assert p["dataset"] == index["dataset"] and p["annotation"] == json.loads(objects["hashes.json"])["annotation"]
    assert set(p["roots"]) == {"Host", "Host__tags", "Team", "$why", "$src"}  # every table, side tables too
    assert p["roots"]["Team"] == st.tree_root([])


def test_the_same_form_gives_the_same_bytes_and_the_bytes_are_rfc_8785():
    a, _, _ = published()
    b, _, _ = published()
    assert a == b
    assert a == json.dumps(json.loads(a), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def test_the_statement_holds_no_number_and_no_pack_hash():
    data, _, _ = published()

    def values(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from values(x)
        elif isinstance(v, list):
            for x in v:
                yield from values(x)
        else:
            yield v

    assert all(isinstance(v, str) for v in values(json.loads(data)))
    assert b"pack_sha256" not in data


def changed(b: bytes, old: bytes, new: bytes) -> bytes:
    assert old in b
    return b.replace(old, new, 1)


@pytest.mark.parametrize("what, change, named", [
    ("a row", lambda d, i, o: (d, i, {**o, "rows.json": changed(o["rows.json"], b"host-b", b"host-c")}), "rows.json"),
    ("the schema", lambda d, i, o: (d, i, {**o, "schema.json": changed(o["schema.json"], b"Team", b"Teem")}),
     "schema.json"),
    ("the hashes", lambda d, i, o: (d, i, {**o, "hashes.json": o["hashes.json"] + b" "}), "hashes.json"),
    ("a root", lambda d, i, o: (changed(d, b'"Team":"e3b0', b'"Team":"e3b1'), i, o), "roots"),
    ("the dataset", lambda d, i, o: (d, {**i, "dataset": "d-" + "0" * 64}, o), "dataset"),
    ("the manifest", lambda d, i, o: (d, {**i, "manifest": {**i["manifest"], "knowledge_time": "2026-01-02T00:00:00Z"}},
                                      o), "knowledge_time"),
    ("a snapshot", lambda d, i, o: (d, {**i, "sources": [{"relation": "host", "sha256": "d" * 64}]}, o), "snapshots"),
    ("an object more", lambda d, i, o: (d, {**i, "objects": [*i["objects"], {"name": "x.ttl", "sha256": "e" * 64}]},
                                        o), "subjects"),
    ("the index's statement hash", lambda d, i, o: (d, {**i, "objects": [
        x if x["name"] != st.NAME else {**x, "sha256": "f" * 64} for x in i["objects"]]}, o), st.NAME),
    ("not canonical", lambda d, i, o: (d + b"\n", i, o), "canonical"),
])
def test_one_changed_byte_is_refused_and_named(what, change, named):
    data, index, objects = published()
    d, i, o = change(data, index, objects)
    problems = st.verify(d, i, o)
    assert problems, what
    assert any(named in p for p in problems), (what, problems)


def test_a_file_the_index_does_not_name_is_not_read():
    data, index, objects = published()
    assert st.verify(data, index, {**objects, "index.json": json.dumps(index).encode(), "x.bin": b"x"}) == []


def test_the_valid_fixture_is_what_make_writes():
    """The contract's valid fixture is no hand copy: it is this statement, so contracts/check.py validates what
    `make` writes (a slot relation, a knowledge time with an offset)."""
    data, _, _ = published()
    assert yaml.safe_load(FIXTURE.read_text("utf-8")) == json.loads(data)


def test_a_made_statement_is_valid_against_its_contract():
    validator = pytest.importorskip("linkml.validator")
    data, _, _ = published()
    report = validator.validate(json.loads(data), str(CONTRACT), "EpochStatement")
    assert [r.message for r in report.results] == []


def restated(data: bytes, change) -> bytes:
    """The statement with `change` applied, in RFC 8785's bytes again (sorted, compact): only its shape differs."""
    s = json.loads(data)
    change(s)
    return json.dumps(s, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@pytest.mark.parametrize("where, change, named", [
    ("the statement", lambda s: s.update(signature="x"), "signature"),
    ("the predicate", lambda s: s["predicate"].update(pack_sha256="0" * 64), "pack_sha256"),
    *[("the predicate", lambda s, k=k: s["predicate"].update({k: ""}), k)
      for k in ("previous", "compiler", "source", "checks")],  # version 1: no place for them, not even empty
    ("a subject", lambda s: s["subject"][0].update(uri="x"), "uri"),
    ("a digest", lambda s: s["subject"][0]["digest"].update(sha512="0"), "sha512"),
    ("a snapshot", lambda s: s["predicate"]["snapshots"][0].update(full="true"), "full"),
    ("the predicate", lambda s: s["predicate"].pop("inclusion"), "inclusion"),
    ("the predicate", lambda s: s["predicate"].update(epoch=3), "epoch is not text"),
    ("the predicate", lambda s: s["predicate"].update(roots="x"), "roots"),
    ("the statement", lambda s: s.update(predicate=[]), "predicate is not an object"),
    ("a subject", lambda s: s["subject"][0].pop("name"), "lacks ['name']"),
    ("the subjects", lambda s: s["subject"].reverse(), "sorted"),
])
def test_a_name_or_shape_the_contract_refuses_is_refused(where, change, named):
    data, index, objects = published()
    problems = st.verify(restated(data, change), index, objects)
    assert any(named in p for p in problems), (where, problems)


def test_the_pin_and_the_roots_are_recomputed_from_the_subjects_bytes():
    """Condition (a) of the ruling on #886: other rows whose file hashes agree everywhere are still refused,
    because the dataset pin, the roots and the inclusion hash are recomputed from the bytes."""
    data, index, objects = published()
    rows = changed(objects["rows.json"], b"host-b", b"host-c")
    objects = {**objects, "rows.json": rows}

    def resign(s):
        for x in s["subject"]:
            if x["name"] == "rows.json":
                x["digest"]["sha256"] = sha(rows)

    data = restated(data, resign)
    now = {"rows.json": sha(rows), st.NAME: sha(data)}
    index = {**index, "objects": [{**x, "sha256": now.get(x["name"], x["sha256"])} for x in index["objects"]]}
    problems = st.verify(data, index, objects)
    assert not any("sha256" in p for p in problems), problems
    assert "predicate dataset is not the hash of the rows" in problems
    assert "the inclusion hash is not the hash of the roots" in problems
    assert any(p.startswith("the row-tree roots are not those of the rows") for p in problems)


def test_rows_that_are_no_subject_are_not_read():
    data, index, objects = published()
    problems = st.verify(restated(data, lambda s: s["subject"][1]["digest"].update(sha256="0" * 64)), index, objects)
    assert "rows.json is not a subject with its bytes" in problems


def test_the_reader_runs_on_a_folder(tmp_path, capsys):
    data, index, objects = published()
    for n, b in {**objects, st.NAME: data, "index.json": json.dumps(index).encode()}.items():
        (tmp_path / n).write_bytes(b)
    assert st.main(["verify", str(tmp_path)]) == 0
    assert "(signature not checked)" in capsys.readouterr().out
    (tmp_path / "rows.json").write_bytes(changed(objects["rows.json"], b"gpu", b"cpu"))
    assert st.main(["verify", str(tmp_path)]) == 2


# Frozen bytes of a publication sealed before the Rezono rename:
# carries the legacy statement predicateType, format, schema key, and proof URI scheme.
PRE_RENAME_SEALED_STATEMENT = (
    b'{"_type":"https://in-toto.io/Statement/v1","predicate":{'
    b'"annotation":"4f612dc9f77e9eb64c1654ea425a491a3c868980d1ec184e91018c9e9f23739b",'
    b'"dataset":"d-4d6d31d9b5a411567b914c0ba305fd080df7328278652e3f2459a84a59354349",'
    b'"definition":"1111111111111111111111111111111111111111111111111111111111111111",'
    b'"epoch":"1","format":"rede.epoch-statement/1",'
    b'"inclusion":"773202cfc6a2b19d8fcf1b3f299fd358bea47658880b0827c8d26e2ee34e5427",'
    b'"knowledge_time":"2026-01-01T00:00:00Z","manifest":"m-1","pack":"toy","role":"guest",'
    b'"role_manifest":"7f009bf88424113a65cc302fc89f5038201d37d311d322718df383725b8474f6",'
    b'"roots":{"$src":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",'
    b'"$why":"fcc46d0311f2b660b915739d0510990316e3362ab5a001d3fb786a4e3a71e503",'
    b'"Host":"6a7af911234cd5f02e5827a2987a1431b004279e52eeeab50bf49ff9fc41d5bc"},'
    b'"schema":"s-684066efd8e235411fa3fc3ef2c8e1653d8e6ae3ead985427a7dfc825e799ffa",'
    b'"snapshots":[{"relation":"host","sha256":"3333333333333333333333333333333333333333333333333333333333333333"}]},'
    b'"predicateType":"https://rede.dev/epoch-statement/v1",'
    b'"subject":[{"digest":{"sha256":"4cca650fcc958615bb3cdd7b89aaabde09883dcdec6eef957a182cd0ff219357"},'
    b'"name":"hashes.json"},'
    b'{"digest":{"sha256":"a55962b7da81fd4553f1383a24c4e7dbd4c145b3e1095d3be3367a9b7ed792c6"},"name":"rows.json"},'
    b'{"digest":{"sha256":"684066efd8e235411fa3fc3ef2c8e1653d8e6ae3ead985427a7dfc825e799ffa"},"name":"schema.json"},'
    b'{"digest":{"sha256":"4f7e462882acfdec31796ac12d768706e8195ee4867b89e501709138f3cab325"},'
    b'"name":"table.Host.parquet"}]}'
)
PRE_RENAME_SEALED_OBJECTS = {
    "schema.json": (
        b'{"base":"https://toy.example/","kinds":{"Host":{"id":{"type":"Text"},'
        b'"slots":{"role":{"card":"1","states":["known"],"type":"Text"}},"world":"closed"}},"pack":"toy","reckon":"1.0"}'
    ),
    "rows.json": (
        b'{"$rows":[{"$id":"h-1","$kind":"Host","$why":{"role":"rede:w/0001"},"role":"edge"}],'
        b'"$schema":"s-684066efd8e235411fa3fc3ef2c8e1653d8e6ae3ead985427a7dfc825e799ffa"}'
    ),
    "hashes.json": (
        b'{"annotation":"4f612dc9f77e9eb64c1654ea425a491a3c868980d1ec184e91018c9e9f23739b",'
        b'"dataset":"d-4d6d31d9b5a411567b914c0ba305fd080df7328278652e3f2459a84a59354349",'
        b'"definition":"c-71daf5b969d5fd292c6f0d75f60984736eeebcc5b878040f72b3e86710a91e3e",'
        b'"schema":"s-684066efd8e235411fa3fc3ef2c8e1653d8e6ae3ead985427a7dfc825e799ffa",'
        b'"side_tables":{"$src":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",'
        b'"$why":"ab9eee8332e0bc7dfa16e392dd23986e64944e7f02a26e1065d4aa9ac1c498ab"},'
        b'"tables":{"Host":"caa524978d32d15a2401d074239026d37cd14b21f8399b070225bf667ddc2a89"}}'
    ),
    "table.Host.parquet": b"PAR1-sealed-stub",
}
PRE_RENAME_SEALED_INDEX = {
    "pack": "toy",
    "role": "guest",
    "schema": "s-684066efd8e235411fa3fc3ef2c8e1653d8e6ae3ead985427a7dfc825e799ffa",
    "dataset": "d-4d6d31d9b5a411567b914c0ba305fd080df7328278652e3f2459a84a59354349",
    "manifest": {
        "id": "m-1",
        "epoch": 1,
        "knowledge_time": "2026-01-01T00:00:00Z",
        "definition_sha256": "1" * 64,
        "compiled": [{"file": "bundle/schema-bundle.json", "sha256": "2" * 64}],
        "role": "guest",
    },
    "sources": [{"relation": "host", "sha256": "3" * 64}],
    "objects": [
        {"name": "hashes.json", "sha256": "4cca650fcc958615bb3cdd7b89aaabde09883dcdec6eef957a182cd0ff219357"},
        {"name": "rows.json", "sha256": "a55962b7da81fd4553f1383a24c4e7dbd4c145b3e1095d3be3367a9b7ed792c6"},
        {"name": "schema.json", "sha256": "684066efd8e235411fa3fc3ef2c8e1653d8e6ae3ead985427a7dfc825e799ffa"},
        {"name": "table.Host.parquet", "sha256": "4f7e462882acfdec31796ac12d768706e8195ee4867b89e501709138f3cab325"},
        {"name": "statement.json", "sha256": "3c3be7c2c5b5ed2e2d13870f104d06533f21163394920a10da277aac6560897e"},
    ],
}


def test_a_pre_rename_sealed_publication_is_accepted(tmp_path):
    carried = {k: v for k, v in PRE_RENAME_SEALED_OBJECTS.items() if k != "table.Host.parquet"}
    assert st.verify(
        PRE_RENAME_SEALED_STATEMENT, PRE_RENAME_SEALED_INDEX, carried, absent={"table.Host.parquet"}
    ) == []
    for n, b in {
        **PRE_RENAME_SEALED_OBJECTS,
        st.NAME: PRE_RENAME_SEALED_STATEMENT,
        "index.json": json.dumps(PRE_RENAME_SEALED_INDEX).encode(),
    }.items():
        (tmp_path / n).write_bytes(b)
    assert st.main(["verify", str(tmp_path)]) == 0
    tampered = {**carried, "rows.json": changed(carried["rows.json"], b'"edge"', b'"core"')}
    problems = st.verify(PRE_RENAME_SEALED_STATEMENT, PRE_RENAME_SEALED_INDEX, tampered, absent={"table.Host.parquet"})
    assert any("rows.json" in p for p in problems)

