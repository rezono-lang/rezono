"""Roles in two layers (B19, seam S10): a read rule over a generic capability, with its completeness evidence.

std-access maps a role to generic capabilities as facts (`role__capability`). A read rule
`may_read(r, "K", x) :- role__capability(r, "c"), K(x).` gives kind K in full to every role mapped to `c`, so
totals and absences over K stay the role's. The publisher names the row each grant rests on (`access.Full`), and
the checker derives the same evidence again from the complete rows and requires it equal.

The roles are those of deploy/profiles/edge.yaml and mapped as it declares them: `viewer` reads (`may_read`),
`propose` reads and may also propose. `guest` is named by the pack and mapped to nothing. One small world,
written by hand; no role of any domain.
"""

import json

import pytest
from rezono_checker import access as checker_access
from rezono_publisher import access
from rezono_publisher.publish import snapshot

KINDS = {"node", "role"}
COLUMNS = {"node": ("node",), "role": ("role",), "role__capability": ("role", None)}
BUNDLE = {
    "kinds": [{"id": "node"}, {"id": "role"}],
    "attributes": [{"table": "role__capability", "kind": "role"}],
}
ROLES = ("guest", "propose", "viewer")
MAPPING = [("propose", "propose"), ("propose", "read"), ("viewer", "read")]


def lit(rel, *terms):
    return {"relation": rel, "terms": list(terms), "polarity": "positive", "stratum": 0}


def rule(rid, head, body, **extra):
    return {"id": rid, "stratum": 0, "head": {"relation": head[0], "terms": list(head[1:])}, "body": body, **extra}


def relation(name, role, arity):
    return {"name": name, "role": role, "key": [{"name": f"c{i}", "type": "string"} for i in range(arity)]}


RULES = {
    "format": "rezono.rules/1",
    "relations": [relation("node", "base", 1), relation("role", "base", 1), relation("role__capability", "base", 2),
                  relation("may_read", "derived", 3), relation("size", "derived", 1)],
    "rules": [
        rule("roles", ("may_read", "?r", "role", "?x"), [lit("role", "?r"), lit("role", "?x")]),
        rule("readers", ("may_read", "?r", "node", "?x"), [lit("role__capability", "?r", "read"), lit("node", "?x")]),
        rule("size", ("size", "?n"), [], aggregates=[{"relation": "node", "function": "count"}]),
    ],
}


def world(mapping=MAPPING, granted=None) -> dict:
    """Every row of the epoch: the nodes, the roles and their mapping, and the may_read rows the rules derive."""
    readers = sorted({r for r, c in mapping if c == "read"})
    may_read = [*((r, "role", x) for r in ROLES for x in ROLES),
                *((r, "node", n) for r in (readers if granted is None else granted) for n in ("n1", "n2"))]
    return {"node": [("n1",), ("n2",)], "role": [(r,) for r in ROLES], "role__capability": sorted(mapping),
            "may_read": sorted(may_read)}


def scope(rows, role):
    return access.Scope(rows, KINDS, {}, COLUMNS, RULES, role)


def total_over_nodes() -> dict:
    """A witness instance whose aggregate ranges over every node: a total."""
    return {"conclusion": {"relation": "size", "key": json.dumps(["2"])}, "rule_id": "size", "bindings": [],
            "premises": [], "aggregates": [{"relation": "node"}]}


def test_a_mapped_role_reads_the_kind_in_full_with_the_mapping_row_as_evidence():
    rows = world()
    s = scope(rows, "viewer")
    assert {"node", "role", "role__capability"} <= s.full
    assert s.full.evidence == (
        {"kind": "node", "rule": "readers", "ground": ["role__capability", "viewer", "read"]},
        {"kind": "role", "rule": "roles", "ground": ["role", "viewer"]},
    )
    assert s.usable(total_over_nodes(), {})  # a total over nodes is the viewer's


def test_an_unmapped_role_gets_no_kind_through_a_capability():
    """`guest` is a role of the pack and holds no capability: the rule derives no node for it, it reads the
    kind not in full, and a total over nodes is not its own."""
    s = scope(world(), "guest")
    assert "node" not in s.full
    assert [g["kind"] for g in s.full.evidence] == ["role"]
    assert not s.usable(total_over_nodes(), {})


def test_a_capability_the_data_does_not_cover_is_red():
    """The mapping gives `viewer` the capability, and a may_read row of one node is missing: the read rules and
    the data disagree, so the publication stops (`rezono:access`) instead of calling a part complete."""
    rows = world()
    rows["may_read"].remove(("viewer", "node", "n2"))
    with pytest.raises(access.Uncovered):
        scope(rows, "viewer")


@pytest.mark.parametrize("role", ROLES)
def test_the_checker_derives_the_same_evidence(role):
    """Two readings that share no code (test_checker_boundary.py): the checker's grants from the complete rows
    are the publisher's evidence, and a whole publication of the role passes the checker's role check."""
    rows = world()
    readable, sees, full = access.for_role(rows, KINDS, {}, COLUMNS, RULES, [], role)
    chains = {k: (k,) for k in KINDS}
    capabilities = {c for r, c in rows["role__capability"] if r == role}
    assert list(full.evidence) == checker_access.grants(RULES, role, chains, True, capabilities)
    complete = {rel: snapshot(rs) for rel, rs in rows.items()}
    mine = {rel: snapshot(rs) for rel, rs in readable.items()}
    found, findings = checker_access.check_role(role, complete, mine, full, BUNDLE,
                                                RULES, witnesses=sees["witnesses"],
                                                claimed_evidence=full.evidence)
    assert (found, findings) == (full, [])
    forged = [*full.evidence, {"kind": "node", "rule": "readers", "ground": ["role__capability", role, "administer"]}]
    _, findings = checker_access.check_role(role, complete, mine, full, BUNDLE,
                                            RULES, witnesses=sees["witnesses"],
                                            claimed_evidence=forged)
    assert [f["reason"] for f in findings] == ["evidence_mismatch"]
