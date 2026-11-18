import json
from pathlib import Path

import pytest

from query_fixture import check_relation


def test_postgres_transport():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["postgresql"]
    fields = ['series', 'protocol', 'port', 'url', 'sha256']
    expected = [("postgresql", *(evidence[k] for k in fields))]
    check_relation("published_default_transport", expected)
