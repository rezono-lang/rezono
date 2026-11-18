"""The wire resource selected by the scenario is also the preflight input."""

from pathlib import Path

import jsonschema
import yaml


ROOT = Path(__file__).parent


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def wire_case():
    case = load(ROOT / "fixtures" / "flow-namespace-cases.yaml")
    name, = case["publications"]
    resource = load(ROOT / "fixtures" / name)
    crd = load(ROOT / "resources" / "publication-crd.yaml")["spec"]
    version, = [v for v in crd["versions"] if v["served"] and v["storage"]]
    assert crd["scope"] == "Namespaced"
    assert crd["names"]["plural"] == "namespacepublications"
    identity = {"apiVersion": crd["group"] + "/" + version["name"], "kind": crd["names"]["kind"]}
    assert identity == {"apiVersion": "admission.rezono.org/v1alpha1", "kind": "NamespacePublication"}
    assert {key: resource[key] for key in identity} == identity
    jsonschema.Draft4Validator(version["schema"]["openAPIV3Schema"]).validate(resource)
    return resource, identity
