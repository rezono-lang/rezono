"""Read the reference registry's selected release and licence from published catalogue bytes."""

import json
import shutil

import yaml

from case_support import ROOT
from test_product_licence import publication, referenced_json, snapshot


RELEASE = "distribution-3.0.0"
URL = "https://raw.githubusercontent.com/distribution/distribution/v3.0.0/LICENSE"
DIGEST = "cb5e8e7e5f4a3988e1063c142c60dc2df75605f4c46515e776e3aca6df976e14"
FIRST_LINE_DIGEST = "15ef3a45b062d92684bcdd84d53f8e1120101dd6294ab9af94c5338bf5b5065f"


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
        assert (RELEASE, "3.0.0") in snapshot(result, "release__version", role)

    bucket, manifest = result
    source_index, = [s for s in manifest["fact_sources"] if s["role"] == "platform-catalogue"]
    entry, = [item for item in referenced_json(bucket, source_index)
              if item["row"]["relation"] == "vendor_licence_notice__declaration"
              and json.loads(item["row"]["key"]) == [RELEASE, "Apache-2.0"]]
    source, = entry["sources"]
    assert (source["kind"], source["revision"], source["url"], source["fragment_sha256"]) == (
        "tool", "3.0.0", URL, FIRST_LINE_DIGEST)


def test_registry_notice_with_a_different_release_or_without_a_selection(tmp_path):
    pack = tmp_path / "examples" / "platform"
    shutil.copytree(ROOT, pack)
    shutil.copytree(ROOT.parents[1] / "packs", tmp_path / "packs")
    # Suppress the newest-stable fallback so the service without a pin has no selection.
    core_path = pack / "facts" / "core.yaml"
    core = yaml.safe_load(core_path.read_text(encoding="utf-8"))
    selected, = [release for release in core["release"] if release["id"] == RELEASE]
    selected["stable"] = "no"
    core_path.write_text(yaml.safe_dump(core), encoding="utf-8")
    extra = {
        "service": [{"id": service, "product": "registry", "role": "shared", "step": 1}
                    for service in ("reg-other", "reg-unselected")],
        "release": [{"id": "registry-other", "product": "registry", "released_on_day": 1,
                     "stable": "no", "version": "2.0.0"}],
        "product_release_source": [{"id": "registry-other-release-source", "product": "registry", "version": "2.0.0",
                                    "published": "2024-01-01",
                                    "source_url": "https://vendor.example.org/releases/registry-2.0.0",
                                    "source_sha256": "0" * 64}],
        "pin": [{"id": "reg-other-pin", "service": "reg-other", "release": "registry-other"}],
        "licence_release_binding": [{"id": "mismatched-registry-notice", "selected_release": "registry-other",
                                    "notice": RELEASE, "basis": "exact-scenario-release"}],
    }
    (pack / "facts" / "registry-other.yaml").write_text(yaml.safe_dump(extra), encoding="utf-8")
    result = publication(pack, tmp_path / "published")
    for role in ("platform-catalogue", "checker"):
        states = snapshot(result, "component_licence_state", role)
        rows = snapshot(result, "component_product_licence", role)
        assert {row for row in states if row[0] in ("reg-other", "reg-unselected")} == {
            ("reg-other", "registry", "unknown-selected-release"),
            ("reg-unselected", "registry", "reference-source-release")}
        assert {row for row in rows if row[0] in ("reg-other", "reg-unselected")} == {
            ("reg-unselected", "registry", "3.0.0", "reference-source-release", "project-source",
             "Apache-2.0", URL, DIGEST)}
