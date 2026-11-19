"""An admission binding is typed: its schema rejects every unknown field and every malformed value.

See decisions/k8s-admission-binding-checks.md, "Schema". Each rejected document differs from a checked-in
binding in one place, chosen by hand from the rules that decision states.
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.resolve()
FIXTURES = ROOT / "fixtures" / "translator"
SCHEMA = ROOT / "resources" / "admission-binding.schema.json"


def text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def flow():
    return yaml.safe_load(text("in-zone-flow.binding.yaml"))


def changed(change):
    doc = flow()
    change(doc)
    return yaml.safe_dump(doc, sort_keys=False)


def ingress(doc):
    return doc["request"][0]


def flows(doc):
    return doc["parameters"]["published_flow"]["lists"][0]


# (case, change, a key the error message must name, or None)
REJECTED = [
    ("unknown top-level field", lambda d: d.update(extra=1), "extra"),
    ("other format", lambda d: d.update(format="rezono.admission-binding/2"), None),
    ("rule with capitals", lambda d: d.update(rule="In-Zone-Flow"), None),
    ("rule with a space", lambda d: d.update(rule="in zone flow"), None),
    ("empty output", lambda d: d.update(output=""), None),
    ("no parameters", lambda d: d.pop("parameters"), "parameters"),
    ("no match", lambda d: d.update(match=[]), None),
    ("delete has no object", lambda d: d["match"][0].update(operations=["CREATE", "DELETE"]), None),
    ("cluster scope", lambda d: d["match"][0].update(scope="Cluster"), None),
    ("unknown match field", lambda d: d["match"][0].update(namespaceSelector={}), "namespaceSelector"),
    ("match without resources", lambda d: d["match"][0].pop("resources"), "resources"),
    ("no request source", lambda d: d.update(request=[]), None),
    ("source without columns", lambda d: ingress(d).update(columns={}), None),
    ("unknown source field", lambda d: ingress(d).update(where=[]), "where"),
    ("unknown iterator field", lambda d: ingress(d)["each"][0].update(filter="x"), "filter"),
    ("iterator path of one element", lambda d: ingress(d)["each"][0].update(path=["object"]), None),
    ("iterator name with a dash", lambda d: ingress(d)["each"][0].update(name="a-rule"), None),
    ("empty closed list", lambda d: ingress(d)["each"][0].update(closed=[]), None),
    ("repeated closed key", lambda d: ingress(d)["each"][0].update(closed=["from", "from"]), None),
    ("optional as text", lambda d: ingress(d)["each"][0].update(optional="yes"), None),
    ("unknown reading", lambda d: ingress(d)["columns"]["port"].update(reading="quantity"), None),
    ("end without reading", lambda d: ingress(d)["columns"]["port"].pop("reading"), None),
    ("boolean default", lambda d: ingress(d)["columns"]["protocol"].update(default=True), None),
    ("unknown column field", lambda d: ingress(d)["columns"]["protocol"].update(cast="upper"), "cast"),
    ("column path with an empty key", lambda d: ingress(d)["columns"]["protocol"].update(path=["port", ""]), None),
    ("reserved field", lambda d: flows(d).update(field="digest"), None),
    ("field with a dash", lambda d: flows(d).update(field="flow-list"), None),
    ("no written columns", lambda d: flows(d).update(columns=[]), None),
    ("boolean fixed value", lambda d: flows(d).update(fixed={"protocol": False}), None),
    ("unknown list field", lambda d: flows(d).update(sort="port"), "sort"),
    ("relation without scope", lambda d: d["parameters"]["published_flow"].pop("scope"), "scope"),
    ("relation without lists", lambda d: d["parameters"]["published_flow"].update(lists=[]), None),
]


@pytest.mark.xfail(
    strict=True,
    reason="Write admission_binding.load_binding and the binding schema as decisions/k8s-admission-binding-checks.md "
           "specifies under Schema. Write in k8s-admission/admission_binding.py and "
           "k8s-admission/resources/admission-binding.schema.json.",
)
def test_binding_schema():
    import jsonschema
    from admission_binding import load_binding

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)

    def closed_objects(node):
        if isinstance(node, dict):
            if "properties" in node:
                assert node.get("additionalProperties") is False, sorted(node["properties"])
            for value in node.values():
                closed_objects(value)
        elif isinstance(node, list):
            for value in node:
                closed_objects(value)

    closed_objects(schema)

    for name in ("verified-supply.binding.yaml", "in-zone-flow.binding.yaml"):
        assert load_binding(text(name)) == yaml.safe_load(text(name))

    smallest = {
        "format": "rezono.admission-binding/1", "rule": "r", "output": "allow",
        "match": [{"apiGroups": [""], "apiVersions": ["v1"], "operations": ["UPDATE"],
                   "resources": ["configmaps"], "scope": "Namespaced"}],
        "request": [{"relation": "seen", "each": [], "columns": {"name": {"path": ["object", "metadata"]}}}],
        "parameters": {},
    }
    assert load_binding(yaml.safe_dump(smallest)) == smallest
    allowed = deepcopy(smallest)
    allowed["request"][0]["columns"]["name"].update(default=0)
    assert load_binding(yaml.safe_dump(allowed)) == allowed

    for case, change, key in REJECTED:
        with pytest.raises(ValueError) as refused:
            load_binding(changed(change))
        if key is not None:
            assert key in str(refused.value), case

    for broken in ("format: [", "- format: rezono.admission-binding/1\n", "plain text\n"):
        with pytest.raises(ValueError):
            load_binding(broken)
