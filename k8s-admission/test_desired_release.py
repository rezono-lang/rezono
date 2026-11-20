"""The same renderers supply both the reviewed release and its API-server oracle."""

from pathlib import Path

import pytest
import yaml
from checked_release_fixture import MANIFEST_KEY, publish_evidence


FIXTURES = Path(__file__).parent / "fixtures" / "server"


def test_desired_admission_release_reuses_both_rule_renderers(tmp_path):
    from admission_release import render_release
    from admission_translator import translate
    from bindings import render_binding
    from policy_renderer import render_policy
    from translator_support import fixture, load_program

    publication = yaml.safe_load((FIXTURES / "publication.yaml").read_text(encoding="utf-8"))
    namespaces = ["admission-blue", "admission-green"]
    digest = publication["spec"]["digest"]
    common = [publication, yaml.safe_load((FIXTURES.parents[1] / "resources" / "publication-crd.yaml")
                                          .read_text(encoding="utf-8"))]
    for ns in namespaces:
        common.append({"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "name": ns, "labels": {"rezono.dev/admission": "enabled"}}})
    for rule in ["verified-supply", "in-zone-flow"]:
        common.append(render_binding(rule=rule, digest=digest, parameter_name=publication["metadata"]["name"]))
    legacy = [render_policy(rule=rule, digest=digest) for rule in ["verified-supply", "in-zone-flow"]]
    translated = [translate(load_program(f"{rule}.rules.yaml"), fixture(f"{rule}.binding.yaml"), digest)
                  for rule in ["verified-supply", "in-zone-flow"]]
    store = publish_evidence(tmp_path)
    rendered = render_release(namespaces, [publication], store=store, manifest_key=MANIFEST_KEY)
    assert len(rendered) == len(common) + 2
    assert all(obj in rendered for obj in common)
    assert all(obj in rendered for obj in legacy) or all(obj in rendered for obj in translated)
    assert rendered == render_release(reversed(namespaces), [publication], store=store, manifest_key=MANIFEST_KEY)
