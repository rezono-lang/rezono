"""Independent delivery-number checks at the tenant reference entry point."""

import json

import pytest

from tenant_oracle import HERE, calculate, load_requests


def delivery_numbers(requests):
    catalog = json.loads((HERE / "tenant-catalog.json").read_text(encoding="utf-8"))
    result = calculate(catalog, requests)
    return {(tenant, entry["metadata"]["name"]): key for tenant, key, entry in result["catalog"]}


@pytest.mark.parametrize(
    ("alpha", "zulu", "first", "second"),
    [
        ("00:00:00.1Z", "00:00:00Z", "zulu", "alpha"),
        ("00:00:00.13Z", "00:00:00.1Z", "zulu", "alpha"),
        ("00:00:00.000000002Z", "00:00:00.000000001Z", "zulu", "alpha"),
        ("00:00:00Z", "00:00:00.000Z", "alpha", "zulu"),
        ("00:00:00.1Z", "00:00:00.100Z", "alpha", "zulu"),
    ],
    ids=["whole-before-fraction", "different-precision", "submicrosecond", "zero-fraction", "fractional-tie"],
)
def test_files_number_each_tenant_by_exact_submission_time(tmp_path, alpha, zulu, first, second):
    for team, service, when in (("elm", "alpha", alpha), ("elm", "zulu", zulu),
                                ("reed", "studio", alpha)):
        path = tmp_path / team / service / "request.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "submittedAt": f"2026-01-02T{when}",
            "profile": "development",
            "items": {"cluster": "small"},
            "connections": [],
        }), encoding="utf-8")

    assert delivery_numbers(load_requests(tmp_path)) == {
        ("elm", first): "elm-1", ("elm", second): "elm-2", ("reed", "studio"): "reed-1",
    }


def test_direct_reference_breaks_ties_between_equivalent_offsets():
    request = {"team": "elm", "profile": "development", "items": {"cluster": "small"}, "connections": []}
    rows = [
        dict(request, service="zulu", submittedAt="2026-01-01T19:00:00.100-05:00"),
        dict(request, service="alpha", submittedAt="2026-01-02T00:00:00.1Z"),
    ]

    assert delivery_numbers(rows) == {("elm", "alpha"): "elm-1", ("elm", "zulu"): "elm-2"}
