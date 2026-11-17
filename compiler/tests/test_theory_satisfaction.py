"""The satisfaction test (M3 of #314; docs/theories.md, step 4), per theory, on a neutral domain.

Each case is a small domain with words of its own that imports a standard theory pack as it is and reads it through
a view (docs/compiler/schema-operations.md, "Views that execute"). A case gives a strategy for the domain's
instances, the translation of an instance into the theory's tables written by hand from the view (a join over the
domain's rows, not the compiler's lowering), and the theory's own reference. For every instance
`satisfaction.satisfied` holds: the view supplies exactly the translated rows, and the theory concludes through
the view what it concludes on them when compiled on its own. The reference agrees with both, so each axiom holds
or the test names the rows that break it. Soufflé agrees on the lowered program, and a view with its path reversed
is a failing control.
A later theory joins with one more entry in CASES. The test domains' own views, on their own facts, are in
examples/test_theory_views.py; that the axioms block publication through a view is test_view_theory_axioms.py.
"""
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import satisfaction
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from rede_compiler import modules, pack
from rede_compiler import rules as ir
from test_theory_order import reference as order_reference

pytest.importorskip("duckdb")

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / 'fixtures/minimal'


@dataclass(frozen=True)
class Case:
    """One theory read by a neutral domain: the domain's classes and channel table, the view, a strategy for one
    instance, the instance as the domain's rows and as the theory's rows (each under an id prefix, so the
    instances of one engine run do not meet), and the theory's conclusions from its own rows."""
    theory: str
    classes: dict
    kinds: list
    arrows: list
    view: dict
    instance: st.SearchStrategy
    rows: Callable[[object, str], dict]
    translate: Callable[[object, str], dict]
    reference: Callable[[dict], dict]


# std-order: items lie in groups and carry a level; a link leads from the item at its tail to the item at its head.
# The view reads an item as ordered, its group as its scale, its level as its rank, and precedes as the path
# item -> (the link whose tail it is) -> head: the shape of a lex specialis reading, an inverse step then a step.
NODES = st.sampled_from('abcdef')
ORDER_INSTANCE = st.tuples(
    st.lists(st.tuples(st.one_of(st.none(), NODES), st.one_of(st.none(), NODES)), max_size=10),   # links
    st.dictionaries(NODES, st.integers(-3, 3), max_size=6),                                       # levels
    st.dictionaries(NODES, st.sampled_from(['g', 'h']), max_size=6))                              # groups


def order_items(instance):
    links, levels, groups = instance
    return sorted({n for link in links for n in link if n} | set(levels) | set(groups))


def order_rows(instance, p):
    links, levels, groups = instance
    return {'item': [(p + n,) for n in order_items(instance)],
            'group': [(p + g,) for g in sorted(set(groups.values()))],
            'link': [(f'{p}l{i}',) for i in range(len(links))],
            'link__tail': [(f'{p}l{i}', p + t) for i, (t, _) in enumerate(links) if t],
            'link__head': [(f'{p}l{i}', p + h) for i, (_, h) in enumerate(links) if h],
            'item__level': [(p + n, str(v)) for n, v in sorted(levels.items())],
            'item__group': [(p + n, p + g) for n, g in sorted(groups.items())]}


def order_translate(instance, p):
    """By hand, from the view: precedes joins a link's tail with its head; a link without either gives none."""
    links, levels, groups = instance
    return {'ordered': {(p + n,) for n in order_items(instance)},
            'scale': {(p + g,) for g in groups.values()},
            'ordered__precedes': {(p + t, p + h) for t, h in links if t and h},
            'ordered__rank': {(p + n, v) for n, v in levels.items()},
            'ordered__on_scale': {(p + n, p + g) for n, g in groups.items()}}


ORDER = Case(
    theory='std-order',
    classes={'Item': {'attributes': {'id': {'identifier': True}, 'group': {'range': 'Group'},
                                     'level': {'range': 'integer'}}},
             'Group': {'attributes': {'id': {'identifier': True}}},
             'Link': {'attributes': {'id': {'identifier': True}, 'tail': {'range': 'Item'}, 'head': {'range': 'Item'}}}},
    kinds=['item', 'group', 'link'], arrows=['item.group', 'link.tail', 'link.head'],
    view={'theory': 'std-order',
          'kinds': [{'name': 'ordered', 'union': [{'populated_from': 'item'}]},
                    {'name': 'scale', 'union': [{'populated_from': 'group'}]}],
          'attributes': [{'of': 'ordered', 'name': 'rank', 'populated_from': 'level'}],
          'arrows': [{'name': 'precedes', 'of': 'ordered',
                      'paths': [{'populated_from': 'item', 'steps': [{'slot': 'tail', 'inverse': True}, {'slot': 'head'}]}]},
                     {'name': 'on_scale', 'of': 'ordered',
                      'paths': [{'populated_from': 'item', 'steps': [{'slot': 'group'}]}]}]},
    instance=ORDER_INSTANCE, rows=order_rows, translate=order_translate,
    reference=lambda t: order_reference(t['ordered__precedes'], t['ordered__rank']))

CASES = {c.theory: c for c in [ORDER]}


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding='utf-8', newline='\n')


