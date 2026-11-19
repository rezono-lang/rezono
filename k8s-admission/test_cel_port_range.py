"""Every port of a requested range needs its own published row.

See decisions/k8s-admission-translator.md, "Port range".
"""

import pytest
from translator_support import evaluate, load_program, run_cel

FLOWS = {
    "list": "params.flows",
    "columns": {"namespace": "object.ns", "source": "{e}.source", "destination": "{e}.destination",
                "port": "{e}.port"},
    "types": {"namespace": "string", "source": "string", "destination": "string", "port": "integer"},
}
PUBLISHED = [("reader", "web", 443), ("reader", "web", 444), ("reader", "web", 446), ("probe", "web", 443)]
CASES = [
    ("reader", "web", 443, 443, True),
    ("reader", "web", 443, 444, True),
    ("reader", "web", 443, 445, False),
    ("reader", "web", 446, 446, True),
    ("reader", "web", 445, 446, False),
    ("reader", "web", 444, 443, False),
    ("probe", "web", 443, 443, True),
    ("probe", "web", 444, 444, False),
    ("reader", "api", 443, 443, False),
]


@pytest.mark.xfail(
    strict=True,
    reason="M4: Write cel_port_range.covers as decisions/k8s-admission-translator.md specifies under Port range. "
           "Write in k8s-admission/cel_port_range.py. Without Go the test checks the exact text; the CI also runs cel-go.",
)
def test_cel_port_range():
    from cel_port_range import covers

    conditions = ["(e0.source == object.row.source)", "(e0.destination == object.row.destination)"]
    start, end = "object.row.port.start", "object.row.port.end"
    expression = covers(FLOWS, "e0", conditions, "port", start, end)
    assert expression == (
        "(object.row.port.start <= object.row.port.end && size(params.flows.filter(e0, "
        "(e0.source == object.row.source) && (e0.destination == object.row.destination) && "
        "(e0.port >= object.row.port.start) && (e0.port <= object.row.port.end))) == "
        "object.row.port.end - object.row.port.start + 1)"
    )
    assert covers(FLOWS, "e2", [], "port", "8", "9") == (
        "(8 <= 9 && size(params.flows.filter(e2, (e2.port >= 8) && (e2.port <= 9))) == 9 - 8 + 1)"
    )
    with pytest.raises(ValueError):
        covers(FLOWS, "e0", conditions, "protocol", start, end)

    # A loose calculation and Rezono's per-port rows give the hand-written answers.
    published = set(PUBLISHED)
    prog = load_program("in-zone-flow.rules.yaml")
    model = {"admission_flow": [("blue", s, d, "TCP", p) for s, d, p in PUBLISHED]}
    for source, destination, first, last, expected in CASES:
        ports = range(first, last + 1)
        assert (first <= last and all((source, destination, p) in published for p in ports)) is expected
        if first <= last:
            rows = [("blue", source, destination, "TCP", p) for p in ports]
            allowed = evaluate(prog, {**model, "requested_flow": rows}, "allow_flow")
            assert all(tuple(map(str, row)) in allowed for row in rows) is expected

    params = {"flows": [{"source": s, "destination": d, "port": p} for s, d, p in PUBLISHED]}
    samples = [({"ns": "blue", "row": {"source": s, "destination": d, "port": {"start": a, "end": b}}},
                params, expression) for s, d, a, b, _ in CASES]
    results = run_cel(samples)
    if results is not None:
        assert results == [case[-1] for case in CASES]
