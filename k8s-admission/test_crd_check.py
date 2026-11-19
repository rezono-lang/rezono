"""The publication CRD declares exactly the lists that the admission bindings write.

See decisions/k8s-admission-binding-checks.md, "CRD check". The expectation is the CRD that part 1 wrote by
hand: it passes with both translator bindings. Each other case changes that CRD or the set of bindings in one
place; the expected problems follow by hand from the decision.
"""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

CRD = Path(__file__).parent.resolve() / "resources" / "publication-crd.yaml"


def pairs():
    from translator_support import fixture, load_program

    return [(fixture(f"{rule}.binding.yaml"), load_program(f"{rule}.rules.yaml"))
            for rule in ("verified-supply", "in-zone-flow")]


def spec(crd):
    return crd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]["properties"]["spec"]


def field(crd, name):
    return spec(crd)["properties"][name]


def items(crd, name):
    return field(crd, name)["items"]


def older_version_first(crd):
    older = deepcopy(crd["spec"]["versions"][0])
    older.update(name="v1alpha0", storage=False)
    del older["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]["images"]
    crd["spec"]["versions"].insert(0, older)


# (case, change of the CRD, expected problems in sorted order)
CASES = [
    ("digest optional", lambda c: spec(c)["required"].remove("digest"), [("digest", "digest")]),
    ("digest of any hex length", lambda c: field(c, "digest").update(pattern="^[0-9a-f]+$"), [("digest", "digest")]),
    ("transport list missing", lambda c: spec(c)["properties"].pop("transportFlows"),
     [("field_missing", "transportFlows")]),
    ("unwritten list", lambda c: spec(c)["properties"].update(zones=deepcopy(field(c, "flows"))),
     [("field_unwritten", "zones")]),
    ("atomic list", lambda c: field(c, "flows").update({"x-kubernetes-list-type": "atomic"}),
     [("list_shape", "flows")]),
    ("unbounded list", lambda c: field(c, "images").pop("maxItems"), [("list_shape", "images")]),
    ("keys in another order", lambda c: field(c, "flows").update(
        {"x-kubernetes-list-map-keys": ["destination", "source", "port"]}), [("list_keys", "flows")]),
    ("protocol not a key", lambda c: field(c, "transportFlows").update(
        {"x-kubernetes-list-map-keys": ["source", "destination", "port"]}), [("list_keys", "transportFlows")]),
    ("extra item property", lambda c: items(c, "images")["properties"].update(tag={"type": "string"}),
     [("item_columns", "images")]),
    ("item column not required", lambda c: items(c, "images").update(required=["image"]),
     [("item_columns", "images")]),
    ("port as text", lambda c: items(c, "flows")["properties"]["port"].update(type="string"),
     [("item_type", "flows/port")]),
    ("optional list required", lambda c: spec(c)["required"].append("transportFlows"),
     [("required", "transportFlows")]),
    ("required list optional", lambda c: spec(c)["required"].remove("images"), [("required", "images")]),
    ("only the storage version counts", older_version_first, []),
]


@pytest.mark.xfail(
    strict=True,
    reason="extra: Write crd_check.check_crd as decisions/k8s-admission-binding-checks.md specifies under CRD check. "
           "Write in k8s-admission/crd_check.py.",
)
def test_crd_check():
    from crd_check import check_crd

    original = yaml.safe_load(CRD.read_text(encoding="utf-8"))
    assert check_crd(original, pairs()) == []

    for case, change, expected in CASES:
        crd = deepcopy(original)
        change(crd)
        assert check_crd(crd, pairs()) == expected, case

    supply_only = pairs()[:1]
    assert check_crd(original, supply_only) == [("field_unwritten", "flows"), ("field_unwritten", "transportFlows")]

    second = deepcopy(pairs()[1][0])
    second["rule"] = "in-zone-flow-copy"
    assert check_crd(original, [*pairs(), (second, pairs()[1][1])]) == [
        ("field_shared", "flows"), ("field_shared", "transportFlows")]
    assert original == yaml.safe_load(CRD.read_text(encoding="utf-8"))