def domain_pack(root, case, view=None):
    """A domain that imports the standard theory pack as it is (a copy, so the pin is its own hash) and reads it
    through the view of `case`, or `view`."""
    theory = Path(shutil.copytree(REPO / 'packs' / case.theory, root / case.theory))
    domain = Path(shutil.copytree(FIXTURE, root / 'domain'))
    write(domain / 'schema/minimal.yaml', {'id': f'https://rezono.example/m3-{case.theory}', 'name': 'domain',
          'imports': ['linkml:types'], 'default_range': 'string', 'annotations': {'layer': 'facts'},
          'classes': case.classes})
    write(domain / 'pack.yaml', {'name': 'domain', 'version': '0', 'default_language': 'nl',
          'imports': [{'name': case.theory, 'path': f'../{case.theory}', 'sha256': modules.pack_hash(theory)}]})
    write(domain / 'channels.yaml', {'kinds': [{'kind': k, 'shape': 'rect'} for k in case.kinds],
          'arrows': [{'arrow': a, 'dash': 'none'} for a in case.arrows]})
    write(domain / 'labels/nl.yaml', {})
    write(domain / 'views.yaml', {'format': 'rede.views/1', 'views': [json.loads(json.dumps(view or case.view))]})
    return domain


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    """Per theory: the domain's directory and its program, read once (reading a pack takes most of a test's time)."""
    out = {}
    for name, case in CASES.items():
        domain = domain_pack(tmp_path_factory.mktemp(name), case)
        out[name] = domain, ir.load(pack.read(domain).rules)
    return out


def union(parts):
    out = {}
    for part in parts:
        for name, rows in part.items():
            out.setdefault(name, set()).update(rows)
    return out


def check(case, prog, instances):
    """Satisfaction on the instances together, each under a prefix of its own; the reference on the translated
    rows equals the theory's conclusions and names the same violations. Returns the result through the view."""
    data = union(case.rows(x, f'i{k}') for k, x in enumerate(instances))
    translated = union(case.translate(x, f'i{k}') for k, x in enumerate(instances))
    theory_dir = REPO / 'packs' / case.theory
    through = satisfaction.satisfied(prog, {n: sorted(r) for n, r in data.items()}, theory_dir, translated)
    want = {n: satisfaction.text(rows) for n, rows in case.reference(translated).items()}
    assert {n: through[n] for n in want} == want
    _, own = satisfaction.theory(theory_dir)
    assert satisfaction.violations(theory_dir, through) == {
        n: want[n] for n, r in sorted(own.relations.items()) if r.invariant and want[n]}
    return through


@pytest.mark.parametrize('name', sorted(CASES))
@settings(max_examples=10, deadline=None)
@given(data=st.data())
def test_property_the_theory_concludes_through_the_view_what_it_concludes_on_the_translated_instance(compiled, name, data):
    """200 instances in ten engine runs of twenty, cycles and conflicts included: through the view, the translated
    instance and the reference agree, on every table, conclusion and axiom."""
    case = CASES[name]
    check(case, compiled[name][1], data.draw(st.lists(case.instance, min_size=20, max_size=20)))


# A fixed instance per theory: one that breaks every axiom somewhere, and a part that holds them.
FIXED = {'std-order': (
    [('a', 'b'), ('b', 'c'), ('c', 'a'),                 # a cycle
     ('d', 'e'), ('d', 'e'), ('e', 'f'),                 # a chain, one link twice
     ('f', None), (None, 'd')],                          # a link without a head, one without a tail
    {'d': 3, 'f': 1, 'a': 0},                            # d before f, rank 3 then 1: a conflict across e
    {'a': 'g', 'd': 'h', 'e': 'h'})}


def test_a_fixed_instance_names_the_rows_that_break_each_axiom(compiled):
    through = check(ORDER, compiled['std-order'][1], [FIXED['std-order']])
    assert satisfaction.violations(REPO / 'packs/std-order', through) == {
        'order_cycle': {('i0a',), ('i0b',), ('i0c',)}, 'rank_conflict': {('i0d', 'i0f'), ('i0a', 'i0a')}}
    assert through['before'] >= {('i0d', 'i0e'), ('i0e', 'i0f'), ('i0d', 'i0f')}


@pytest.mark.skipif(shutil.which('souffle') is None, reason='Souffle is not installed; no oracle pass claimed')
@pytest.mark.parametrize('name', sorted(CASES))
def test_souffle_agrees_on_the_lowered_program_as_a_set(compiled, name, tmp_path):
    case = CASES[name]
    domain, prog = compiled[name]
    data = {n: sorted(r) for n, r in case.rows(FIXED[name], 'i0').items()}
    oracle = satisfaction.souffle_agrees(prog, data, domain, tmp_path)
    assert any(oracle[n] for n in satisfaction.theory(REPO / 'packs' / case.theory)[1].derived())


def test_the_control_fails_with_the_path_reversed(tmp_path):
    """The comparison is no tautology: the same translation refuses a view that reads the link from head to tail."""
    view = json.loads(json.dumps(ORDER.view))
    view['arrows'][0]['paths'][0]['steps'] = [{'slot': 'head', 'inverse': True}, {'slot': 'tail'}]
    prog = ir.load(pack.read(domain_pack(tmp_path, ORDER, view)).rules)
    chain = ([('a', 'b'), ('b', 'c')], {}, {})
    data = {n: sorted(r) for n, r in ORDER.rows(chain, 'i0').items()}
    with pytest.raises(AssertionError, match='other rows for ordered__precedes'):
        satisfaction.satisfied(prog, data, REPO / 'packs/std-order', ORDER.translate(chain, 'i0'))
