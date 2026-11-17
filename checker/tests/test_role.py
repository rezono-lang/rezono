"""RV-K04: what one filtered role may read (rede_checker/access.py, decision O8), on a filter that got it wrong.

One small world, written by hand: nothing here comes from the compiler or the publisher. The role `guest` reads
every person, the documents it was granted, and what follows from those. `world()` is what a correct filter
hands the checker; each case breaks one thing, as a filter bug would, and names the reason. Every reason
`check_role` can give has a case.
"""

import json
import re
from pathlib import Path

import pytest

from rede_checker import access
from rede_checker.canon import encode_key

KINDS = {"doc", "person"}
COLUMNS = {"doc": ("doc",), "person": ("person",), "doc__author": ("doc", "person"), "role": (None,),
           "grant": (None, "doc"), "role__capability": (None, None)}


def atom(relation, *terms, polarity="positive", stratum="0"):
    return {"relation": relation, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def rule(rid, stratum, head, *body):
    return {"id": rid, "stratum": stratum, "head": {"relation": head[0], "terms": list(head[1:])}, "body": list(body)}


def derived(name, *columns):
    return {"name": name, "role": "derived", "key": [{"name": c, "type": "string"} for c in columns]}


# Every role reads every person; a document only when granted. So `person` is read in full and `doc` is not.
DOC = {"format": "rede.rules/1", "pack": "example",
       "relations": [derived("may_read", "role", "kind", "id"), derived("authored", "person", "doc"),
                     derived("busy", "person"), derived("idle", "person")],
       "rules": [
           rule("everyone", "1", ("may_read", "?r", "person", "?x"), atom("role", "?r"), atom("person", "?x")),
           rule("granted", "1", ("may_read", "?r", "doc", "?x"), atom("grant", "?r", "?x")),
           rule("authored", "1", ("authored", "?p", "?d"), atom("doc__author", "?d", "?p")),
           rule("busy", "1", ("busy", "?p"), atom("doc__author", "?d", "?p")),
           rule("idle", "2", ("idle", "?p"), atom("person", "?p"), atom("busy", "?p", polarity="negative", stratum="1")),
       ]}
# A calculation per document. It reads `person`, which the guest reads in full, or `doc__author`, which it does not.
CALC = {"format": "rede.calc-ir/1", "subject": "doc", "as_of": "calc__as_of", "rules": [{"view": "calc__size"}],
        "facts": [{"id": "people", "reads": "presence", "table": "person"}],
        "versions": [{"id": "size@v", "view": "calc__size__v",
                      "definitions": [{"when": {"boolean": True}, "value": {"fact": "people"}}]}]}


def ref(relation, *parts):
    return {"relation": relation, "key": encode_key(parts)}


def instance(rule_id, head, bindings, *premises):
    """A witness instance; a premise is (relation, *parts), or ("not", relation, *parts)."""
    return {"conclusion": ref(*head), "rule_id": rule_id,
            "bindings": [{"variable": v, "value": x} for v, x in bindings.items()],
            "premises": [{"row": ref(*p[1:]), "polarity": "negative", "stratum": 1} if p[0] == "not"
                         else {"row": ref(*p), "polarity": "positive", "stratum": 0} for p in premises]}


EVERYONE = [instance("everyone", ("may_read", "guest", "person", p), {"?r": "guest", "?x": p}, ("role", "guest"), ("person", p))
            for p in ("p1", "p2")]
GRANTED = instance("granted", ("may_read", "guest", "doc", "d1"), {"?r": "guest", "?x": "d1"}, ("grant", "guest", "d1"))
AUTHORED = {d: instance("authored", ("authored", "p1", d), {"?d": d, "?p": "p1"}, ("doc__author", d, "p1")) for d in ("d1", "d2")}
BUSY = {d: instance("busy", ("busy", "p1"), {"?d": d, "?p": "p1"}, ("doc__author", d, "p1")) for d in ("d1", "d2")}
IDLE = instance("idle", ("idle", "p2"), {"?p": "p2"}, ("person", "p2"), ("not", "busy", "p2"))
SIZE = {d: {"conclusion": ref("calc__size", d, "1", "known", ""), "rule": "size", "version": "v", "premises": []}
        for d in ("d1", "d2")}


def world(calc=False) -> dict:
    """The complete epoch and what a correct filter gives the guest."""
    w = {
        "complete": {"role": [("guest",)], "person": [("p1",), ("p2",)], "doc": [("d1",), ("d2",)],
                     "doc__author": [("d1", "p1"), ("d2", "p1")], "grant": [("guest", "d1")],
                     "may_read": [("guest", "person", "p1"), ("guest", "person", "p2"), ("guest", "doc", "d1")],
                     "authored": [("p1", "d1"), ("p1", "d2")], "busy": [("p1",)], "idle": [("p2",)]},
        "mine": {"role": [("guest",)], "person": [("p1",), ("p2",)], "doc": [("d1",)], "doc__author": [("d1", "p1")],
                 "grant": [("guest", "d1")],
                 "may_read": [("guest", "person", "p1"), ("guest", "person", "p2"), ("guest", "doc", "d1")],
                 # busy(p1) by the document it reads; idle(p2) negates busy, which it does not read in full
                 "authored": [("p1", "d1")], "busy": [("p1",)], "idle": []},
        "full": {"person", "role"},
        "instances": [*EVERYONE, GRANTED, *AUTHORED.values(), *BUSY.values(), IDLE],
        "witnesses": [*EVERYONE, GRANTED, AUTHORED["d1"], BUSY["d1"]],
        "calc_ir": None, "calc_all": [], "calc_mine": [],
        # The publisher's evidence for `full`: the one grant without a condition, on the guest's `role` row.
        "evidence": [{"kind": "person", "rule": "everyone", "ground": ["role", "guest"]}],
    }
    if calc:
        size = [(d, "1", "known", "") for d in ("d1", "d2")]
        w["complete"] |= {"calc__as_of": [], "calc__size": size}
        w["mine"] |= {"calc__as_of": [], "calc__size": size[:1]}
        w |= {"full": {"person", "role", "calc__as_of"}, "calc_ir": json.loads(json.dumps(CALC)),
              "calc_all": list(SIZE.values()), "calc_mine": [SIZE["d1"]]}
    return w


def snapshot(rows) -> bytes:
    return rows if isinstance(rows, bytes) else json.dumps([{"key": list(r)} for r in sorted(rows)]).encode()


def checked(w) -> tuple[frozenset, set]:
    """(the relations the checker finds full, its findings as (reason, relation))."""
    full, findings = access.check_role(
        "guest", {r: snapshot(rs) for r, rs in w["complete"].items()}, {r: snapshot(rs) for r, rs in w["mine"].items()},
        w["full"], COLUMNS, KINDS, {}, w.get("doc", DOC), w["calc_ir"], w["instances"], w["calc_all"], w["calc_mine"],
        w["witnesses"], claimed_evidence=w.get("evidence"))
    assert all(f["severity"] == "error" for f in findings)
    return full, {(f["reason"], f.get("relation")) for f in findings}


@pytest.mark.parametrize("calc", [False, True])
def test_a_correct_filter_passes(calc):
    w = world(calc)
    assert checked(w) == (frozenset(w["full"]), set())


def unreadable_row(w):  # a document that was not granted
    w["mine"]["doc"].append(("d2",))


def dropped_row(w):  # the filter lost a row the role may read
    w["mine"]["doc__author"] = []


def ungranted_person(w):  # the read rules give every person, but may_read has no row for p2
    for rows in (w["complete"]["may_read"], w["mine"]["may_read"]):
        rows.remove(("guest", "person", "p2"))
    w["instances"].remove(EVERYONE[1])
    w["witnesses"].remove(EVERYONE[1])


def unnamed(w):
    """The same world for a role the pack's facts do not name: `everyone` derives nothing for it."""
    for rows in (w["complete"], w["mine"]):
        rows["role"] = [("other",)]
        rows["may_read"] = [("guest", "doc", "d1")]
    w["instances"] = [i for i in w["instances"] if i not in EVERYONE]
    w["witnesses"] = [i for i in w["witnesses"] if i not in EVERYONE]
    w["evidence"] = []


def unnamed_role_in_full(w):  # the filter still gives every person, in full, to a role the pack does not name
    unnamed(w)
    w["evidence"] = None  # what the scope finds here; the evidence has a case of its own


def forged_ground(w):  # the filter claims documents in full on a mapping row the complete snapshots do not hold
    w["evidence"] = [*w["evidence"], {"kind": "doc", "rule": "granted", "ground": ["role__capability", "guest", "read"]}]


def lost_ground(w):  # the filter names no ground for a kind the role reads in full
    w["evidence"] = []


def relation_without_kinds(w):  # a base relation the schema gives no kind per column for
    w["complete"]["stray"] = [("x",)]


def wider_scope(w):  # the filter claims `doc` in full, so a negation over it would pass
    w["full"] = w["full"] | {"doc"}


def underivable_row(w):  # authored(p1, d2) rests on a document the role does not read
    w["mine"]["authored"].append(("p1", "d2"))


def negation_outside_scope(w):  # idle(p2) negates busy, which reaches documents the role does not read
    w["mine"]["idle"] = [("p2",)]
    w["witnesses"].append(IDLE)


def dropped_conclusion(w):  # the role reads the premise, and the filter lost the conclusion
    w["mine"]["authored"] = []
    w["witnesses"].remove(AUTHORED["d1"])


def other_proof(w):  # busy(p1) by the document the role does not read: a proof it cannot use
    w["witnesses"][w["witnesses"].index(BUSY["d1"])] = BUSY["d2"]


def missing_proof(w):
    w["witnesses"].remove(GRANTED)


def broken_snapshot(w):
    w["mine"]["person"] = b"[{"


def hidden_subject(w):  # the calculation of a document the role does not read
    w["mine"]["calc__size"].append(("d2", "1", "known", ""))
    w["calc_mine"].append(SIZE["d2"])


def partial_read(w):  # the calculation reads a relation the role reads only in part
    w["calc_ir"]["facts"][0]["table"] = "doc__author"


def dropped_calculation(w):
    w["mine"]["calc__size"] = []
    w["calc_mine"] = []


def dropped_calculation_witness(w):
    w["calc_mine"] = []


# (what the filter got wrong, with a calculation, the findings it must give, and whether those are all)
CASES = [
    (unreadable_row, False, {("not_readable", "doc")}, True),
    (dropped_row, False, {("readable_missing", "doc__author")}, False),
    (ungranted_person, False, {("full_not_readable", "person")}, False),
    (unnamed_role_in_full, False, {("full_mismatch", "person"), ("not_readable", "person"),
                                   ("not_readable", "doc__author"), ("not_derivable", "authored"),
                                   ("not_derivable", "busy"), ("choice_mismatch", None)}, True),
    (relation_without_kinds, False, {("no_columns", "stray")}, True),
    (forged_ground, False, {("evidence_mismatch", "may_read")}, True),
    (lost_ground, False, {("evidence_mismatch", "may_read")}, True),
    (wider_scope, False, {("full_mismatch", "doc")}, True),
    (underivable_row, False, {("not_derivable", "authored")}, True),
    (negation_outside_scope, False, {("not_derivable", "idle"), ("choice_mismatch", None)}, True),
    (dropped_conclusion, False, {("derivable_missing", "authored"), ("choice_mismatch", None)}, True),
    (other_proof, False, {("choice_mismatch", None)}, True),
    (missing_proof, False, {("choice_mismatch", None)}, True),
    (broken_snapshot, False, {("malformed_snapshot", "person")}, False),
    (hidden_subject, True, {("calc_not_visible", "calc__size"), ("calc_not_visible", None)}, False),
    (partial_read, True, {("calc_not_visible", "calc__size"), ("calc_not_visible", None)}, True),
    (dropped_calculation, True, {("calc_visible_missing", "calc__size"), ("calc_visible_missing", None)}, True),
    (dropped_calculation_witness, True, {("calc_visible_missing", None)}, True),
]


@pytest.mark.parametrize("change, calc, findings, exactly", CASES, ids=lambda v: getattr(v, "__name__", ""))
def test_the_checker_finds_what_the_filter_got_wrong(change, calc, findings, exactly):
    w = world(calc)
    change(w)
    found = checked(w)[1]
    assert found == findings if exactly else findings <= found


def test_a_role_the_pack_does_not_name_reads_nothing_in_full():
    """RV-S10: `may_read(r, "person", x) :- role(r), person(x).` derives no row for a role without its own
    `role` row, so it gives that role no person and nothing in full. What it was granted by name stays."""
    w = world()
    unnamed(w)
    w["mine"] |= {"person": [], "doc__author": [], "authored": [], "busy": []}
    w["witnesses"] = [GRANTED]
    w["full"] = {"role"}  # `role` holds no element here (no kind per column), so every role reads it
    assert checked(w) == (frozenset({"role"}), set())


def per_person(table: str) -> dict:
    """The world with a calculation per person, a kind the guest reads in full, that reads `table`."""
    people = [(p, "1", "known", "") for p in ("p1", "p2")]
    proofs = [{"conclusion": ref("calc__size", *row), "rule": "size", "version": "v", "premises": []} for row in people]
    sees = table == "person"  # the guest reads every person, and of doc__author only the rows of its documents
    w = world()
    w["complete"] |= {"calc__as_of": [], "calc__size": people}
    w["mine"] |= {"calc__as_of": [], "calc__size": people if sees else []}
    w["calc_ir"] = json.loads(json.dumps(CALC)) | {"subject": "person",
                                                   "rules": [{"rule": "size", "view": "calc__size", "versions": ["size@v"]}]}
    w["calc_ir"]["facts"][0]["table"] = table
    w |= {"calc_all": proofs, "calc_mine": proofs if sees else [],
          "full": {"person", "role", "calc__as_of"} | ({"calc__size"} if sees else set())}
    return w


def test_a_calculation_view_is_full_only_when_every_relation_it_reads_is():
    """RV-S26 (O8): full means a missing row is "none". The subject kind is full for the guest both times. Where
    the calculation reads a relation the guest reads in part, the guest has no row of the view and the view is not
    full; a filter that still claims it is red. Where every source is full, so is the view, with every row."""
    w = per_person("doc__author")
    assert w["mine"]["calc__size"] == [] and "calc__size" not in w["full"]
    assert checked(w) == (frozenset(w["full"]), set())
    w["full"] = w["full"] | {"calc__size"}
    assert checked(w) == (frozenset({"person", "role", "calc__as_of"}), {("full_mismatch", "calc__size")})
    w = per_person("person")
    assert w["mine"]["calc__size"] == w["complete"]["calc__size"] and "calc__size" in w["full"]
    assert checked(w) == (frozenset(w["full"]), set())


def test_the_scope_is_the_checkers_own():
    """The role's proofs are checked against the `full` the checker derives, whatever the filter claims."""
    w = world()
    wider_scope(w)
    assert checked(w)[0] == frozenset({"person", "role"})


def test_every_reason_of_the_role_check_is_reached():
    """A reason check_role can give and no case here plants would be an untested check."""
    source = Path(access.__file__).read_text(encoding="utf-8")
    reached = {reason for _, _, findings, _ in CASES for reason, _ in findings}
    assert set(re.findall(r'"reason": "([a-z_]+)"', source)) <= reached


# Roles in two layers (B19): the read rules grant documents to every role the pack maps to the capability `read`,
# not to a role by name. The mapping is a fact, as std-access declares it (`role__capability`), and the guest is
# mapped as deploy/profiles/edge.yaml declares its readers (`may_read`, which reads). The rule over the capability
# gives documents in full, with the mapping row as its ground.
READERS = rule("readers", "1", ("may_read", "?r", "doc", "?x"), atom("role__capability", "?r", "read"), atom("doc", "?x"))
TWO_LAYERS = DOC | {"rules": [READERS if r["id"] == "granted" else r for r in DOC["rules"]]}
BY_CAPABILITY = {d: instance("readers", ("may_read", "guest", "doc", d), {"?r": "guest", "?x": d},
                             ("role__capability", "guest", "read"), ("doc", d)) for d in ("d1", "d2")}


def two_layers() -> dict:
    """The world with documents read through the capability: every row is the guest's, every relation full."""
    w = world()
    complete = w["complete"] | {"role__capability": [("guest", "read")], "grant": [],
                                "may_read": [*w["complete"]["may_read"], ("guest", "doc", "d2")]}
    w["complete"], w["mine"] = complete, dict(complete)
    w["instances"] = [*EVERYONE, *BY_CAPABILITY.values(), *AUTHORED.values(), *BUSY.values(), IDLE]
    w["witnesses"] = [*EVERYONE, *BY_CAPABILITY.values(), *AUTHORED.values(), BUSY["d1"], IDLE]
    w["full"] = set(complete)
    w["doc"] = TWO_LAYERS
    w["evidence"] = [{"kind": "doc", "rule": "readers", "ground": ["role__capability", "guest", "read"]},
                     {"kind": "person", "rule": "everyone", "ground": ["role", "guest"]}]
    return w


def test_a_capability_gives_a_kind_in_full_with_its_mapping_row_as_evidence():
    """A total or an absence over documents counts for the guest (idle negates busy, which reaches every
    authorship) only because the guest reads every document in full, on the mapping row the checker found."""
    w = two_layers()
    assert checked(w) == (frozenset(w["full"]), set())
    chains = {k: (k,) for k in KINDS}
    assert access.grants(TWO_LAYERS, "guest", chains, True, {"read"}) == w["evidence"]
    assert access.full_kinds(TWO_LAYERS, "guest", chains, True, {"read"}) == KINDS
    assert access.full_kinds(TWO_LAYERS, "guest", chains, True) == {"person"}


def test_without_the_mapping_row_the_capability_gives_nothing_in_full():
    """The same rules for a role the pack maps to no capability: the rule derives no document for it, so it reads
    none, nothing over documents is complete for it, and a filter that still hands over the two-layer view is red."""
    w = two_layers()
    w["complete"] = w["complete"] | {"role__capability": [("other", "read")],
                                     "may_read": [r for r in w["complete"]["may_read"] if r[1] != "doc"]}
    w["instances"] = [i for i in w["instances"] if i not in BY_CAPABILITY.values()]
    full, found = checked(w)
    assert full == frozenset({"person", "role", "role__capability"})
    assert found == {("evidence_mismatch", "may_read"), ("not_readable", "doc"), ("not_readable", "doc__author"),
                     ("not_readable", "role__capability"), ("readable_missing", "role__capability"),
                     ("not_derivable", "authored"), ("not_derivable", "busy"),
                     ("not_derivable", "idle"), ("not_derivable", "may_read"), ("choice_mismatch", None),
                     ("full_mismatch", "authored, busy, doc, doc__author, grant, idle, may_read")}


def test_a_capability_named_by_a_variable_gives_nothing_in_full():
    """`role__capability(r, c)` with `c` free holds for any capability: that is a condition on the data, not a
    grant of the kind to a capability, so it gives no kind in full."""
    loose = rule("readers", "1", ("may_read", "?r", "doc", "?x"), atom("role__capability", "?r", "?c"), atom("doc", "?x"))
    doc = DOC | {"rules": [loose]}
    assert access.grants(doc, "guest", {k: (k,) for k in KINDS}, True, {"read"}) == []
