"""The subsidy pack's publication forms, as the publisher writes them (rezono_publisher.forms).

Subsidy is the first published pack whose roles read differently: the case officer reads the payment ledger,
the policy adviser does not. The publication form checks:

- each role's form verifies from its own files alone: the objects its index names, nothing else;
- non-interference (R6, the two-world test): two packs that differ only in a ledger payment, which the
  policy adviser does not read, give the policy adviser the same bytes and the case officer other bytes;
- the complete form is written nowhere: no `publication/` object outside the filtered roles' own prefixes.

Each filtered role fetches its standards exports and their loss lists through its index, and
each passes its independent reader (`edge/plugins/connectors/accept.py`, `published`) on those bytes.

Each filtered role fetches its tables, one object per table and form, and the library recomputes the
dataset hash from the tables of one form alone; DuckDB, an independent reader, reads each Parquet table with the
same number of rows. The two-world test above covers the tables too: they are among the objects compared.

Needs the compiler with DuckDB and the publisher.
"""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

from rezono_publisher import batch, forms, publish, store  # noqa: E402

from rezono_publication import arrow, l0  # noqa: E402  (the repository root is on the path through rezono_publisher.forms)
from rezono_publication.hash import hashes  # noqa: E402
from rezono_publication import statement  # noqa: E402

HERE = Path(__file__).parent
PACK = "subsidy"
ROLES = {"checker": "complete", "case_officer": "may_read", "policy_adviser": "may_read"}
FILTERED = ("case_officer", "policy_adviser")
PAYMENT = '{"id": "P001", "application": "A001", "booked_on": "2026-10-06", "amount": 269400}'


def copy(tmp: Path) -> Path:
    """A copy of the pack at the same depth, next to packs/ and the scheme it imports, so the imports resolve."""
    root = HERE.parents[1]
    d = tmp / "examples" / "subsidy"
    shutil.copytree(HERE, d, ignore=shutil.ignore_patterns("expected", "__pycache__", "test_*.py"))
    shutil.copytree(HERE.parent / "subsidy-scheme", d.parent / "subsidy-scheme")
    try:
        (tmp / "packs").symlink_to(root / "packs", target_is_directory=True)
    except OSError:  # no symbolic links without rights (Windows): a copy pins the same bytes
        shutil.copytree(root / "packs", tmp / "packs")
    return d


def published(pack_dir: Path, root: Path):
    e = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-11-10T00:00:00Z", sources=[("rules", "test")])
    s = store.FileStore(root)
    return s, publish.publish(e, s, ROLES, forms=True)


def objects(s, role: str) -> dict[str, bytes]:
    """A role's form as the role fetches it: its index, then each object it names, by sha256."""
    index = json.loads(s.get(forms.index_key(PACK, "m-1", role)))
    out = {}
    for o in index["objects"]:
        data = s.get(forms.key_of(o["uri"]))
        assert data is not None and forms.sha256(data) == o["sha256"] and len(data) == o["bytes"], o["name"]
        assert forms.key_of(o["uri"]).startswith(forms.prefix(PACK, "m-1", role)), o["uri"]
        out[o["name"]] = data
    return {"index.json": json.dumps(index, sort_keys=True).encode()} | out


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    return published(HERE, tmp_path_factory.mktemp("store"))


def test_each_role_s_form_verifies_from_its_own_files_alone(world):
    s, m = world
    datasets = {}
    for role in FILTERED:
        got = objects(s, role)
        index = json.loads(got["index.json"])
        assert index["manifest"]["id"] == m["id"] and index["role"] == role
        schema = json.loads(got["schema.json"])
        rows = l0.read_collection(schema, json.loads(got["rows.json"]))
        h = hashes(schema, rows)  # offline: the library, the role's three objects, nothing else
        assert h == json.loads(got["hashes.json"])
        assert h["dataset"] == index["dataset"] and h["schema"] == index["schema"] == l0.check_schema(schema)
        datasets[role] = h["dataset"]
    assert datasets["case_officer"] != datasets["policy_adviser"]  # they read differently


def test_each_role_s_epoch_statement_says_what_its_files_say(world):
    """Per filtered role one statement, read back from the bytes the role fetches through its index alone;
    the two roles read differently, so their statements differ, and neither names the pack hash."""
    s, m = world
    made = {}
    for role in FILTERED:
        got = objects(s, role)
        index = json.loads(got["index.json"])
        assert statement.verify(got[statement.NAME], index, got) == []
        p = json.loads(got[statement.NAME])["predicate"]
        assert (p["pack"], p["role"], p["manifest"], p["dataset"]) == (PACK, role, m["id"], index["dataset"])
        assert m["pack_sha256"] not in got[statement.NAME].decode("utf-8")
        made[role] = p["inclusion"]
    assert made["case_officer"] != made["policy_adviser"]


def test_the_policy_adviser_s_form_holds_nothing_of_the_ledger(world):
    s, _ = world
    kinds = {}
    for role in FILTERED:
        rows = json.loads(objects(s, role)["rows.json"])["$rows"]
        kinds[role] = {r["$kind"] for r in rows}
    assert "LedgerPayment" in kinds["case_officer"]
    assert "LedgerPayment" not in kinds["policy_adviser"]


