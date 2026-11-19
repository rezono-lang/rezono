"""Only a request fragment that CEL can compute becomes a gate; the rest stays an observation.

See decisions/k8s-admission-translator.md, "What CEL cannot do".
"""

import pytest
from translator_support import load_program, program

S, I = "string", "integer"
PAIR = [("namespace", S), ("service", S)]
PORT = [("namespace", S), ("port", I)]


def request_program(rule_list, **relations):
    return program({"req": ("base", PAIR), "ok": ("base", PAIR), "names": ("base", [("namespace", S)]),
                    "allow": ("derived", PAIR), **relations}, rule_list)


ALLOW = ("allow", ["?n", "?s"])
REQ = ("req", ["?n", "?s"], "positive")
COUNT_OK = {"aggregates": [{"relation": "ok", "terms": ["?n", "_"], "function": "count", "as": "?c"}]}


def observe(reason, rule=None):
    return {"route": "observe", "reason": reason, "rule": rule}


@pytest.mark.xfail(
    strict=True,
    reason="M4: Write admission_route.classify as decisions/k8s-admission-translator.md specifies under What CEL "
           "cannot do. Write in k8s-admission/admission_route.py.",
)
def test_admission_route():
    from admission_route import classify

    supply = load_program("verified-supply.rules.yaml")
    assert classify(supply, "allow_image", {"pod_image": "Pod"}) == {"route": "gate"}
    assert classify(supply, "verified_image", {"pod_image": "Pod"}) == observe("no_incoming_object")
    flows = load_program("in-zone-flow.rules.yaml")
    assert classify(flows, "allow_flow", {"requested_flow": "NetworkPolicy"}) == {"route": "gate"}

    joined = request_program([("allow", ALLOW, [REQ, ("ok", ["?n", "?s"], "positive")], [])])
    assert classify(joined, "allow", {"req": "Pod"}) == {"route": "gate"}
    assert classify(joined, "allow", {"req": "Pod", "ok": "ConfigMap"}) == observe("multiple_objects")
    assert classify(joined, "allow", {"req": "Pod", "ok": "Pod"}) == {"route": "gate"}

    # A count over the model is computed before the release; a count over the request is not.
    model_count = request_program([
        ("counted", ("counted", ["?n", "?c"]), [("names", ["?n"], "positive")], [], COUNT_OK),
        ("allow", ALLOW, [REQ, ("counted", ["?n", "?c"], "positive")], [("gt", "?c", "0")]),
    ], counted=("derived", [("namespace", S), ("count", I)]))
    assert classify(model_count, "allow", {"req": "Pod"}) == {"route": "gate"}
    request_count = request_program([("allow", ALLOW, [REQ], [("gt", "?c", "0")], COUNT_OK)])
    assert classify(request_count, "allow", {"req": "Pod"}) == observe("aggregate", "allow")

    shifted = program(
        {"req": ("base", PORT), "ok": ("base", PORT), "allow": ("derived", PORT)},
        [("allow", ("allow", ["?n", "?p"]), [("req", ["?n", "?p"], "positive"), ("ok", ["?n", "?q"], "positive")],
          [("eq", "?q", "?r")], {"assignments": [{"var": "?r", "op": "add", "left": "?p", "right": "1"}]})],
    )
    assert classify(shifted, "allow", {"req": "Pod"}) == observe("arithmetic", "allow")

    reach = program(
        {"seed": ("base", [("service", S)]), "edge": ("base", [("from", S), ("to", S)]),
         "good": ("base", [("service", S)]), "reached": ("derived", [("service", S)]),
         "allow": ("derived", [("service", S)])},
        [("reach_seed", ("reached", ["?a"]), [("seed", ["?a"], "positive")], []),
         ("reach_step", ("reached", ["?b"]), [("reached", ["?a"], "positive"), ("edge", ["?a", "?b"], "positive")], []),
         ("allow", ("allow", ["?b"]), [("reached", ["?b"], "positive"), ("good", ["?b"], "positive")], [])],
    )
    assert classify(reach, "allow", {"seed": "Pod"}) == observe("recursion", "reach_step")
    model_reach = program(
        {"seed": ("base", [("service", S)]), "edge": ("base", [("from", S), ("to", S)]),
         "req": ("base", [("service", S)]), "reached": ("derived", [("service", S)]),
         "allow": ("derived", [("service", S)])},
        [("reach_seed", ("reached", ["?a"]), [("seed", ["?a"], "positive")], []),
         ("reach_step", ("reached", ["?b"]), [("reached", ["?a"], "positive"), ("edge", ["?a", "?b"], "positive")], []),
         ("allow", ("allow", ["?b"]), [("req", ["?b"], "positive"), ("reached", ["?b"], "positive")], [])],
    )
    assert classify(model_reach, "allow", {"req": "Pod"}) == {"route": "gate"}

    closed = request_program([("allow", ALLOW, [REQ, ("ok", ["?n", "?s"], "negative")], [])])
    assert classify(closed, "allow", {"req": "Pod"}) == {"route": "gate"}
    unrecorded = request_program([
        ("unbanned", ("unbanned", ["?n", "?s"]), [REQ, ("ban", ["?n", "?s"], "negative")], []),
        ("allow", ALLOW, [("unbanned", ["?n", "?s"], "positive")], []),
    ], ban=("base", PAIR, {"world": "open"}), unbanned=("derived", PAIR, {"absence": True}))
    assert classify(unrecorded, "allow", {"req": "Pod"}) == observe("open_negation", "unbanned")
