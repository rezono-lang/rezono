"""The same renderers supply both the reviewed release and its API-server oracle."""

from pathlib import Path

import pytest
import yaml
from checked_release_fixture import MANIFEST_KEY, publish_evidence


FIXTURES = Path(__file__).parent / "fixtures" / "server"


def test_desired_admission_release_reuses_both_rule_renderers(tmp_path):
    from admission_release import render_release
    from bindings import render_binding
    from policy_renderer import render_policy

    publication = yaml.safe_load((FIXTURES / "publication.yaml").read_text(encoding="utf-8"))
    namespaces = ["admission-blue", "admission-green"]
    wanted = [publication, yaml.safe_load((FIXTURES.parents[1] / "resources" / "publication-crd.yaml")
                                         .read_text(encoding="utf-8"))]
    for ns in namespaces:
        wanted.append({"apiVersion": "v1", "kind": "Namespace", "metadata": {
            "name": ns, "labels": {"rezono.dev/admission": "enabled"}}})
    for rule in ["verified-supply", "in-zone-flow"]:
        digest = publication["spec"]["digest"]
        wanted.append(render_policy(rule=rule, digest=digest))
        wanted.append(render_binding(rule=rule, digest=digest, parameter_name=publication["metadata"]["name"]))
    store = publish_evidence(tmp_path)
    rendered = render_release(namespaces, [publication], store=store, manifest_key=MANIFEST_KEY)
    assert len(rendered) == len(wanted)
    assert all(obj in rendered for obj in wanted)
    assert rendered == render_release(reversed(namespaces), [publication], store=store, manifest_key=MANIFEST_KEY)
