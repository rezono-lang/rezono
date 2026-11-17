"""A Nest sheet (`nest.<id>`, one per binding) is checked like any sheet (rezono_checker.views, check_view), plus its
binding in the compiled bundle (`channels.nests`): its nodes are exactly the parts the role's rows give (every element
of the first level the role reads, every element whose container is a part, and every element whose container is
unknown, apart with its own parts; an element known to have no container is on no sheet); a part's container is the
role's one row of its level's arrow; a perspective's states are exactly the role's rows of its relation for that part,
and without a row "none" or unknown, whichever holds. Negative cases first."""

import copy
import json

from rezono_checker.views import Role, check_view

STATE = {"channel": "tone", "slot": "state", "level": "ordered", "meaning_message": "s"}
# A binding as the compiler writes it into the bundle: an arrow by its element id, a column by its name.
NEST = {"id": "home", "title_message": "t", "part_message": "p",
        "levels": [{"kind": "household", "flow": "column"}, {"kind": "application", "part_of": "application.household", "flow": "row"},
                   {"kind": "cost_line", "part_of": "cost_line.application"}],
        "perspectives": [{"id": "as_is", "label_message": "a"},
                         {"id": "repeat", "label_message": "r", "relation": "repeat_application", "part": "part", "origin": "origin", "state": STATE}]}
BUNDLE = {
    "kinds": [{"id": "household"}, {"id": "application"}, {"id": "renewal", "parent": "application"},
              {"id": "transfer", "parent": "application"}, {"id": "cost_line"}, {"id": "scheme"}],
    "attributes": [],
    # Both arrows of the Nest are required, and no relation says `world`, so each is closed.
    "arrows": [{"id": "application.household", "table": "application__household", "kind": "application", "target": "household", "required": True},
               {"id": "cost_line.application", "table": "cost_line__application", "kind": "cost_line", "target": "application", "required": True},
               {"id": "application.scheme", "table": "application__scheme", "kind": "application", "target": "scheme", "required": False}],
    "relations": [{"id": "repeat_application", "columns": [{"name": "origin", "type": "string"}, {"name": "part", "type": "string"},
                                                           {"name": "state", "type": "string"}]}],
    "channels": {"nests": [NEST, {k: v for k, v in NEST.items() if k != "perspectives"} | {"id": "plain"}]},
}
# h1 holds a1 (with line c1), h2 holds a2 (with line c3); a3 (a renewal) and c4 have no container this role reads, c2
# lies in a3; c5 lies in an application this role does not read, a9 is another role's.
ROWS = {"household": [["h1"], ["h2"]], "application": [["a1"], ["a2"], ["a3"]], "renewal": [["a3"]],
        "cost_line": [["c1"], ["c2"], ["c3"], ["c4"], ["c5"]], "scheme": [["s1"]],
        "application__household": [["a1", "h1"], ["a2", "h2"]], "application__scheme": [["a1", "s1"]],
        "cost_line__application": [["c1", "a1"], ["c2", "a3"], ["c3", "a2"], ["c5", "a9"]],
        "repeat_application": [["a1", "a3", "again"], ["a1", "c1", "first"], ["a2", "c1", "first"]]}
SHEET, TILE = "nest.home", 512
FULL = frozenset(ROWS)  # this role reads every relation in full (the `full` flag of its snapshots)
IN = lambda arrow, value: {"relation": arrow, "value": value}  # noqa: E731
APART = {"unknown": True}


def part(node_id, y, group=None, repeat=()):
    n = {"id": node_id, "x": 0, "y": y, "width": 100, "height": 20, "status": "valid", "states": {"repeat": [list(s) for s in repeat]}}
    return n | ({"group": group} if group is not None else {})


