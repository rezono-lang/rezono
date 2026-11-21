"""Conclusion IRIs through the local reader (decisions/publication-conclusion-addresses.md §1, §3, §4): the epoch
listing and `/<pack>/resolve`, on a store the publisher built with each filtered role's publication form.

Every expectation comes from the Python side: the IRI of each row is `rdf.conclusion_iri` under the role's
publication schema, its pin is the dataset hash of the role's form (`hashes.json`), and `rdf.resolve_iri` resolves
the same pinned IRI to the same row. The fixture gets a subkind (a Spare is an Item), which shares its root's IRI
space. Three epochs:

- m-1: `summary` also reads links; there is no role `guest` yet.
- m-2: `summary` reads no link any more, so it can no longer read m-1; `guest` reads what `summary` reads. m-2 is
  withdrawn afterwards (decisions/publication-supersession-and-withdrawal.md §2).
- m-3: item-a's amount is 13, so its flagged row is another tuple; the row item-c of m-3 is withdrawn.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml
from slip_support import FIXTURE, PACK, ROOT

from rezono_compiler import modules
from rezono_publication import rdf
from rezono_publisher import batch, publish, store as stores

PROBE = Path(__file__).with_name("standing_reader.mjs")
ROLES = {"checker": "complete", "reader": "may_read", "summary": "may_read"}
REASON = "The second epoch read an unverified extract."
ROW_REASON = "item-c was entered twice."


def query(target: Path, role: str, *paths: str) -> list[dict]:
    run = subprocess.run([os.environ.get("REZONO_NODE", "node"), str(PROBE)],
                         input=json.dumps({"store": target.as_posix(), "role": role, "requests": list(paths)}),
                         capture_output=True, encoding="utf-8", timeout=300, cwd=ROOT)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def resolve(iri: str) -> str:
    return f"/{PACK}/resolve?iri={quote(iri, safe='')}"


def edit(path: Path, change) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")


def capabilities(rows: dict, role: str, given: list[str]) -> None:
    for entry in rows["role"]:
        if entry["id"] == role:
            entry["capability"] = given
            return
    rows["role"].append({"id": role, "title": role.title(), "capability": given})


@pytest.fixture(scope="module")
def published(tmp_path_factory):
    directory = tmp_path_factory.mktemp("addresses")
    pack = modules.copy_closure(FIXTURE, directory / "closure")
    # A subkind: a Spare is an Item, and the role that reads items reads spares.
    edit(pack / "schema" / "slip.yaml", lambda d: d["classes"].update({"Spare": {"is_a": "Item"}}))
    edit(pack / "facts" / "rows.yaml", lambda d: d.update({"spare": [{"id": "item-d", "group": "group-b", "amount": 3}]}))
    with (pack / "rules" / "access.dl").open("a", encoding="utf-8", newline="\n") as rules:
        rules.write('may_read(r, "spare", s) :- role__capability(r, "read"), spare(s).\n'
                    'may_read_full(r, "spare") :- role__capability(r, "read").\n')
    target = directory / "store"
    st = stores.FileStore(target)
    manifests = {}

    def epoch(n: int, roles: dict) -> None:
        e = batch.epoch(pack, epoch=n, knowledge_time=f"2026-01-0{n}T00:00:00Z", sources=[("rules", f"epoch-{n}")])
        manifests[n] = publish.publish(e, st, roles, forms=True)

    edit(pack / "facts" / "rows.yaml", lambda d: capabilities(d, "summary", ["read", "read_restricted"]))
    epoch(1, ROLES)
    edit(pack / "facts" / "rows.yaml", lambda d: (capabilities(d, "summary", ["read"]),
                                                   capabilities(d, "guest", ["read"])))
    epoch(2, ROLES | {"guest": "may_read"})
    edit(pack / "facts" / "rows.yaml", lambda d: next(i for i in d["item"] if i["id"] == "item-a").update(amount=13))
    epoch(3, ROLES | {"guest": "may_read"})
    for record in ({"id": "wd-epoch", "epochs": ["m-2"], "reason": REASON},
                   {"id": "wd-row", "rows": [{"relation": "item", "key": ["item-c"], "manifest": "m-3"}],
                    "reason": ROW_REASON}):
        st.put_new(f"{PACK}/withdrawals/{record['id']}.json", json.dumps({
            "format": "rezono.withdrawal/1", "state": "withdrawn", "decider": ["board"], "decided_on": "2026-02-01",
            **record}, sort_keys=True).encode("utf-8"))
    return target, st, manifests


def form(st, manifest: str, role: str) -> tuple[dict, list[dict], str]:
    """The role's publication form of a manifest, as the publisher wrote it: schema, rows and dataset hash."""
    prefix = f"{PACK}/{manifest}/{role}/publication/"
    schema = json.loads(st.get(prefix + "schema.json"))
    rows = json.loads(st.get(prefix + "rows.json"))["$rows"]
    return schema, rows, json.loads(st.get(prefix + "hashes.json"))["dataset"]


