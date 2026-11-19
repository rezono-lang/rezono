"""A theory kind populated from several source kinds, from decisions/view-source-unions.md.

The theory element keeps the plain source identifier, so rules join it with the source kinds directly.
Identifiers of different branches must be disjoint: a shared identifier is an integrity violation, not a silent
merge. The expected rows are the set union of the branch facts, written out by hand.
"""

import pytest
from rezono_compiler import view_rules
from test_view_rules import NAMES, model, run


def two_roots(schema):
    schema['classes']['Other'] = {'attributes': {'id': {'identifier': True}}}


def union(view):
    view['kinds'][0]['union'].append({'populated_from': 'other'})


def facts(*others):
    return {'parent': [('a',), ('b',)], 'other': [(o,) for o in others],
            'link': [('l1',)], 'link__left': [('l1', 'a')], 'link__right': [('l1', 'b')]}


@pytest.mark.xfail(strict=True, raises=view_rules.ViewRuleError,
                   reason="Lower a theory kind with several source branches in compiler/rezono_compiler/view_rules.py: "
                          "one rule per branch into the theory relation with the plain identifier, and one invariant "
                          "relation holding identifiers that occur in two branches, as "
                          "decisions/view-source-unions.md fixes. Compiler only. This test supersedes the union "
                          "refusal that test_view_rules.py used to assert.")
def test_a_theory_kind_unions_disjoint_source_kinds(tmp_path):
    d, t, view, program = model(tmp_path, domain_change=two_roots, view_change=union)
    lowered = view_rules.lower(view, d, t, program, NAMES, namespace='vmap')
    invariants = [name for name, relation in lowered.relations.items() if relation.invariant]
    assert len(invariants) == 1, invariants

    rows, witnesses = run(lowered, facts('c', 'd'))
    assert rows['mapped_node'] == {('a',), ('b',), ('c',), ('d',)}
    assert rows['mapped_next'] == {('a', 'b')}  # the arrow's path starts at the parent branch only
    assert rows[invariants[0]] == set()
    assert witnesses  # every theory row keeps a rule witness back to its source branch

    # The same identifier in both branches is a violation naming it, never one merged element.
    rows, _ = run(lowered, facts('b', 'd'))
    assert rows[invariants[0]] == {('b',)}
