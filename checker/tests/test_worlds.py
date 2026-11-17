"""AUD-C2: the checker holds the open and the closed world itself (decision W6), at negation and aggregation.
It derives each relation's world from the rule IR, so a proof that negates an open relation outside an
`absence` relation is refused even when the compiler let it through."""

import copy

import pytest

from rezono_checker.rules import check_worlds, load_rules


def relation(name, role, *columns, **flags):
    return {"name": name, "role": role, "key": [{"name": c, "type": "string"} for c in columns], **flags}


def rule(rid, head, body=(), aggregates=(), stratum="0"):
    return {"id": rid, "stratum": stratum, "head": {"relation": head, "terms": ["?x"]},
            "body": [{"relation": r, "terms": ["?x"], "polarity": p, "stratum": s} for r, p, s in body],
            "aggregates": list(aggregates)}


# `host` is a closed kind, `owner` an open attribute table: a missing owner is unknown, not "no owner".
BASE = [relation("host", "base", "id"), relation("owner", "base", "id", world="open")]


def doc(*rules, derived=()):
    return {"format": "rede.rules/1", "relations": BASE + list(derived), "rules": list(rules)}


ORPHAN = rule("orphan", "orphan", [("host", "positive", "0"), ("owner", "negative", "0")], stratum="1")


def test_negating_an_open_relation_needs_absence():
    with pytest.raises(ValueError, match="owner is open"):
        load_rules(doc(ORPHAN, derived=[relation("orphan", "derived", "id", world="closed")]))
    load_rules(doc(ORPHAN, derived=[relation("orphan", "derived", "id", world="closed", absence=True)]))


def test_aggregating_over_an_open_relation_needs_absence():
    count = rule("owners", "owners", [("host", "positive", "0")], [
        {"relation": "owner", "terms": ["?x"], "function": "count", "as": "?n", "stratum": "0"}], stratum="1")
    count["head"]["terms"] = ["?x", "?n"]
    owners = relation("owners", "derived", "id", "n", world="closed")
    with pytest.raises(ValueError, match="owner is open"):
        load_rules(doc(count, derived=[owners]))
    load_rules(doc(count, derived=[{**owners, "absence": True}]))


def test_open_spreads_along_positive_literals_whatever_the_declaration_says():
    """`owned` reads `owner` positively, so it is open. Declaring it closed does not let `unowned` negate it."""
    owned = rule("owned", "owned", [("owner", "positive", "0")])
    unowned = rule("unowned", "unowned", [("host", "positive", "0"), ("owned", "negative", "0")], stratum="1")
    honest = relation("owned", "derived", "id", world="open")
    with pytest.raises(ValueError, match="owned is open"):
        load_rules(doc(owned, unowned, derived=[honest, relation("unowned", "derived", "id", world="closed")]))
    with pytest.raises(ValueError, match="declared closed, but its rules make it open"):
        check_worlds(doc(owned, derived=[{**honest, "world": "closed"}]), load_rules(doc(owned, derived=[honest])))


def test_absence_stops_open_and_is_only_on_derived_relations():
    gap = rule("gap", "gap", [("host", "positive", "0"), ("owner", "negative", "0")], stratum="1")
    gaps = relation("gap", "derived", "id", world="closed", absence=True)
    worlds = check_worlds(doc(gap, derived=[gaps]), load_rules(doc(gap, derived=[gaps])))
    assert worlds == {"host": "closed", "owner": "open", "gap": "closed"}
    bad = doc(gap, derived=[gaps])
    bad["relations"][1] = {**bad["relations"][1], "absence": True}
    with pytest.raises(ValueError, match="on a derived relation"):
        load_rules(bad)


def test_an_absence_label_must_be_earned():
    """Review of #458: a plain copy of an open relation labelled absence would be closed, and negating it would
    pass. Each rule of an absence relation negates an open relation, aggregates over one, or reads another
    absence relation."""
    copy_ = rule("copied_owner", "copied_owner", [("owner", "positive", "0")])
    unowned = rule("unowned", "unowned", [("host", "positive", "0"), ("copied_owner", "negative", "0")], stratum="1")
    copied = relation("copied_owner", "derived", "id", world="closed", absence=True)
    with pytest.raises(ValueError, match="a rule of an absence relation"):
        load_rules(doc(copy_, unowned, derived=[copied, relation("unowned", "derived", "id", world="closed")]))
    # Valid: negating the open relation, and a second absence relation that reads the first.
    gap = rule("gap", "gap", [("host", "positive", "0"), ("owner", "negative", "0")], stratum="1")
    gap_copy = rule("gap_copy", "gap_copy", [("gap", "positive", "1")], stratum="1")
    gaps = relation("gap", "derived", "id", world="closed", absence=True)
    worlds = check_worlds(doc(gap, gap_copy, derived=[gaps, {**gaps, "name": "gap_copy"}]),
                          load_rules(doc(gap, gap_copy, derived=[gaps, {**gaps, "name": "gap_copy"}])))
    assert worlds["gap"] == worlds["gap_copy"] == "closed"


def test_an_outcome_is_closed():
    reads = rule("state", "state", [("owner", "positive", "0")])
    reads["head"]["terms"] = ["?x", "known", ""]
    state = relation("state", "derived", "host", "state", "reason", world="open", outcome="host")
    with pytest.raises(ValueError, match="an outcome is closed"):
        load_rules(doc(reads, derived=[state]))


def test_the_minimal_format_has_no_worlds():
    minimal = copy.deepcopy(doc(ORPHAN))
    del minimal["format"], minimal["relations"]
    load_rules(minimal)
