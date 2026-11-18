import json
from pathlib import Path

import pytest

from query_fixture import check_relation


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='Add typed keycloak product inputs with source and digest and the generic published_release projection. Read decisions/platform-source-and-scenario-cases.md. Own schema, facts and rules modules named keycloak_release. Source: https://www.keycloak.org/2024/10/keycloak-2600-released')
def test_keycloak_release():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["keycloak"]
    fields = ['release', 'published', 'url', 'sha256']
    expected = [("keycloak", *(evidence[k] for k in fields))]
    check_relation("published_release", expected)