def test_a_ledger_payment_does_not_change_the_policy_adviser_s_form(request, tmp_path):
    """Non-interference (R6): change what only the case officer reads, and the policy adviser's form stays byte
    for byte; the case officer's changes, so the change is real."""
    d = copy(tmp_path / "pack")
    facts = d / "facts" / "ledger.yaml"
    text = facts.read_text(encoding="utf-8")
    assert PAYMENT in text
    facts.write_text(text.replace(PAYMENT, PAYMENT.replace("269400", "269401")), encoding="utf-8")
    other, _ = published(d, tmp_path / "store")
    # The unchanged world only now: in CI another process publishes it meanwhile (scripts/components.py).
    s, _ = request.getfixturevalue("world")
    assert objects(other, "policy_adviser") == objects(s, "policy_adviser")
    assert objects(other, "case_officer")["rows.json"] != objects(s, "case_officer")["rows.json"]
    # The epoch statement too: the policy adviser's is the same bytes, the case officer's is not.
    assert objects(other, "policy_adviser")[statement.NAME] == objects(s, "policy_adviser")[statement.NAME]
    assert objects(other, "case_officer")[statement.NAME] != objects(s, "case_officer")[statement.NAME]


def test_the_complete_form_is_written_nowhere(world):
    s, _ = world
    written = [k for k in s.list(f"{PACK}/") if "/publication/" in k]
    assert written and all(any(k.startswith(forms.prefix(PACK, "m-1", r)) for r in FILTERED) for k in written)
    assert not s.list(forms.prefix(PACK, "m-1", "checker"))


def test_each_role_s_form_marks_the_scheme_parameters_as_decided_values(world):
    # DV1: SchemeParameter says `plane: control`; every role reads it in full, so every form carries the marker,
    # its owner, and a decision that is always known (publication L0 section 3.7).
    s, _ = world
    for role in FILTERED:
        kinds = json.loads(objects(s, role)["schema.json"])["kinds"]
        rate = kinds["SchemeParameter"]
        assert (rate["plane"], rate["owner"]) == ("control", "policy_adviser")
        assert rate["slots"]["decision"] == {"card": "1", "ref": "Decision", "states": ["known"]}
        assert [k for k, v in kinds.items() if "plane" in v] == ["SchemeParameter"]


def test_each_role_s_form_carries_the_base_the_pack_declares(world):
    # Pack.yaml `iri:` gives the schema document its base, and every element its IRI under it.
    s, _ = world
    rdf = pytest.importorskip("rezono_publication.rdf")
    for role in FILTERED:
        schema = json.loads(objects(s, role)["schema.json"])
        assert schema["base"] == "https://rezono.org/example/subsidy/"
        assert not [k for k, v in schema["kinds"].items() if "iri" in v]  # every kind lives under the base
        iri = rdf.element_iri(schema, "Application", "A001")
        assert iri == "https://rezono.org/example/subsidy/Application/A001"


def test_each_role_s_standards_exports_pass_their_readers(world):
    """The exports and their loss lists, as the role fetches them, each against its independent reader."""
    pytest.importorskip("pyshacl")
    pytest.importorskip("open_data_contract_standard")
    spec = importlib.util.spec_from_file_location("rezono_accept", HERE.parents[1] / "edge" / "plugins" / "connectors"
                                                  / "accept.py")
    accept = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(accept)
    s, _ = world
    for role in FILTERED:
        got = objects(s, role)
        names = {o["name"] for o in json.loads(got["index.json"])["objects"]}
        assert {"view.ttl", "context.jsonld", "prov.ttl", "shapes.ttl", "contract.odcs.yaml", "dcat.ttl"} <= names
        assert {"rdf.losses.yaml", "prov-o.losses.yaml", "shacl.losses.yaml", "odcs.losses.yaml",
                "dcat.losses.yaml"} <= names
        report = accept.published(got, s.uri(forms.prefix(PACK, "m-1", role)))
        assert all(r["state"] == "accepted" for r in report.values()), (role, report)


def test_each_role_s_tables_give_its_dataset_hash_alone(world, tmp_path):
    """The Arrow and the Parquet tables, as the role fetches them, each form by itself."""
    import duckdb

    s, _ = world
    for role in FILTERED:
        got = objects(s, role)
        index = json.loads(got["index.json"])
        schema = json.loads(got["schema.json"])
        for f in arrow.FORMS:
            files = {n: b for n, b in got.items() if n.startswith("table.") and n.endswith("." + f)}
            assert len(files) == len(arrow.table_names(schema)), (role, f)
            assert hashes(schema, arrow.from_files(schema, files, f))["dataset"] == index["dataset"], (role, f)
        for name, data in got.items():
            if name.endswith(".parquet"):
                path = tmp_path / f"{role}.{name}"
                path.write_bytes(data)
                rows = arrow.read_table_bytes(got[name[: -len("parquet")] + "arrow"], "arrow").num_rows
                assert duckdb.sql(f"select count(*) from read_parquet('{path.as_posix()}')").fetchall()[0][0] == rows
