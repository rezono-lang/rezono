"""A Timeline sheet (`timeline.<id>`) is checked like any sheet (rezono_checker.views, check_view), plus its binding
in the compiled bundle (`channels.timelines`): its nodes are exactly the elements of the row kind that the role
reads, each with its dates as a list in the binding's order: `known` with the value of the role's one row of
that attribute; without a row the start and the end `unknown`, the extension and a mark `unknown` or, where the
row is known to have none (optional, a closed relation, read in full), not there; it holds no line, and no cell
but its judgement. Negative cases first."""

import copy
import json

from rezono_checker.views import Role, check_view

# A binding as the compiler writes it into the bundle: an attribute by its element id (`<kind>.<slot>`).
TIMELINE = {"id": "validity", "title_message": "t", "rows": "parameter", "start": "parameter.valid_from",
            "end": "parameter.valid_until", "extension": "parameter.grace_until", "main_message": "m",
            "extension_message": "e", "marks": [{"slot": "parameter.decided_on"}]}
BUNDLE = {
    "kinds": [{"id": "parameter"}, {"id": "rate", "parent": "parameter"}, {"id": "scheme"}],
    # Only the start is required; no relation says `world`, so each is closed.
    "attributes": [{"id": f"parameter.{a}", "table": f"parameter__{a}", "required": a == "valid_from"}
                   for a in ("valid_from", "valid_until", "grace_until", "decided_on", "status")],
    "arrows": [],
    "channels": {"timelines": [TIMELINE, {k: v for k, v in TIMELINE.items() if k not in ("extension", "extension_message", "marks")}
                               | {"id": "plain", "judgement": {"channel": "tone", "slot": "parameter.status", "level": "ordered", "meaning_message": "j"}}]},
}
# p1 has every date; p2 (a rate, a subkind) has no end and no decision; p3 is a row another role reads.
ROWS = {"parameter": [["p1"], ["p2"]], "rate": [["p2"]], "scheme": [["s1"]],
        "parameter__valid_from": [["p1", "2026-01-01"], ["p2", "2026-07-01"]],
        "parameter__valid_until": [["p1", "2027-01-01"]], "parameter__grace_until": [["p1", "2027-04-01"]],
        "parameter__decided_on": [["p1", "2025-11-20"]], "parameter__status": [["p1", "current"]]}
SHEET, TILE = "timeline.validity", 512
FULL = frozenset(ROWS)  # this role reads every relation in full (the `full` flag of its snapshots)
START, END, EXTENSION, MARK = (f"parameter__{a}" for a in ("valid_from", "valid_until", "grace_until", "decided_on"))
ORDER = [START, END, EXTENSION, MARK]  # the binding's order: the start, the end, the extension, then the marks
KNOWN = lambda relation, value: {"relation": relation, "state": "known", "value": value}  # noqa: E731
UNKNOWN = lambda relation: {"relation": relation, "state": "unknown"}  # noqa: E731
NODES = [
    {"id": "parameter/p1", "x": 0, "y": 0, "width": 400, "height": 30, "status": "valid",
     "dates": [KNOWN(START, "2026-01-01"), KNOWN(END, "2027-01-01"), KNOWN(EXTENSION, "2027-04-01"), KNOWN(MARK, "2025-11-20")]},
    # No end: unknown, as an end always is. No extension and no decision: optional, closed and read in full, so
    # p2 has none and shows none.
    {"id": "rate/p2", "x": 0, "y": 30, "width": 400, "height": 30, "status": "valid",
     "dates": [KNOWN(START, "2026-07-01"), UNKNOWN(END)]},
]


def problems(nodes=NODES, edges=(), rows=ROWS, sheet=SHEET, bundle=BUNDLE, full=FULL):
    snapshots = {r: json.dumps([{"key": k} for k in keys]).encode() for r, keys in rows.items()}
    layout = {"nodes": {n["id"]: [n["x"], n["y"], n["width"], n["height"]] for n in nodes},
              "edges": {e["id"]: {"source": e["source"], "target": e["target"], "points": e["points"]} for e in edges}}
    tile = {"format": "rezono.tile/1", "sheet": sheet, "level": 0, "x": 0, "y": 0, "box": [0, 0, TILE, TILE],
            "nodes": nodes, "edges": list(edges)}
    path = f"{sheet}/0/0_0.json"
    return check_view(sheet, snapshots, json.dumps(layout).encode(), {path: json.dumps(tile).encode()}, path, TILE, 4, 1, bundle,
                      role=Role(snapshots, bundle, full))


def with_slot(relation, **change):
    """The bundle with one attribute declared otherwise."""
    return BUNDLE | {"attributes": [a | change if a["table"] == relation else a for a in BUNDLE["attributes"]]}


