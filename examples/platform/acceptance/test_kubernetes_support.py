import json
from pathlib import Path

import pytest

from query_fixture import check_relation


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Add typed kubernetes product inputs with source and digest and the generic published_series_support projection. Read decisions/platform-source-and-scenario-cases.md. Own schema, facts and rules modules named kubernetes_support. Source: https://kubernetes.io/releases/1.32/')
def test_kubernetes_support():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["kubernetes"]
    fields = ['series', 'latestPatch', 'end', 'url', 'sha256']
    expected = [("kubernetes", *(evidence[k] for k in fields))]
    check_relation("published_series_support", expected)
