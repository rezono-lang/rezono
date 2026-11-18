import json
from pathlib import Path

import pytest

from query_fixture import check_relation


def test_keycloak_release():
    evidence = json.loads(Path(__file__).with_name("product-evidence.json").read_text())["keycloak"]
    fields = ['release', 'published', 'url', 'sha256']
    expected = [("keycloak", *(evidence[k] for k in fields))]
    check_relation("published_release", expected)
