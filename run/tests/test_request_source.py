import pytest

from offline_cases import FIXTURE, case, implementation


def test_request_source():
    load = implementation("request_source.py", "load_request")
    raw = (FIXTURE / "request.json").read_bytes()
    digest = case()["request_sha256"]
    provenance = {"repository": "sample/requests", "commit": "c" * 40, "path": "requests/sample.json"}
    value = load(raw, provenance, digest)
    assert value == {"request": {"id": "sample", "service": "sample-service"},
                     "source": {**provenance, "sha256": digest}}
    with pytest.raises(ValueError):
        load(raw + b" ", provenance, digest)
    with pytest.raises(ValueError):
        load(raw, dict(provenance, commit="main"), digest)
