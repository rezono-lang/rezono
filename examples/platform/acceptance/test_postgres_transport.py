import json
from pathlib import Path

import pytest

from query_fixture import check_relation


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Add typed postgresql product inputs with source and digest and the generic published_default_transport projection. Read decisions/platform-source-and-scenario-cases.md. Own schema, facts and rules modules named postgres_transport. Source: https://www.postgresql.org/docs/17/runtime-config-connection.html')
def test_postgres_transport():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["postgresql"]
    fields = ['series', 'protocol', 'port', 'url', 'sha256']
    expected = [("postgresql", *(evidence[k] for k in fields))]
    check_relation("published_default_transport", expected)