@pytest.mark.parametrize("role,manifest", [("reader", "m-1"), ("reader", "m-3"), ("summary", "m-3"), ("guest", "m-3")])
def test_every_row_of_the_form_resolves_from_its_pinned_iri_as_python_resolves_it(published, role, manifest):
    target, st, _ = published
    schema, rows, dataset = form(st, manifest, role)
    rows = [r for r in rows if not (manifest == "m-3" and r["$kind"] == "Item" and r["$id"] == "item-c")]
    pinned = [rdf.conclusion_iri(schema, r["$kind"], r["$id"], manifest=manifest, dataset=dataset) for r in rows]
    replies = query(target, role, *(resolve(iri) for iri in pinned))
    kinds = set()
    for row, iri, reply in zip(rows, pinned, replies):
        assert rdf.resolve_iri(schema, rows, iri, manifest=manifest, dataset=dataset) == row  # Python's own answer
        assert reply["status"] == 200, (iri, reply)
        body = reply["body"]
        derived = "tuple_key" in schema["kinds"][row["$kind"]]
        assert body["kind"] == row["$kind"], (iri, body)
        assert body["key"] == (json.loads(row["$id"]) if derived else [row["$id"]]), (iri, body)
        assert (body["manifest"], body["dataset"], body["pinned_iri"]) == (manifest, dataset, iri)
        assert body["iri"] == rdf.conclusion_iri(schema, row["$kind"], row["$id"])
        kinds.add(row["$kind"])
    assert {"Item", "Spare", "Flagged", "GroupSize", "CalcCappedAmount"} <= kinds
    spare = next(r for r in rows if r["$kind"] == "Spare")
    assert rdf.conclusion_iri(schema, "Spare", spare["$id"]).startswith(schema["base"] + "Item/")  # the root's space


def test_a_subkind_has_no_space_of_its_own_and_a_kept_row_keeps_its_iri_across_epochs(published):
    target, st, _ = published
    s1, _, d1 = form(st, "m-1", "reader")
    s3, _, d3 = form(st, "m-3", "reader")
    item_a = rdf.conclusion_iri(s3, "Item", "item-a")
    assert item_a == rdf.conclusion_iri(s1, "Item", "item-a") and d1 != d3
    flagged_12 = rdf.conclusion_iri(s1, "Flagged", json.dumps(["item-a", "12"], separators=(",", ":")))
    own_space = s3["base"] + "Spare/item-d"
    replies = query(target, "reader", resolve(item_a), resolve(rdf.pin_iri(item_a, manifest="m-1", dataset=d1)),
                    resolve(flagged_12), resolve(rdf.pin_iri(flagged_12, manifest="m-1", dataset=d1)), resolve(own_space))
    assert [r["status"] for r in replies] == [200, 200, 404, 200, 404], replies
    assert replies[0]["body"]["pinned_iri"] == rdf.pin_iri(item_a, manifest="m-3", dataset=d3)
    assert replies[1]["body"]["pinned_iri"] == rdf.pin_iri(item_a, manifest="m-1", dataset=d1)
    assert replies[1]["headers"]["x-rezono-standing"] == "superseded"
    assert replies[0]["headers"]["x-rezono-standing"] == "current"


def test_a_pin_is_the_dataset_hash_of_the_role_form(published):
    target, st, manifests = published
    schema, _, dataset = form(st, "m-3", "reader")
    iri = rdf.conclusion_iri(schema, "Item", "item-a")
    manifest_sha = hashlib.sha256(st.get(f"{PACK}/manifests/m-3.json")).hexdigest()
    _, _, summary_dataset = form(st, "m-3", "summary")
    replies = query(target, "reader",
                    resolve(rdf.pin_iri(iri, dataset=dataset)),
                    resolve(rdf.pin_iri(iri, manifest="m-3", dataset=dataset)),
                    resolve(rdf.pin_iri(iri, manifest="m-3", dataset="d-" + manifest_sha)),  # the manifest's own hash
                    resolve(rdf.pin_iri(iri, manifest="m-3", dataset=summary_dataset)))  # another role's dataset
    assert [r["status"] for r in replies] == [200, 200, 409, 409], replies
    assert summary_dataset != dataset


