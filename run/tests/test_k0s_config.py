"""The k0s cluster configuration from the derived controller, from decisions/run-cluster-shape.md."""

import json

import pytest

from offline_cases import implementation


CONTROLLER = ("run-one", "m-c", "192.0.2.13")


def canonical(document):
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.mark.xfail(strict=True, reason="Read decisions/run-cluster-shape.md, section Converters. Implement render in run/k0s_config.py.")
def test_k0s_config():
    render = implementation("k0s_config.py", "render")
    expected = canonical({
        "apiVersion": "k0s.k0sproject.io/v1beta1", "kind": "ClusterConfig", "metadata": {"name": "run-one"},
        "spec": {"api": {"address": "192.0.2.13", "sans": ["192.0.2.13"]}, "network": {"provider": "custom"}},
    })
    assert render("run-one", [CONTROLLER]) == expected
    assert render("run-one", [CONTROLLER, CONTROLLER]) == expected

    v6 = render("run-one", [("run-one", "m-c", "2001:db8::13")])
    assert json.loads(v6)["spec"]["api"] == {"address": "2001:db8::13", "sans": ["2001:db8::13"]}

    for rows in ([], [CONTROLLER, ("run-one", "m-d", "192.0.2.14")], [CONTROLLER, ("run-one", "m-c", "192.0.2.21")],
                 [("run-two", "m-c", "192.0.2.13")], [("run-one", "m-c", "controller.example.org")]):
        with pytest.raises(ValueError):
            render("run-one", rows)
