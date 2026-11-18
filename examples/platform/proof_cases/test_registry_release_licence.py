"""Read the reference registry's selected release and licence from published catalogue bytes."""

import json
import shutil

import pytest
import yaml

from case_support import ROOT
from test_product_licence import publication, referenced_json, snapshot


RELEASE = "distribution-3.0.0"
URL = "https://raw.githubusercontent.com/distribution/distribution/v3.0.0/LICENSE"
DIGEST = "cb5e8e7e5f4a3988e1063c142c60dc2df75605f4c46515e776e3aca6df976e14"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Provide the Distribution v3.0.0 release, registry service pin, licence notice, provenance sidecar "
    "and exact release binding under examples/platform/facts. Read decisions/platform-registry-reference.md."
))
def test_registry_selects_a_sourced_distribution_release(tmp_path):
    result = publication(ROOT, tmp_path / "published")
    expected = ("reg", "registry", "3.0.0", "exact-scenario-release", "project-source", "Apache-2.0", URL, DIGEST)
    for role in ("platform-catalogue", "checker"):
        rows = snapshot(result, "component_product_licence", role)
        assert {row for row in rows if row[0] == "reg"} == {expected}
        assert {row for row in snapshot(result, "component_licence_state", role) if row[0] == "reg"} == {
            ("reg", "registry", "exact-scenario-release")}
        pins = {key for key, service in snapshot(result, "pin__service", role) if service == "reg"}
        assert {r for key, r in snapshot(result, "pin__release", role) if key in pins} == {RELEASE}
        assert (RELEASE, "registry") in snapshot(result, "release__product", role)

    bucket, manifest = result
    source_index, = [s for s in manifest["fact_sources"] if s["role"] == "platform-catalogue"]
    notices = {key for key, address in snapshot(result, "vendor_licence_notice__source_url") if address == URL}
    sources = [s for entry in referenced_json(bucket, source_index)
               if entry["row"]["relation"] == "vendor_licence_notice__declaration"
               and json.loads(entry["row"]["key"]) in [[n, "Apache-2.0"] for n in notices]
               for s in entry["sources"]]
    assert {(s["kind"], s["revision"], s["url"]) for s in sources} == {("tool", "3.0.0", URL)}


def test_another_selected_registry_release_needs_its_own_notice(tmp_path):
    pack = tmp_path / "examples" / "platform"
    shutil.copytree(ROOT, pack)
    shutil.copytree(ROOT.parents[1] / "packs", tmp_path / "packs")
    extra = {
        "service": [{"id": "reg-other", "product": "registry", "role": "shared", "step": 1}],
        "release": [{"id": "registry-other", "product": "registry", "released_on_day": 1, "stable": "no"}],
        "pin": [{"id": "reg-other-pin", "service": "reg-other", "release": "registry-other"}],
    }
    (pack / "facts" / "registry-other.yaml").write_text(yaml.safe_dump(extra), encoding="utf-8")
    result = publication(pack, tmp_path / "published")
    states = snapshot(result, "component_licence_state")
    assert {row for row in states if row[0] == "reg-other"} == {("reg-other", "registry", "unknown-selected-release")}
    assert not any(row[0] == "reg-other" for row in snapshot(result, "component_product_licence"))
