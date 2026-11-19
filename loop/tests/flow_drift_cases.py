"""Finite policy and Hubble input rows, with independently stated output witnesses."""

from rezono_canon import canonical_json
from wire_fixtures import fixture


def columns(names, integers=()):
    return [(name, "integer" if name in integers else "string") for name in names.split()]


SCOPE = ("run-a", "hubble", "sample")
SCOPE_NAMES = "run collector window"
FLOW_NAMES = "source destination protocol port"
SWEEP_REF = "sweep/current"
POLICY = "policy/base"
WINDOW_COLUMNS = columns(SCOPE_NAMES + " start stop ref", {"start", "stop"})
SWEEP_COLUMNS = {
    "sweep_window": WINDOW_COLUMNS,
    "expected_node": columns(SCOPE_NAMES + " node"),
    "node_report": columns(SCOPE_NAMES + " node first last gaps lost", {"first", "last", "gaps", "lost"}),
    # The protected admission inputs, with their reserved signatures (decisions/admission-transport.md section 6).
    "verified_receipt": columns("receipt source scope cut inventory content"),
    "verified_member": columns("receipt member part value", {"part"}),
}
FLOW_COLUMNS = {
    "sweep_window": WINDOW_COLUMNS,
    "complete_sweep": columns(SCOPE_NAMES + " ref"),
    "bound_policy": columns(SCOPE_NAMES + " snapshot"),
    "allowed_flow": columns("snapshot " + FLOW_NAMES + " ref", {"port"}),
    "flow_event": columns(SCOPE_NAMES + " tick " + FLOW_NAMES + " verdict ref", {"tick", "port"}),
}

# Every change is applied to node b. Node a still has full coverage throughout.
REPORT_CASES = {
    "complete": ("node-b", 8, 25, 0, 0),
    "missing": None,
    "late-start": ("node-b", 11, 20, 0, 0),
    "early-stop": ("node-b", 10, 19, 0, 0),
    "interior-gap": ("node-b", 10, 20, 1, 0),
    "lost-event": ("node-b", 10, 20, 0, 1),
    "different-node": ("node-c", 10, 20, 0, 0),
}

OTHER_SCOPES = [("prior", "hubble", "sample"), ("run-a", "hubble", "prior"),
                ("run-a", "other", "sample")]
NODES = ("node-a", "node-b")


class MissingVerifiedSweepInventory(AssertionError):
    """complete_sweep follows from the recorded inventory without an admitted sweep receipt."""


def verified_sweep(nodes=NODES, scope=SCOPE, receipt="receipt/sweep", tag="sweep-node"):
    """The rows that admission gives for one verified sweep receipt (decisions/admission-transport.md section 6).

    Each trusted member key is [tag, run, collector, window, node]; admission exposes one row per part."""
    members = []
    for node in nodes:
        key = [tag, *scope, node]
        member = canonical_json(key)
        members.extend((receipt, member, part, value) for part, value in enumerate(key))
    return {
        "verified_receipt": [(receipt, "inventory-observer", "scope/" + receipt, "cut/" + receipt,
                              "inventory/" + receipt, "content/" + receipt)],
        "verified_member": members,
    }


def coverage_rows(case, verified=True):
    reports = [(*SCOPE, "node-a", 10, 20, 0, 0)]
    if case in REPORT_CASES and REPORT_CASES[case] is not None:
        reports.append((*SCOPE, *REPORT_CASES[case]))
    reports.extend((*other, "node-b", 10, 20, 0, 0) for other in OTHER_SCOPES)
    rows = {
        "sweep_window": [(*SCOPE, 10, 20, SWEEP_REF)],
        "expected_node": [] if case == "empty-inventory" else [(*SCOPE, "node-a"), (*SCOPE, "node-b")],
        "node_report": reports,
    }
    # The pinned inventory lists both nodes in every case; the empty-inventory case only empties the records.
    return {**rows, **verified_sweep()} if verified else rows


def tuples():
    cases = fixture("network")["cases"]
    keys = {case["id"]: tuple(case[name] for name in FLOW_NAMES.split()) for case in cases}
    keys["datagram"] = (*keys["echo"][:2], "UDP", keys["echo"][3])
    return keys


def flow_rows():
    keys = tuples()
    events = [("echo", 10, "forwarded", "event/1"),
              ("echo", 19, "forwarded", "event/2"),
              ("other-rule", 12, "dropped", "event/3"),
              ("overlap", 13, "dropped", "event/4"),
              ("outside", 14, "forwarded", "event/5"),
              ("datagram", 15, "forwarded", "event/6")]
    observations = [(*SCOPE, tick, *keys[key], verdict, ref) for key, tick, verdict, ref in events]
    observations.extend((*scope, 12, *keys["upper"], "forwarded", "event/foreign")
                        for scope in OTHER_SCOPES)
    observations.extend((*SCOPE, tick, *keys["upper"], "forwarded", "event/out-of-window")
                        for tick in (9, 20))
    return {
        "sweep_window": coverage_rows("complete")["sweep_window"],
        "bound_policy": [(*SCOPE, POLICY)],
        "allowed_flow": [(POLICY, *keys[key], "allow/" + key) for key in ("echo", "upper", "other-rule")],
        "flow_event": observations,
    }


def expected_rows(complete):
    # A hand-read table. Both refs are real input IDs, including the negative
    # lookup in a closed policy snapshot and the positive lookup of a sweep.
    rows = [
        ("echo", "matched", "valid", "allow/echo", "event/1"),
        ("echo", "matched", "valid", "allow/echo", "event/2"),
        ("other-rule", "blocked", "violated", "allow/other-rule", "event/3"),
        ("overlap", "prevented", "absent", POLICY, "event/4"),
        ("outside", "excess", "violated", POLICY, "event/5"),
        ("datagram", "excess", "violated", POLICY, "event/6"),
    ]
    if complete:
        rows.append(("upper", "unseen", "unknown", "allow/upper", SWEEP_REF))
    keys = tuples()
    return {(*SCOPE, *keys[key][:3], str(keys[key][3]), *outcome) for key, *outcome in rows}