def test_an_epoch_the_role_never_had_is_not_there_or_can_no_longer_read_answers_the_same(published):
    target, st, _ = published
    schema, _, dataset = form(st, "m-1", "summary")
    iri = rdf.conclusion_iri(schema, "Item", "item-a")
    asked = [rdf.pin_iri(iri, manifest=m, dataset=dataset) for m in ("m-1", "m-7")]
    summary = query(target, "summary", *(resolve(i) for i in asked))  # m-1: it read links then, and no more now
    guest = query(target, "guest", *(resolve(i) for i in asked))  # m-1: it had no snapshot of it
    reader = query(target, "reader", resolve(asked[0]))
    assert reader[0]["status"] == 200, reader  # the epoch is there, and readable to a role that still reads it
    assert summary[0]["status"] == 404, summary
    for reply in [*summary, *guest]:
        assert reply == summary[0], (reply, summary[0])
    listed = {role: [m["id"] for m in query(target, role, f"/{PACK}/manifests")[0]["body"]["manifests"]]
              for role in ("summary", "guest")}
    assert listed == {"summary": ["m-3", "m-2"], "guest": ["m-3", "m-2"]}


def test_withdrawn_epochs_and_rows_answer_410_with_their_reason(published):
    target, st, _ = published
    s2, _, d2 = form(st, "m-2", "reader")
    s3, _, d3 = form(st, "m-3", "reader")
    replies = query(target, "reader",
                    resolve(rdf.conclusion_iri(s2, "Item", "item-a", manifest="m-2", dataset=d2)),
                    resolve(rdf.conclusion_iri(s3, "Item", "item-c", manifest="m-3", dataset=d3)),
                    resolve(rdf.conclusion_iri(s3, "Item", "item-c")))
    assert [r["status"] for r in replies] == [410, 410, 410], replies
    assert replies[0]["body"]["withdrawal"] == {"id": "wd-epoch", "decider": ["board"], "decided_on": "2026-02-01",
                                               "reason": REASON}
    assert replies[1]["body"]["reason"] == replies[2]["body"]["reason"] == ROW_REASON
    assert all(r["headers"]["x-rezono-standing"] == "withdrawn" for r in replies)


def test_the_listing_pages_newest_first_and_shows_a_withdrawn_epoch_with_its_withdrawal(published):
    target, st, _ = published
    [whole, first, second, third, bad] = query(
        target, "reader", f"/{PACK}/manifests", f"/{PACK}/manifests?limit=1", f"/{PACK}/manifests?limit=1&after=m-3",
        f"/{PACK}/manifests?limit=1&after=m-2", f"/{PACK}/manifests?after=m-03")
    manifests = whole["body"]["manifests"]
    assert [(m["id"], m["standing"]) for m in manifests] == [("m-3", "current"), ("m-2", "withdrawn"),
                                                              ("m-1", "superseded")]
    assert manifests[1]["withdrawal"] == {"id": "wd-epoch", "decider": ["board"], "decided_on": "2026-02-01",
                                          "reason": REASON}
    for m in manifests:
        head = json.loads(st.get(f"{PACK}/heads/{10**19 - 1 - m['epoch']:019d}.json"))
        assert m["manifest_sha256"] == head["sha256"]
    assert "next" not in whole["body"]
    assert [m["id"] for m in first["body"]["manifests"]] == ["m-3"] and first["body"]["next"] == "m-3"
    assert [m["id"] for m in second["body"]["manifests"]] == ["m-2"] and second["body"]["next"] == "m-2"
    assert [m["id"] for m in third["body"]["manifests"]] == ["m-1"] and "next" not in third["body"]
    assert bad["status"] == 400


def test_what_the_reader_cannot_resolve_is_said_so(published):
    target, st, _ = published
    schema, _, dataset = form(st, "m-3", "summary")
    base = schema["base"]
    link = base + "Link/link-a"  # a kind summary does not read: as absent as an id no kind holds
    replies = query(target, "summary",
                    resolve(rdf.canonical_witness_iri(schema, {"rule_id": "held", "conclusion": {}})),
                    resolve(base + "witness/abc"),
                    resolve(base + "Item/item-a?pin=m-03@" + dataset),
                    resolve(base + "Item/item~2Da"),
                    resolve(base + "Item/no-such-item"),
                    resolve(link),
                    resolve(base + "Item/"))
    assert [r["status"] for r in replies] == [501, 400, 400, 400, 404, 404, 400], replies
    assert replies[4] == replies[5]
    assert query(target, "reader", resolve(link))[0]["status"] == 200