NODES = [
    part("household/h1", 0),  # 0
    part("household/h2", 20),  # 1
    part("application/a1", 40, IN("application__household", "h1")),  # 2
    part("application/a2", 60, IN("application__household", "h2")),  # 3
    part("renewal/a3", 80, APART, [("a1", "again")]),  # 4
    part("cost_line/c1", 100, IN("cost_line__application", "a1"), [("a1", "first"), ("a2", "first")]),  # 5
    part("cost_line/c2", 120, IN("cost_line__application", "a3")),  # 6
    part("cost_line/c3", 140, IN("cost_line__application", "a2")),  # 7
    part("cost_line/c4", 160, APART),  # 8
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


def with_arrow(arrow_id, **change):
    """The bundle with one arrow declared otherwise."""
    return BUNDLE | {"arrows": [a | change if a["id"] == arrow_id else a for a in BUNDLE["arrows"]]}


def changed(i, **change):
    out = copy.deepcopy(NODES)
    out[i].update(change)
    return out


def without(*ids, nodes=NODES):
    return [n for n in nodes if n["id"] not in ids]


def found(text, **kw):
    out = problems(**kw)
    assert any(text in p for p in out), out


def test_a_part_the_role_does_not_read_is_found():
    hidden = part("application/a9", 180, IN("application__household", "h1"))
    found("application/a9 is no part of this Nest", nodes=[*NODES, hidden])
    found("application/a9 is no row the role reads", nodes=[*NODES, hidden])
    found("household/h9 is no part of this Nest", nodes=[*NODES, part("household/h9", 180)])
    # c5 is read, its application is not: it is in a container, so not apart, and that container is no part.
    found("cost_line/c5 is no part of this Nest", nodes=[*NODES, part("cost_line/c5", 180, IN("cost_line__application", "a9"))])


def test_a_part_in_another_container_than_its_row_says_is_found():
    found("the role's row of cost_line__application says a1", nodes=changed(5, group=IN("cost_line__application", "a3")))
    found("the role's row of application__household says h1", nodes=changed(2, group=IN("application__scheme", "s1")))
    found("the role's row of application__household says h2", nodes=changed(3, group=IN("application__household", "h1")))


def test_a_missing_part_is_found():
    found("part cost_line/c1 is missing: the role reads it", nodes=without("cost_line/c1"))
    found("part household/h2 is missing", nodes=without("household/h2"))  # every element of the first level
    found("part cost_line/c4 is missing", nodes=without("cost_line/c4"))  # one that stands apart is a part too
    found("part renewal/a3 is missing", nodes=without("renewal/a3"))


def test_a_part_that_stands_apart_stands_once():
    twice = [*NODES, part("cost_line/c4", 180, APART)]
    assert any("cost_line/c4" in p for p in problems(nodes=twice)), problems(nodes=twice)


def test_an_unknown_container_drawn_as_known_is_found():
    found("renewal/a3 stands in a container the role reads no row of", nodes=changed(4, group=IN("application__household", "h1")))
    bare = copy.deepcopy(NODES)
    del bare[8]["group"]
    found("cost_line/c4 stands in a container the role reads no row of", nodes=bare)


def test_a_known_container_drawn_apart_is_found():
    found("application/a1 stands apart as unknown, the role reads its container h1", nodes=changed(2, group=APART))
    found("household/h1 is the element the sheet is of, yet stands in a container", nodes=changed(0, group=APART))


def test_a_state_the_role_s_rows_do_not_give_is_found():
    text = "shows states that are not the role's rows of its perspectives"
    found(f"cost_line/c1 {text}", nodes=changed(5, states={"repeat": [["a1", "again"], ["a2", "first"]]}))
    found(f"cost_line/c2 {text}", nodes=changed(6, states={"repeat": [["a1", "first"]]}))
    found(f"cost_line/c1 {text}", nodes=changed(5, states={"repeat": [["a1", "first"]]}))  # one of its rows left out
    found(f"renewal/a3 {text}", nodes=changed(4, states={"repeat": [["again"]]}))  # without the origin the binding names
    found(f"household/h1 {text}", nodes=changed(0, states={"repeat": [], "as_is": []}))  # a perspective without a relation has none
    less = copy.deepcopy(NODES)
    del less[0]["states"]
    found(f"household/h1 {text}", nodes=less)


def test_a_part_known_to_have_no_container_is_on_no_sheet_and_an_unknown_one_stands_apart():
    """The arbiter, 11-11-2026: without a container row a part stands apart where its container is unknown (a
    required arrow, an open relation, or one the role does not read in full). Where the arrow is optional, its
    relation closed and read in full, the element is known to have none: a part of nothing, on no sheet."""
    plain = [{k: v for k, v in n.items() if k != "states"} for n in NODES]
    rest = without("renewal/a3", "cost_line/c2", nodes=plain)
    optional = with_arrow("application.household", required=False)
    # a3 has no household: drawn apart it would call a known fact unknown. Its line c2 goes with it; c4 stays.
    found("renewal/a3 is no part of this Nest", nodes=plain, sheet="nest.plain", bundle=optional)
    found("cost_line/c2 is no part of this Nest", nodes=plain, sheet="nest.plain", bundle=optional)
    assert problems(nodes=rest, sheet="nest.plain", bundle=optional) == []
    for why in (dict(bundle=BUNDLE), dict(bundle=with_arrow("application.household", required=False, world="open")),
                dict(bundle=optional, full=FULL - {"application__household"}), dict(bundle=optional, full=frozenset())):
        assert problems(nodes=plain, sheet="nest.plain", **why) == [], why
        found("part renewal/a3 is missing: the role reads it", nodes=rest, sheet="nest.plain", **why)


def test_a_part_without_a_state_shows_none_or_unknown_and_never_the_other():
    """A perspective's state has the same answers as a Timeline's date: the role's rows; none (`[]`) where the
    relation is closed and read in full; unknown (`{unknown: true}`) where it is open or read in part."""
    text = "shows states that are not the role's rows of its perspectives"
    found(f"cost_line/c2 {text}", nodes=changed(6, states={"repeat": APART}))  # none, drawn as unknown
    found(f"cost_line/c1 {text}", nodes=changed(5, states={"repeat": APART}))  # the role's rows, drawn as unknown
    unknown = [n | {"states": {"repeat": n["states"]["repeat"] or APART}} for n in NODES]
    for why in (dict(full=FULL - {"repeat_application"}), dict(full=frozenset()),
                dict(bundle=BUNDLE | {"relations": [BUNDLE["relations"][0] | {"world": "open"}]})):
        found(f"cost_line/c2 {text}", **why)  # unknown, drawn as none
        assert problems(nodes=unknown, **why) == [], why


def test_a_part_with_two_containers_is_no_part():
    rows = ROWS | {"application__household": [*ROWS["application__household"], ["a1", "h2"]]}
    found("application/a1 is no part of this Nest", rows=rows)
    found("cost_line/c1 is no part of this Nest", rows=rows)  # and so neither is what lies in it


def test_two_elements_of_one_level_with_one_id_are_refused():
    """A container is named by its id alone: with a renewal and a transfer both `a3`, a line in `a3` would lie
    in one of two. The viewer stops on it too (RV-V29)."""
    rows = ROWS | {"transfer": [["a3"]]}
    found("renewal/a3 and transfer/a3 are two elements of level application with one id", rows=rows)


def test_a_node_that_is_no_part_or_a_line_is_found():
    found("scheme/s1 is no part of this Nest", nodes=[*NODES, part("scheme/s1", 180)])
    line = {"id": "application/a1->x->cost_line/c1", "source": "application/a1", "target": "cost_line/c1", "arrow": "x", "points": []}
    found("a Nest holds no lines", edges=[line])


def test_a_sheet_without_its_binding_is_found():
    found("no Nest of the bundle has this sheet", sheet="nest.nothing")
    found("no Nest of the bundle has this sheet", sheet="nest.home.h1")  # an element is never part of a sheet's name
    found("no Nest of the bundle has this sheet", sheet="nest")
    for binding in (NEST | {"levels": NEST["levels"][:1]},  # one level
                    NEST | {"levels": [NEST["levels"][0], NEST["levels"][2]]},  # an arrow that does not point one level out
                    NEST | {"levels": [NEST["levels"][0], NEST["levels"][1] | {"part_of": "application__household"}]},  # a table, no id
                    NEST | {"perspectives": [NEST["perspectives"][1] | {"part": "nothing"}]}):  # no such column
        found("no Nest of the bundle has this sheet", bundle=dict(BUNDLE, channels={"nests": [binding]}))


def test_a_nest_without_perspectives_shows_no_states():
    plain = [{k: v for k, v in n.items() if k != "states"} for n in NODES]
    assert problems(nodes=plain, sheet="nest.plain") == []
    found("shows states that are not the role's rows", nodes=NODES, sheet="nest.plain")
    found("holds more than its place", nodes=NODES, sheet="flow.home")  # and states are nothing a Flow's node holds


def test_a_role_that_reads_no_element_of_the_first_level_sees_only_what_stands_apart():
    rows = {k: v for k, v in ROWS.items() if k not in ("household", "application__household")}
    # Without a household, every application stands apart (its container is unknown), with its lines.
    apart = [part("application/a1", 0, APART), part("application/a2", 20, APART), part("renewal/a3", 40, APART),
             part("cost_line/c1", 60, IN("cost_line__application", "a1")), part("cost_line/c2", 80, IN("cost_line__application", "a3")),
             part("cost_line/c3", 100, IN("cost_line__application", "a2")), part("cost_line/c4", 120, APART)]
    plain = [{k: v for k, v in n.items() if k != "states"} for n in apart]
    assert problems(nodes=plain, rows=rows, sheet="nest.plain") == []


def test_parts_containers_and_states_the_role_reads_pass():
    assert problems() == []
