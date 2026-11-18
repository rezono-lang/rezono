import json
from pathlib import Path

import pytest

from query_fixture import check_relation


def test_kubernetes_support():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["kubernetes"]
    fields = ['series', 'latestPatch', 'end', 'url', 'sha256']
    expected = [("kubernetes", *(evidence[k] for k in fields))]
    check_relation("published_series_support", expected)
