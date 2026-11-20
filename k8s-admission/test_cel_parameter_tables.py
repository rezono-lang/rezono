"""Model relations are read back from a NamespacePublication inside CEL.

See decisions/k8s-admission-translator.md, "Parameter table", and the bindings in fixtures/translator/.
"""

import json

import pytest
from translator_support import IMAGE_A, IMAGE_B, fixture, load_program, run_cel

SUPPLY_LIST = 'params.spec.images.map(x, {"service": x.service, "image": x.image})'
FLOW_LIST = (
    '(params.spec.flows.map(x, {"source": x.source, "destination": x.destination, "protocol": "TCP", "port": x.port})'
    ' + (has(params.spec.transportFlows) ? params.spec.transportFlows : [])'
    '.map(x, {"source": x.source, "destination": x.destination, "protocol": x.protocol, "port": x.port}))'
)


def same_rows(table, expected):
    columns = ", ".join(f'"{name}": {template.replace("{e}", "e")}' for name, template in table["columns"].items())
    mapped = f"{table['list']}.map(e, {{{columns}}})"
    literal = json.dumps(expected)
    return f"size({mapped}) == {len(expected)} && {mapped}.all(r, r in {literal}) && {literal}.all(r, r in {mapped})"


def test_cel_parameter_tables():
    from cel_parameter_tables import parameter_tables

    supply = parameter_tables(fixture("verified-supply.binding.yaml"), load_program("verified-supply.rules.yaml"),
                              "request.namespace")
    assert supply == {"verified_image": {
        "list": SUPPLY_LIST,
        "columns": {"namespace": "request.namespace", "service": "{e}.service", "image": "{e}.image"},
        "types": {"namespace": "string", "service": "string", "image": "string"},
    }}
    flow_binding, flow_program = fixture("in-zone-flow.binding.yaml"), load_program("in-zone-flow.rules.yaml")
    flows = parameter_tables(flow_binding, flow_program, "object.ns")
    assert flows == {"published_flow": {
        "list": FLOW_LIST,
        "columns": {"namespace": "object.ns", "source": "{e}.source", "destination": "{e}.destination",
                    "protocol": "{e}.protocol", "port": "{e}.port"},
        "types": {"namespace": "string", "source": "string", "destination": "string", "protocol": "string",
                  "port": "integer"},
    }}
    unknown = dict(flow_binding, parameters={"absent_relation": flow_binding["parameters"]["published_flow"]})
    with pytest.raises(ValueError):
        parameter_tables(unknown, flow_program, "object.ns")

    images = parameter_tables(fixture("verified-supply.binding.yaml"), load_program("verified-supply.rules.yaml"),
                              "object.ns")["verified_image"]
    tcp = {"source": "reader", "destination": "web", "port": 443}
    udp = {"source": "idp", "destination": "dns", "protocol": "UDP", "port": 53}
    row = {"namespace": "blue", "protocol": "TCP"}
    samples = [
        ({"ns": "blue"}, {"spec": {"images": [{"service": "web", "image": IMAGE_A}, {"service": "api", "image": IMAGE_B}]}},
         same_rows(images, [{"namespace": "blue", "service": "web", "image": IMAGE_A},
                            {"namespace": "blue", "service": "api", "image": IMAGE_B}])),
        ({"ns": "blue"}, {"spec": {"flows": [tcp], "transportFlows": [udp]}},
         same_rows(flows["published_flow"], [dict(tcp, **row), dict(udp, namespace="blue")])),
        ({"ns": "blue"}, {"spec": {"flows": [tcp]}},
         same_rows(flows["published_flow"], [dict(tcp, **row)])),
        ({"ns": "blue"}, {"spec": {"flows": [], "transportFlows": []}}, same_rows(flows["published_flow"], [])),
    ]
    results = run_cel(samples)
    if results is not None:
        assert results == [True] * len(samples)