def dated(i, relation, date, nodes=NODES):
    """Row i with `date` as its entry of `relation`, at that relation's place in the binding's order; without
    an entry of it where `date` is None."""
    out = copy.deepcopy(nodes)
    rest = [d for d in out[i]["dates"] if d["relation"] != relation]
    out[i]["dates"] = sorted([*rest, *([date] if date is not None else [])], key=lambda d: ORDER.index(d["relation"]))
    return out


def found(text, **kw):
    out = problems(**kw)
    assert any(text in p for p in out), out


def test_a_row_the_role_does_not_read_is_found():
    """p3 is in no row of this role: on the sheet it would show an element and its dates to who may not read them."""
    hidden = {"id": "parameter/p3", "x": 0, "y": 60, "width": 400, "height": 30, "status": "valid",
              "dates": [UNKNOWN(r) for r in ORDER[:3]]}
    found("parameter/p3 is no row of the Timeline", nodes=[*NODES, hidden])
    found("parameter/p3 is no row the role reads", nodes=[*NODES, hidden])


def test_a_date_that_differs_from_the_role_s_row_is_found():
    found("shows parameter__valid_until as '2028-01-01', the role reads ['2027-01-01']",
          nodes=dated(0, END, KNOWN(END, "2028-01-01")))
    found("shows parameter__decided_on as '2025-11-21'", nodes=dated(0, MARK, KNOWN(MARK, "2025-11-21")))


def test_a_missing_row_is_found():
    found("row rate/p2 is missing: the role reads it", nodes=NODES[:1])
    # An element of the row kind with no date at all is a row too: every date unknown.
    found("row parameter/p4 is missing", rows=ROWS | {"parameter": [*ROWS["parameter"], ["p4"]]})


def test_an_unknown_date_drawn_as_known_is_found():
    """The role reads no end of p2: a date there, whoever else reads one, is refused, and so is "no end"."""
    found("shows parameter__valid_until as '2027-01-01', the role reads no such row",
          nodes=dated(1, END, KNOWN(END, "2027-01-01")))
    # An end is never "none": the end is optional here and the role reads its whole closed relation.
    found("does not show parameter__valid_until: the role reads no row of it, so it is unknown", nodes=dated(1, END, None))
    found("neither known nor unknown", nodes=dated(1, END, {"relation": END, "state": "none"}))
    found("neither known nor unknown", nodes=dated(1, END, {"relation": END, "state": "known", "value": None}))
    found("neither known nor unknown", nodes=dated(1, END, {"relation": END, "state": "unknown", "value": "2027-01-01"}))
    # The role reads no decision of p2: a mark there is a date nobody stated to this role.
    found("shows parameter__decided_on as '2025-11-20', the role reads no such row", nodes=dated(1, MARK, KNOWN(MARK, "2025-11-20")))


def test_a_known_date_drawn_as_unknown_is_found():
    found("shows parameter__valid_until as unknown, the role reads ['2027-01-01']", nodes=dated(0, END, UNKNOWN(END)))


def test_an_extension_and_a_mark_without_a_row_show_none_or_unknown_and_never_the_other():
    """Three answers, each exact both ways (the arbiter, 11-11-2026): known, the role's row; none, where the
    attribute is optional, its relation closed and read in full; unknown in every other case without a row."""
    for relation in (EXTENSION, MARK):
        # Known: the role's row is never left out and never unknown.
        found(f"does not show {relation}, the role reads", nodes=dated(0, relation, None))
        found(f"shows {relation} as unknown, the role reads", nodes=dated(0, relation, UNKNOWN(relation)))
        # None: p2 has no row of it, and shown as unknown the sheet would call a known fact unknown.
        as_unknown = dated(1, relation, UNKNOWN(relation))
        found(f"shows {relation} as unknown: it is optional and the role reads its closed relation in full, so the row has none",
              nodes=as_unknown)
        assert problems(bundle=with_slot(relation, world="closed")) == []
        # Unknown: read in part, an open relation, or a required attribute. Left out, the sheet would say "none".
        for why in (dict(full=FULL - {relation}), dict(bundle=with_slot(relation, world="open")),
                    dict(bundle=with_slot(relation, required=True)), dict(bundle=with_slot(relation, required=None))):
            found(f"does not show {relation}: the role reads no row of it, so it is unknown and is shown as unknown", **why)
            assert problems(nodes=as_unknown, **why) == [], why
    # Without the snapshots' flags no relation counts as read in full: nothing is "none".
    both = dated(1, MARK, UNKNOWN(MARK), dated(1, EXTENSION, UNKNOWN(EXTENSION)))
    assert problems(nodes=both, full=frozenset()) == []
    found("does not show parameter__grace_until: the role reads no row of it", full=frozenset())


