"""An untrusted archive must not confer source completeness."""

from copy import deepcopy

import pytest

from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_checker.check import check_epoch
from rezono_checker.rules import load_rules
from rezono_publisher import store
from rezono_publisher.views import key_of


SOURCE = {"kind": "query", "name": "example-register", "revision": "snapshot-17",
          "position": "/enumeration"}
MEMBERS = [["partition-a"], ["partition-b"]]


class UnverifiedReceiptAccepted(AssertionError):
    """The ordinary checker treated a claimed admission row as authority."""


def pin(bucket, name, body):
    data = canonical_bytes(body)
    digest = sha256_hex(data)
    key = f"archive/{digest}.json"
    bucket.put_new(key, data)
    return {"file": name, "uri": bucket.uri(key), "sha256": digest}


def captured():
    return [
        {"key": ["partition-a"], "terminal": {**SOURCE, "position": "/partitions/a/end"}, "rows": [
            {"key": ["a-one"], "values": {"count": {"state": "known", "value": "3"}},
             "source": {**SOURCE, "position": "/partitions/a/rows/0"}},
            {"key": ["a-two"], "values": {"count": {"state": "known", "value": "7"}},
             "source": {**SOURCE, "position": "/partitions/a/rows/1"}},
        ]},
        {"key": ["partition-b"], "terminal": {**SOURCE, "position": "/partitions/b/end"}, "rows": []},
    ]


def relation(name, role, columns):
    return {"name": name, "role": role, "world": "closed",
            "key": [{"name": column, "type": "string"} for column in columns]}


def asserted_complete(bucket, evidence, source, scope, cut, inventory, content, *, trusted_relation=False,
                      authority=()):
    # Same ordinary proof shape for a valid positive past read or a purported admission.
    base = "recorded_read" if trusted_relation else "verified_receipt"
    result = "recorded_scope" if trusted_relation else "complete"
    values = [evidence["id"], source, scope, cut, inventory, content]
    result_values = [source, scope, cut, evidence["id"]]
    document = {"format": "rezono.rules/1", "pack": "example", "relations": [
        relation(base, "base", ("receipt", "source", "scope", "cut", "inventory", "content")),
        relation(result, "derived", ("source", "scope", "cut", "receipt")),
    ], "rules": [{
        "id": result, "stratum": "0", "head": {"relation": result, "terms": result_values},
        "body": [{"relation": base, "terms": values, "polarity": "positive", "stratum": "0"}],
    }]}
    witness = {"rule_id": result, "bindings": [],
               "conclusion": {"relation": result, "key": canonical_json(result_values)},
               "premises": [{"row": {"relation": base, "key": canonical_json(values)},
                             "polarity": "positive", "stratum": 0}]}
    snapshots = [
        pin(bucket, name, [{"key": key}]) | {"relation": name, "complete": True, "role": "checker", "format": "json"}
        for name, key in ((base, values), (result, result_values))
    ]
    manifest = {"id": "m-1", "snapshots": snapshots}
    if not trusted_relation:
        manifest["completeness_receipts"] = [pin(bucket, "receipt.json", evidence)]
    return check_epoch([witness], manifest, load_rules(document), lambda uri: bucket.get(key_of(uri)),
                       derived={result}, completeness_authority=authority)


def test_completeness_receipt_exact_inventory(tmp_path):
    bucket = store.FileStore(tmp_path / "archive")
    expected = captured()
    trusted_inventory = pin(bucket, "expected-members.json", MEMBERS)
    trusted_content = pin(bucket, "captured-content.json", expected)
    definition = pin(bucket, "scope-definition.json", {"query": "partitions", "binding": "register"})
    authorization = pin(bucket, "authorized-issuer.json", {
        "issuer": "reader", "source": SOURCE, "scope": definition,
    })
    scope = {"definition": definition, "query": "partitions", "bindings": [
        {"name": "register", "type": "Text", "value": "example-register"},
    ]}
    # The scope digest names its definition by the hash of the bytes it pins, not by where a copy is stored.
    scope_digest = canonical_sha256({**scope, "definition": definition["sha256"]})
    cut = {"frontier": {"source_id": "example-register", "position": "snapshot-17"}}
    initial = {"source": SOURCE, "issuer": {"id": "reader", "authorization": authorization},
               "scope": scope, "cut": cut, "inventory": trusted_inventory, "content": trusted_content}
    first = initial | {"id": canonical_sha256(["rezono.completeness-receipt/1", initial])}
    assert asserted_complete(
        bucket, first, SOURCE["name"], scope_digest, canonical_sha256(cut),
        trusted_inventory["sha256"], trusted_content["sha256"], trusted_relation=True,
    )["valid"]

    substitution = deepcopy(expected)
    substitution[1] = {"key": ["partition-c"], "terminal": {**SOURCE, "position": "/partitions/c/end"}, "rows": []}
    assert len(substitution) == len(MEMBERS) and [member["key"] for member in substitution] != MEMBERS
    dropped = deepcopy(expected)
    dropped[0]["rows"].pop()
    assert [member["key"] for member in dropped] == MEMBERS
    assert pin(bucket, "retry.json", sorted(reversed(expected), key=lambda member: member["key"]))["sha256"] == (
        trusted_content["sha256"]
    )
    empty = pin(bucket, "empty.json", [])
    assert empty["sha256"] != trusted_inventory["sha256"]

    # The trusted context is the protected caller's: the exact read is admitted against it, and each mutation
    # below is refused for its own reason, not for a missing authority.
    authority = [initial]
    admitted = asserted_complete(bucket, first, SOURCE["name"], scope_digest, canonical_sha256(cut),
                                 trusted_inventory["sha256"], trusted_content["sha256"], authority=authority)
    assert admitted == {**admitted, "valid": True, "findings": []}, admitted["findings"]
    unauthorized = asserted_complete(bucket, first, SOURCE["name"], scope_digest, canonical_sha256(cut),
                                     trusted_inventory["sha256"], trusted_content["sha256"])
    assert not unauthorized["valid"]

    accepted, misread = set(), {}
    for name, change, code in (
        ("member substitution", {"content": pin(bucket, "substituted.json", substitution)}, "receipt_member_mismatch"),
        ("row dropped within member", {"content": pin(bucket, "truncated.json", dropped)}, "receipt_content_mismatch"),
        ("wrong cut", {"cut": {"frontier": {"source_id": "example-register", "position": "snapshot-18"}}},
         "receipt_cut_mismatch"),
        ("unauthorized issuer", {"issuer": {"id": "unrelated-reader", "authorization": authorization}},
         "receipt_issuer_unauthorized"),
        ("unattested empty inventory", {"inventory": empty, "content": empty}, "receipt_inventory_mismatch"),
    ):
        body = initial | change
        receipt = body | {"id": canonical_sha256(["rezono.completeness-receipt/1", body])}
        checked = asserted_complete(bucket, receipt, SOURCE["name"], scope_digest,
                                    canonical_sha256(body["cut"]), body["inventory"]["sha256"],
                                    body["content"]["sha256"], authority=authority)
        if checked["valid"]:
            accepted.add(name)
        details = [f.get("detail", "") for f in checked["findings"] if f["reason"] == "receipt_unverified"]
        if not any(f": {code}:" in detail for detail in details):
            misread[name] = details
    if accepted:
        raise UnverifiedReceiptAccepted(f"checker accepted {', '.join(sorted(accepted))}")
    assert not misread, misread
