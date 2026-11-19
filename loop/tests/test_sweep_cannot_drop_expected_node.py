"""Compare a checked flow sweep with an independently retained two-node inventory."""
import pytest

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex
from round_visibility_publication import checked_loop_publication, observation_reference


def _source(position):
    return {"kind": "tool", "name": "inventory-observer", "position": position}


def _key(scope, node):
    """The trusted member key: tag, the bindings the rule joins on, then the node (admission-transport.md 6)."""
    return ["sweep-node", scope["run"], scope["collector"], scope["window"], node]


def _inventory(scope, nodes):
    return canonical_bytes([_key(scope, node) for node in nodes])


def _content(scope, nodes, finals):
    return canonical_bytes([
        {"key": _key(scope, node), "terminal": _source(f"final/{node}"),
         "rows": [{"key": [final["id"]], "values": final, "source": _source(final["id"])}]}
        for node, final in zip(nodes, finals, strict=True)
    ])


def _context(scope, retained):
    """The read binding that the protected caller pins, independent of any submitted candidate."""
    return {
        "source": _source("flow-window/20"),
        "issuer": {
            "id": "inventory-observer",
            "authorization": observation_reference("retained", "collector-authority", retained["collector-authority"]),
        },
        "scope": {
            "definition": observation_reference("retained", "scope-definition", retained["scope-definition"]),
            "query": "expected-sweep-nodes",
            "bindings": [{"name": name, "type": "string", "value": value} for name, value in scope.items()],
        },
        "cut": {"frontier": {"source_id": "inventory-observer", "position": "20"}},
    }


def _authority(scope, retained):
    return {**_context(scope, retained),
            "inventory": observation_reference("retained", "flow-node-inventory", retained["flow-node-inventory"]),
            "content": observation_reference("retained", "flow-node-content", retained["flow-node-content"])}


def _receipt(scope, nodes, finals, retained):
    artifacts = {"inventory": _inventory(scope, nodes), "content": _content(scope, nodes, finals)}
    body = {
        **_context(scope, retained),
        **{name: observation_reference("submitted", name, data) for name, data in artifacts.items()},
    }
    receipt = canonical_bytes({"id": canonical_sha256(["rezono.completeness-receipt/1", body]), **body})
    return {**artifacts, "receipt": receipt}


def _evidence(evidence, scope, retained):
    """The bodies of context.json and index.json (decisions/admission-transport.md section 3)."""
    return {"context": {"completeness": [_authority(scope, retained)]},
            "index": {"completeness_receipts": [observation_reference("submitted", "receipt", evidence["receipt"])]}}


def test_sweep_cannot_drop_expected_node(tmp_path):
    nodes = ("node-a", "node-b")
    scope = {"run": "run", "collector": "observer", "window": "flow-window"}
    expected = [dict(scope, id=f"inventory-{node}", node=node) for node in nodes]
    finals = [dict(scope, id=f"final-{node}", node=node, first=10, last=20, gaps=0, lost=0) for node in nodes]
    retained = {
        "flow-node-inventory": _inventory(scope, nodes),
        "flow-node-finals": canonical_bytes(finals),
        "scope-definition": canonical_bytes({"query": "expected-sweep-nodes", "scope": scope, "bounds": [10, 20]}),
        "collector-authority": canonical_bytes({"issuer": "inventory-observer", "query": "expected-sweep-nodes"}),
        "flow-node-content": _content(scope, nodes, finals),
    }
    records = {
        "flow_sweep_window": [dict(scope, id="sweep", start=10, stop=20)],
        "flow_expected_node": expected,
        "flow_node_report": finals,
    }
    completed = {("run", "observer", "flow-window", "sweep")}
    complete_evidence = _receipt(scope, nodes, finals, retained)
    manifest, rows, _ = checked_loop_publication(
        tmp_path / "full", records, retained=retained, submitted=complete_evidence,
        **_evidence(complete_evidence, scope, retained),
    )
    assert rows("complete_sweep") == completed
    assert {entry["source_id"]: entry["position"] for entry in manifest["sources"]} == {
        name: sha256_hex(body) for name, body in retained.items()
    }

    truncated = {**records, "flow_expected_node": expected[:1], "flow_node_report": finals[:1]}
    shortened_evidence = _receipt(scope, nodes[:1], finals[:1], retained)
    assert shortened_evidence["receipt"] != complete_evidence["receipt"]
    _, rows, _ = checked_loop_publication(
        tmp_path / "truncated", truncated, retained=retained, submitted=shortened_evidence,
        **_evidence(shortened_evidence, scope, retained),
    )
    assert rows("complete_sweep") == set(), (
        f"The published sweep trusts a shortened submission over the pinned two-node inventory: {rows('complete_sweep')}"
    )
