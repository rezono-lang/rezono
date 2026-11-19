"""Model rows become NamespacePublication lists through the binding's parameters.

See decisions/k8s-admission-translator.md, "Parameters". The expected publication is the hand-written
fixtures/server/publication.yaml of part 1, and hand-sorted entries per decisions/k8s-admission-publication.md.
"""

import copy

import pytest
import yaml
from translator_support import FIXTURES, IMAGE_A, IMAGE_B, fixture, load_program


@pytest.mark.xfail(
    strict=True,
    reason="M4: Write parameter_projection.project_parameters as decisions/k8s-admission-translator.md specifies under "
           "Parameters. Write in k8s-admission/parameter_projection.py.",
)
def test_parameter_projection():
    from parameter_projection import project_parameters

    supply_binding, supply = fixture("verified-supply.binding.yaml"), load_program("verified-supply.rules.yaml")
    flow_binding, flow = fixture("in-zone-flow.binding.yaml"), load_program("in-zone-flow.rules.yaml")
    managed = ["admission-blue", "admission-green"]

    images = project_parameters(supply_binding, supply, {"verified_image": {("admission-blue", "web", IMAGE_A)}},
                                managed)
    flows = project_parameters(flow_binding, flow,
                               {"published_flow": {("admission-blue", "reader", "web", "TCP", 443)}}, managed)
    assert images["admission-green"] == {"images": []}
    assert flows["admission-green"] == {"flows": []}
    published = yaml.safe_load((FIXTURES.parent / "server" / "publication.yaml").read_text(encoding="utf-8"))
    assert {"digest": published["spec"]["digest"], **images["admission-blue"], **flows["admission-blue"]} == \
        published["spec"]

    rows = [
        ("blue", "reader", "web", "TCP", 10), ("blue", "reader", "web", "TCP", 9), ("blue", "probe", "web", "TCP", 443),
        ("blue", "idp", "dns", "UDP", 53), ("blue", "idp", "dns", "SCTP", 53), ("blue", "reader", "web", "TCP", 9),
    ]
    assert project_parameters(flow_binding, flow, {"published_flow": rows}, ["blue"]) == {"blue": {
        "flows": [
            {"source": "probe", "destination": "web", "port": 443},
            {"source": "reader", "destination": "web", "port": 9},
            {"source": "reader", "destination": "web", "port": 10},
        ],
        "transportFlows": [
            {"source": "idp", "destination": "dns", "protocol": "SCTP", "port": 53},
            {"source": "idp", "destination": "dns", "protocol": "UDP", "port": 53},
        ],
    }}
    assert project_parameters(supply_binding, supply, {"verified_image": [
        ("blue", "web", IMAGE_B), ("blue", "api", IMAGE_B), ("blue", "web", IMAGE_A),
    ]}, ["blue"]) == {"blue": {"images": [
        {"service": "api", "image": IMAGE_B}, {"service": "web", "image": IMAGE_A}, {"service": "web", "image": IMAGE_B},
    ]}}

    with pytest.raises(ValueError):
        project_parameters(supply_binding, supply, {"verified_image": [("other", "web", IMAGE_A)]}, ["blue"])
    tcp_only = copy.deepcopy(flow_binding)
    tcp_only["parameters"]["published_flow"]["lists"] = tcp_only["parameters"]["published_flow"]["lists"][:1]
    with pytest.raises(ValueError):
        project_parameters(tcp_only, flow, {"published_flow": [("blue", "idp", "dns", "UDP", 53)]}, ["blue"])
