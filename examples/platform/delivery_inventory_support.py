"""Independent expectations and genuine request-file changes for delivery inventory."""

import json

from request_preview_case import preview
from tenant_oracle import calculate, load_requests


def expected(teams, catalog):
    return calculate(json.loads(catalog.read_text()), load_requests(teams))


def delivery_id(key):
    owner, ordinal = key.rsplit("-", 1)
    return owner, int(ordinal)


def add_service(teams):
    request = json.loads((teams / "elm/ledger/request.json").read_text())
    request.update(items={"cluster": "medium"}, connections=[], submittedAt="2026-01-04T00:00:00Z")
    path = teams / "elm/archive/request.json"
    path.parent.mkdir()
    path.write_text(json.dumps(request))


def exact(teams, catalog, relation, expected_rows):
    try:
        actual = preview(teams, catalog, "relation", relation)
    except AssertionError as error:
        # An unrelated compiler, import or input failure must fail CI even under xfail.
        if f"unknown derived relation {relation!r}" in str(error):
            raise
        raise RuntimeError(f"Could not evaluate {relation}: {error}") from error
    assert actual == sorted(expected_rows), relation
