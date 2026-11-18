"""The four expected positions follow the platform request-order decision."""

import json

import pytest

from request_preview import preview_inputs, relation_rows
from request_preview_case import ROOT, preview
from rezono_compiler import pack


REQUESTS = (
    ("reed/zulu", "00Z"),
    ("elm/alpha", "00.0000001Z"),
    ("elm/zulu", "00.000000100Z"),
    ("reed/alpha", "00.00000010Z"),
)
EXPECTED = {"reed/zulu": 1, "elm/alpha": 2, "elm/zulu": 3, "reed/alpha": 4}


class MissingGlobalRequestOrdinal(AssertionError):
    pass


def assert_ordinals(rows, expected):
    assert all(type(ordinal) is int for _, ordinal in rows)
    assert sorted(map(tuple, rows)) == sorted(expected.items())


def test_global_request_ordinals_use_exact_time_tenant_and_service(tmp_path):
    teams = tmp_path / "teams"
    for request, second in reversed(REQUESTS):
        path = teams / request / "request.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "profile": "development", "items": {"cluster": "small"}, "connections": [],
            "submittedAt": "2026-01-02T00:00:" + second,
        }), encoding="utf-8")
    catalog = ROOT / "tenant-catalog.json"
    try:
        rows = preview(teams, catalog, "relation", "request_ordinal")
    except AssertionError as error:
        if "unknown derived relation 'request_ordinal'" not in str(error):
            raise
        raise MissingGlobalRequestOrdinal("the preview lacks request_ordinal") from error
    assert_ordinals(rows, EXPECTED)

    settings = json.loads(catalog.read_text(encoding="utf-8"))
    settings["landedDeliveries"] = [{"request": "elm/zulu", "revision": "a" * 40,
                                     "cores": 2, "memoryGiB": 4, "storageGiB": 20}]
    with_receipt = tmp_path / "catalog.json"
    with_receipt.write_text(json.dumps(settings), encoding="utf-8")
    model = pack.read(ROOT)
    inputs = preview_inputs(model, ROOT, teams, with_receipt)
    assert_ordinals(relation_rows(model, inputs, "request_ordinal"), EXPECTED)
    reversed_inputs = {name: list(reversed(records)) for name, records in inputs.items()}
    assert_ordinals(relation_rows(model, reversed_inputs, "request_ordinal"), EXPECTED)

    # Keep the other ordering facts and any precomputed field keys for the same request.
    for relation in ("tenant_service_request", "tenant_service_request__submitted_at",
                     "tenant_service_request__tenant", "tenant_service_request__service"):
        replacement = [row for row in inputs[relation] if row[0] != "elm/alpha"]
        assert len(replacement) == len(inputs[relation]) - 1
        surviving = relation_rows(model, inputs | {relation: replacement}, "request_ordinal")
        assert_ordinals(surviving, {"reed/zulu": 1, "elm/zulu": 2, "reed/alpha": 3})

    path = teams / "reed/zulu/request.json"
    changed = json.loads(path.read_text(encoding="utf-8"))
    changed["submittedAt"] = "2026-01-02T00:00:00.0000002Z"
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert_ordinals(preview(teams, with_receipt, "relation", "request_ordinal"),
                    {"elm/alpha": 1, "elm/zulu": 2, "reed/alpha": 3, "reed/zulu": 4})
