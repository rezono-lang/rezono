"""A tenant's two public totals cross a written decision, never a private reading."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex
from rezono_checker.evidence import Evidence
from rezono_compiler import pack, rules
from rezono_publisher import batch, publish, store


ROOT = Path(__file__).resolve().parent
TENANT = "sprig"
PEER = "private-neighbor"
SUMMARY = "tenant_capacity_summary"
BASIS = "platform_capacity_basis"
RECEIPT_SOURCE = "capacity-readings"
RECEIPT_TAG = "capacity-reading"
# Period, pool limit, tenant usage, peer usage. Distinct limits and free space.
PERIODS = (("early", 11, 3, 5), ("late", 17, 4, 6))


class MissingCapacityPublication(Exception):
    pass


def row(ref):
    return ref["relation"], tuple(json.loads(ref["key"]))


def graph(rows, proof, complete, program):
    """Walk every emitted edge, including negative and aggregate scopes and calculation premises."""
    assert proof["hidden"] == []
    edges = {}
    for calc in (False, True):
        for w in proof.get("calc_witnesses" if calc else "witnesses", ()):
            head = row(w["conclusion"])
            assert head in rows, head
            if calc:
                assert head not in edges, head
            parents = set()
            for premise in w["premises"]:
                child = row(premise if calc else premise["row"])
                if calc or premise["polarity"] == "positive":
                    assert child in rows, child
                    parents.add(child)
                else:
                    assert premise["polarity"] == "negative" and child[0] in complete and child not in rows, child
            for a in w.get("aggregates", ()):
                rel = a["relation"]
                assert rel in complete, rel
                atom = program.rules[w["rule_id"]].aggregates[a["position"]].atom
                assert atom.relation == rel
                bindings = {v["variable"]: v["value"] for v in w.get("bindings", ())}
                fixed = [(i, bindings.get(t, t)) for i, t in enumerate(atom.terms) if t != "_"]
                assert tuple(v for _, v in fixed) == tuple(json.loads(a["group_key"]))
                members = {r for r in rows if r[0] == rel and all(r[1][i] == v for i, v in fixed)}
                assert len(members) == a["count"]
                parents.update(members)
            edges.setdefault(head, set()).update(parents)
    return edges


def leaves(edges, start):
    pending, visited, result = [start], set(), set()
    while pending:
        item = pending.pop()
        if item not in visited:
            visited.add(item)
            if item in edges:
                pending.extend(edges[item])
            else:
                result.add(item)
    return result


def test_a_private_second_step_invalidates_an_otherwise_readable_graph():
    def ref(rel):
        return {"relation": rel, "key": '["x"]'}

    def witness(rel, premise):
        return {"conclusion": ref(rel), "premises": [{"row": ref(premise), "polarity": "positive"}]}

    readable = {row(ref(name)) for name in ("result", "middle", "public")}
    good = {"witnesses": [witness("result", "middle"), witness("middle", "public")], "hidden": []}
    assert leaves(graph(readable, good, set(), None), row(ref("result"))) == {row(ref("public"))}
    for invalid in (dict(good, witnesses=[witness("result", "middle"), witness("middle", "private")]),
                    dict(good, hidden=[ref("private")])):
        with pytest.raises(AssertionError):
            graph(readable, invalid, set(), None)


def snapshots(epoch, bucket, role, mode):
    manifest = publish.publish(epoch, bucket, {role: mode})
    keys = publish.role_objects(bucket, epoch.pack, manifest["id"], role)
    data = {name: bucket.get(key) for name, key in keys.items()}
    rows = {(path[10:-5], tuple(r["key"])) for path, body in data.items() if path.startswith("relations/")
            for r in json.loads(body)}
    full = {s["relation"] for s in manifest["snapshots"] if s["role"] == role and s["full"]}
    program = rules.load(json.loads(epoch.rules))
    edges = graph(rows, json.loads(data["witnesses.json"]), full, program)
    derived = set(program.derived())
    for relation, key in rows:
        if relation in derived or relation.startswith("c__"):
            assert (relation, key) in edges, (relation, key)
    return rows, edges, data


def prepare(directory):
    target = directory / "examples" / "platform"
    shutil.copytree(ROOT, target)
    shutil.copytree(ROOT.parents[1] / "packs", directory / "packs")
    observations = []
    for period, _, own, other in PERIODS:
        for team, value in [(TENANT, own), (PEER, other)]:
            observations.append({"id": f"{team}-{period}", "tenant": team, "period": period, "cores": value})
    source = {"capacity_reading": observations,
              "capacity_pool": [{"id": period, "cores": cap} for period, cap, _, _ in PERIODS],
              "role": [{"id": name, "title": name} for name in (TENANT, PEER)]}
    (target / "facts" / "audit-readings.yaml").write_text(yaml.safe_dump(source), encoding="utf-8")
    return target


def capacity_evidence():
    """Pinned trusted context and candidate completeness receipt covering every reading in PERIODS
    (decisions/scoped-completeness.md, decisions/admission-transport.md section 6)."""
    archive = {}

    def pin(name, value):
        data = canonical_bytes(value)
        uri = f"archive/{name}"
        archive[uri] = data
        return {"file": name, "uri": uri, "sha256": sha256_hex(data)}

    source = {"kind": "query", "name": RECEIPT_SOURCE, "revision": "snapshot-1", "position": "/enumeration"}
    authorization = pin("observations/retained/authorization.json", {"issuer": "capacity-observer"})
    definition = pin("observations/retained/definition.json", {"query": RECEIPT_SOURCE})
    content = []
    for period, _, own, peer in PERIODS:
        for team, used in ((TENANT, own), (PEER, peer)):
            key = [RECEIPT_TAG, period, team]
            content.append({
                "key": key,
                "terminal": {**source, "position": f"/readings/{period}/{team}/end"},
                "rows": [{
                    "key": key,
                    "values": {"tenant": team, "period": period, "cores": used},
                    "source": {**source, "position": f"/readings/{period}/{team}/0"},
                }],
            })
    content.sort(key=lambda member: canonical_bytes(member["key"]))
    inventory = [member["key"] for member in content]

    def body(prefix):
        return {
            "source": source,
            "issuer": {"id": "capacity-observer", "authorization": authorization},
            "scope": {"definition": definition, "query": RECEIPT_SOURCE, "bindings": []},
            "cut": {"frontier": {"source_id": RECEIPT_SOURCE, "position": "snapshot-1"}},
            "inventory": pin(f"{prefix}/inventory.json", inventory),
            "content": pin(f"{prefix}/content.json", content),
        }

    trusted = body("observations/retained")
    submitted = body("observations/submitted")
    identity = canonical_sha256(["rezono.completeness-receipt/1", submitted])
    candidate = pin("observations/submitted/receipt.json", submitted | {"id": identity})
    context = pin("observations/retained/context.json", {"completeness": [trusted], "rounds": []})
    index = pin("observations/submitted/index.json", {"completeness_receipts": [candidate], "rounds": []})
    return Evidence(context, index, archive.__getitem__)


def state(target, private):
    notes = [{"id": f"note-{p}", "issuer": "platform", "origin": "decision", "period": p,
              "free_cores": cap - own - peer, "total_cores": own + peer}
             for p, cap, own, peer in PERIODS if not private or p != "late"]
    (target / "facts" / "public-decisions.yaml").write_text(
        yaml.safe_dump({"capacity_notice": notes}), encoding="utf-8")
    if private:
        # This substitute rule proves precisely the same late result in the real engine,
        # through a platform-only basis. The early summary keeps its ordinary readable witness.
        (target / "rules" / "test_private_basis.dl").write_text(
            'tenant_capacity_summary(t, "late", f, u, n) :- capacity_reading__tenant(x, t), '
            'capacity_reading__period(x, "late"), capacity_reading__cores(x, n), platform_capacity_basis("late", f, u).\n',
            encoding="utf-8")
    return batch.epoch(target, epoch=2 if private else 1, knowledge_time="2026-03-01T00:00:00Z",
                       sources=[("rules", "platform-proof-example")], evidence=capacity_evidence())


def declaration(period, free, used):
    return {(f"capacity_notice__{slot}", (f"note-{period}", value)) for slot, value in
            [("free_cores", free), ("total_cores", used), ("origin", "decision"), ("issuer", "platform")]}


def test_complete_tenant_publication_or_no_manifest(tmp_path):
    model = pack.read(ROOT)
    if not {BASIS, SUMMARY} <= set(rules.load(model.rules).derived()):
        raise MissingCapacityPublication("platform_capacity_basis and tenant_capacity_summary must be real rules")
    target = prepare(tmp_path)
    tenant_store = store.FileStore(tmp_path / "tenant")
    for private in (False, True):
        current = state(target, private)
        platform, details, _ = snapshots(current, store.FileStore(tmp_path / f"platform-{private}"),
                                          "platform", "complete")
        expected = set()
        for p, cap, own, peer in PERIODS:
            free, used = str(cap - own - peer), str(own + peer)
            summary = (SUMMARY, (TENANT, p, free, used, str(own)))
            expected.add(summary)
            basis = (BASIS, (p, free, used))
            assert basis in details and summary in platform
            private_inputs = {("capacity_reading__cores", (f"{t}-{p}", str(v)))
                              for t, v in [(TENANT, own), (PEER, peer)]}
            assert private_inputs | {("capacity_pool__cores", (p, str(cap)))} <= leaves(details, basis)
            if private and p == "late":
                assert private_inputs <= leaves(details, summary)
        if private:
            # The prior manifest, pointer and role objects must survive byte for byte.
            before = {k: tenant_store.get(k) for k in tenant_store.list("")}
            with pytest.raises(publish.Blocked, match=r"(?i)(proof|witness|unreadable|unprovable|incomplete|private premise)"):
                publish.publish(current, tenant_store, {TENANT: "may_read"})
            assert {k: tenant_store.get(k) for k in tenant_store.list("")} == before
            fresh = store.FileStore(tmp_path / "first-refusal")
            with pytest.raises(publish.Blocked, match=r"(?i)(proof|witness|unreadable|unprovable|incomplete|private premise)"):
                publish.publish(current, fresh, {TENANT: "may_read"})
            assert publish.role_objects(fresh, current.pack, "m-2", TENANT) == {}
            assert fresh.list(f"{current.pack}/manifests/") == []
            continue
        visible, proofs, files = snapshots(current, tenant_store, TENANT, "may_read")
        assert {r for r in visible if r[0] == SUMMARY and r[1][0] == TENANT} == expected
        assert not any(r[0] == BASIS for r in visible)
        assert all(PEER.encode() not in raw for raw in files.values())
        source_doc = json.loads(files["sources.json"])
        entries = source_doc if isinstance(source_doc, list) else source_doc["entries"]
        sources = {row(entry["row"]): entry["sources"] for entry in entries}
        for _, (team, p, free, used, own) in expected:
            summary = (SUMMARY, (team, p, free, used, own))
            note = declaration(p, free, used)
            assert note <= visible and not (note & proofs.keys())
            for leaf in note:
                assert any(s['kind'] == 'pack' and s['name'] == 'facts/public-decisions.yaml'
                           and s['position'].isdigit() for s in sources[leaf]), leaf
            assert {r for r in note if r[0].endswith("_cores")} <= leaves(proofs, summary)
            assert {("capacity_reading__tenant", (f"{TENANT}-{p}", TENANT)),
                    ("capacity_reading__cores", (f"{TENANT}-{p}", own))} <= leaves(proofs, summary)


class MissingNoticeMismatch(AssertionError):
    pass


MISMATCH = "capacity_notice_mismatch"


def test_complete_publication_reports_a_notice_that_differs_from_the_basis(tmp_path):
    model = pack.read(ROOT)
    if MISMATCH not in rules.load(model.rules).derived():
        raise MissingNoticeMismatch(f"no {MISMATCH} beside {BASIS}")
    target = prepare(tmp_path)
    current = state(target, private=False)
    platform, _, _ = snapshots(current, store.FileStore(tmp_path / "matching"), "platform", "complete")
    assert not any(r[0] == MISMATCH for r in platform)

    # The late notice overstates the free cores by one; the early notice still matches.
    _, cap, own, peer = PERIODS[1]
    free, used = cap - own - peer, own + peer
    path = target / "facts" / "public-decisions.yaml"
    notes = yaml.safe_load(path.read_text(encoding="utf-8"))
    late, = [note for note in notes["capacity_notice"] if note["period"] == "late"]
    late["free_cores"] = free + 1
    path.write_text(yaml.safe_dump(notes), encoding="utf-8")
    changed = batch.epoch(target, epoch=3, knowledge_time="2026-03-01T00:00:00Z",
                          sources=[("rules", "platform-proof-example")], evidence=capacity_evidence())
    platform, details, _ = snapshots(changed, store.FileStore(tmp_path / "differing"), "platform", "complete")
    finding = (MISMATCH, ("note-late", "late", str(free + 1), str(used), str(free), str(used)))
    assert {r for r in platform if r[0] == MISMATCH} == {finding}
    assert {("capacity_notice__free_cores", ("note-late", str(free + 1))),
            ("capacity_pool__cores", ("late", str(cap))),
            ("capacity_reading__cores", (f"{TENANT}-late", str(own))),
            ("capacity_reading__cores", (f"{PEER}-late", str(peer)))} <= leaves(details, finding)

    visible, _, files = snapshots(changed, store.FileStore(tmp_path / "tenant"), TENANT, "may_read")
    assert not any(r[0] in (MISMATCH, BASIS) for r in visible)
    assert all(PEER.encode() not in raw for raw in files.values())