def test_a_date_with_two_rows_is_never_known():
    """The binding's attributes are single-valued. Two rows for one element are no date the sheet may choose
    from, and a mark with two rows cannot be left out either."""
    rows = ROWS | {"parameter__valid_until": [["p1", "2027-01-01"], ["p1", "2028-01-01"]]}
    found("the role reads ['2027-01-01', '2028-01-01']", rows=rows)
    rows = ROWS | {"parameter__decided_on": [["p1", "2025-11-20"], ["p1", "2025-12-01"]]}
    found("the role reads ['2025-11-20', '2025-12-01']", rows=rows)
    found("does not show parameter__decided_on, the role reads ['2025-11-20', '2025-12-01']", rows=rows, nodes=dated(0, MARK, None))


def test_dates_that_are_no_list_of_the_binding_s_dates_in_its_order_are_found():
    refused = "does not show its dates as a list of its Timeline's dates, each once and in the binding's order"

    def with_dates(dates):
        return [{**NODES[0], "dates": dates}, NODES[1]]

    of = NODES[0]["dates"]
    found(refused, nodes=with_dates({d["relation"]: {k: v for k, v in d.items() if k != "relation"} for d in of}))  # a map by relation
    found(refused, nodes=with_dates([*of, KNOWN("parameter__status", "current")]))  # a relation the binding does not name
    found(refused, nodes=with_dates([*of, of[3]]))  # one relation twice
    found(refused, nodes=with_dates([of[1], of[0], *of[2:]]))  # the end before the start
    found(refused, nodes=with_dates([of[3], *of[:3]]))  # a mark before the dates
    found(refused, nodes=with_dates([*of[:3], "2025-11-20"]))  # an entry that names no relation
    found(refused, nodes=[{k: v for k, v in n.items() if k != "dates"} for n in NODES])  # no dates at all


def test_a_node_that_is_no_row_or_a_line_is_found():
    scheme = {"id": "scheme/s1", "x": 0, "y": 60, "width": 400, "height": 30, "status": "valid", "dates": NODES[1]["dates"]}
    found("scheme/s1 is no row of the Timeline", nodes=[*NODES, scheme])
    end = {"id": "unknown/parameter/p2/parameter__valid_until", "x": 0, "y": 60, "width": 10, "height": 10, "status": "unknown"}
    found("is no row of the Timeline", nodes=[*NODES, end])
    line = {"id": "parameter/p1->x->rate/p2", "source": "parameter/p1", "target": "rate/p2", "arrow": "x", "points": []}
    found("a Timeline holds no lines", edges=[line])


def test_a_cell_is_the_judgement_of_the_binding_or_refused():
    plain = [{**n, "dates": n["dates"][:2]} for n in NODES]  # the binding `plain` has a start and an end only
    assert problems(nodes=plain, sheet="timeline.plain") == []
    found("does not show its dates as a list of its Timeline's dates", sheet="timeline.plain")  # an extension it does not bind
    judged = copy.deepcopy(plain)
    judged[0]["cell"] = {"relation": "parameter__status", "state": "known", "value": "current"}
    assert problems(nodes=judged, sheet="timeline.plain") == []
    judged[0]["cell"]["value"] = "expired"
    found("shows a cell that is no row the role reads", nodes=judged, sheet="timeline.plain")
    other = copy.deepcopy(plain)
    other[0]["cell"] = {"relation": START, "state": "known", "value": "2026-01-01"}
    found("is not the judgement of its Timeline", nodes=other, sheet="timeline.plain")
    cell = copy.deepcopy(NODES)  # the first binding has no judgement
    cell[0]["cell"] = {"relation": "parameter__status", "state": "known", "value": "current"}
    found("is not the judgement of its Timeline", nodes=cell)


def test_a_timeline_without_its_binding_and_dates_on_another_sheet_are_found():
    found("no Timeline of the bundle has this sheet", sheet="timeline.nothing")
    found("holds more than its place", sheet="timeline.nothing")  # and its dates are read as nothing the checker knows
    found("holds more than its place", sheet="flow.validity")
    for binding in ({k: v for k, v in TIMELINE.items() if k != "end"},  # no end
                    TIMELINE | {"end": "parameter__valid_until"},  # a relation where an element id goes
                    TIMELINE | {"extension": "parameter.valid_until"},  # one date twice
                    TIMELINE | {"judgement": {"channel": "tone", "slot": "parameter.nothing"}}):  # no such attribute
        found("no Timeline of the bundle has this sheet", bundle=dict(BUNDLE, channels={"timelines": [binding]}))


def test_a_sheet_of_a_kind_the_checker_does_not_know_is_found():
    plain = [{k: v for k, v in n.items() if k != "dates"} for n in NODES]
    found("a sheet of a kind the checker does not know", nodes=plain, sheet="other.validity")
    assert problems(nodes=plain, sheet="flow.validity") == [] and problems(nodes=plain, sheet="map") == []


def test_rows_and_dates_the_role_reads_pass():
    assert problems() == []
