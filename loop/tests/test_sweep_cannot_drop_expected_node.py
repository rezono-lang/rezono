"""Compare a checked flow sweep with an independently retained two-node inventory."""
import pytest

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex
from round_visibility_publication import checked_loop_publication, observation_reference


def _receipt(scope, nodes, finals, retained):
    def source(position):
        return {"kind": "tool", "name": "inventory-observer", "position": position}

    artifacts = {
        "inventory": canonical_bytes([[node] for node in nodes]),
        "content": canonical_bytes([
            {"key": [node], "terminal": source(f"final/{node}"),
             "rows": [{"key": [final["id"]], "values": final, "source": source(final["id"])}]}
            for node, final in zip(nodes, finals, strict=True)
        ]),
    }
    body = {
        "source": source("flow-window/20"),
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
        **{name: observation_reference("submitted", name, data) for name, data in artifacts.items()},
    }
    receipt = canonical_bytes({"id": canonical_sha256(["rezono.completeness-receipt/1", body]), **body})
    return {
        **artifacts, "receipt": receipt,
        "admission": canonical_bytes({"completeness_receipts": [observation_reference("submitted", "receipt", receipt)]}),
    }


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/scoped-completeness.md sections 1 and 3. Verify the expected nodes "
        "against the independently pinned source inventory before publishing complete_sweep. "
        "Keep the interval, terminal reports, gap and loss requirements. Write in the Loop observation path. "
        "Blocked: the shortened case passes only the retained source name and digest to batch.epoch, which has "
        "no archive and no admitted receipt input, and publish.publish receives an Epoch whose rows are already derived, so no "
        "implementation path lets the pinned inventory reach complete_sweep. The planner must say how admission supplies verified_receipt."
    ),
)
def test_sweep_cannot_drop_expected_node(tmp_path):
    nodes = ("node-a", "node-b")
    scope = {"run": "run", "collector": "observer", "window": "flow-window"}
    expected = [dict(scope, id=f"inventory-{node}", node=node) for node in nodes]
    finals = [dict(scope, id=f"final-{node}", node=node, first=10, last=20, gaps=0, lost=0) for node in nodes]
    retained = {
        "flow-node-inventory": canonical_bytes([[node] for node in nodes]),
        "flow-node-finals": canonical_bytes(finals),
        "scope-definition": canonical_bytes({"query": "expected-sweep-nodes", "scope": scope, "bounds": [10, 20]}),
        "collector-authority": canonical_bytes({"issuer": "inventory-observer", "query": "expected-sweep-nodes"}),
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
    )
    assert rows("complete_sweep") == set(), (
        f"The published sweep trusts a shortened submission over the pinned two-node inventory: {rows('complete_sweep')}"
    )
