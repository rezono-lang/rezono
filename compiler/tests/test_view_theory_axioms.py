"""THV1 (#401): a strong axiom of a theory blocks publication when the violation reaches the theory only through a view.

Each case is a small domain that imports one standard theory pack as it is (std-order, std-part, std-time) and maps
its own kinds onto it with a view (docs/compiler.md, "Views that execute").
The lowering binds every rule that read a theory table to one relation that holds both the table and the view's
rows, the `@invariant`s included (`view_rules.bind`).
A row in an invariant relation is a red check and blocks publication, as the publisher counts it
(edge/publisher/rezono_publisher/batch.py); `red` below is that count.

Per axiom: a violation through the view gives the invariant's rows and blocks; the same rows in the theory's own
tables give the same rows; a control on the same view gives no row, while the view demonstrably supplied rows.
The expectations are written from the rows and dates themselves, not with the compiler.
"""
import datetime
import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import batch, modules, pack, rules as ir
from support import typed

pytest.importorskip("duckdb")

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / 'fixtures/minimal'
EPOCH = datetime.date(1970, 1, 1)

# Per theory: the domain's classes, its channel table and the view onto the theory.
ORDER = {
    'classes': {'Step': {'attributes': {'id': {'identifier': True},
                                        'leads_to': {'range': 'Step', 'multivalued': True},
                                        'level': {'range': 'integer'}}}},
    'kinds': ['step'], 'arrows': ['step.leads_to'],
    'view': {'theory': 'std-order',
             'kinds': [{'name': 'ordered', 'union': [{'populated_from': 'step'}]}],
             'attributes': [{'of': 'ordered', 'name': 'rank', 'populated_from': 'level'}],
             'arrows': [{'name': 'precedes', 'of': 'ordered',
                         'paths': [{'populated_from': 'step', 'steps': [{'slot': 'leads_to'}]}]}]}}
PART = {
    'classes': {'Component': {'attributes': {'id': {'identifier': True}, 'inside': {'range': 'Component'}}}},
    'kinds': ['component'], 'arrows': ['component.inside'],
    'view': {'theory': 'std-part',
             'kinds': [{'name': 'constituent', 'union': [{'populated_from': 'component'}]}],
             'arrows': [{'name': 'part_of', 'of': 'constituent',
                         'paths': [{'populated_from': 'component', 'steps': [{'slot': 'inside'}]}]}]}}
TIME = {
    'classes': {'Term': {'attributes': {'id': {'identifier': True}, 'opens': {'range': 'date'},
                                        'closes': {'range': 'date'}, 'calendar': {'range': 'Calendar'}}},
                'Calendar': {'attributes': {'id': {'identifier': True}}}},
    'kinds': ['term', 'calendar'], 'arrows': ['term.calendar'],
    'view': {'theory': 'std-time',
             'kinds': [{'name': 'interval', 'union': [{'populated_from': 'term'}]},
                       {'name': 'axis', 'union': [{'populated_from': 'calendar'}]}],
             'attributes': [{'of': 'interval', 'name': 'start', 'populated_from': 'opens', 'reading': 'days'},
                            {'of': 'interval', 'name': 'end', 'populated_from': 'closes', 'reading': 'days'}],
             'arrows': [{'name': 'on_axis', 'of': 'interval',
                         'paths': [{'populated_from': 'term', 'steps': [{'slot': 'calendar'}]}]}]}}


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding='utf-8', newline='\n')


def domain_pack(root, case):
    """A domain that imports the standard theory pack as it is (a copy, so the pin is its own hash) and reads it
    through the view of `case`."""
    name = case['view']['theory']
    theory = Path(shutil.copytree(REPO / 'packs' / name, root / name))
    domain = Path(shutil.copytree(FIXTURE, root / 'domain'))
    write(domain / 'schema/minimal.yaml', {'id': f'https://rezono.example/thv1-{name}', 'name': 'domain',
          'imports': ['linkml:types'], 'default_range': 'string', 'annotations': {'layer': 'facts'},
          'classes': case['classes']})
    write(domain / 'pack.yaml', {'name': 'domain', 'version': '0', 'default_language': 'nl',
          'imports': [{'name': name, 'path': f'../{name}', 'sha256': modules.pack_hash(theory)}]})
    write(domain / 'channels.yaml', {'kinds': [{'kind': k, 'shape': 'rect'} for k in case['kinds']],
          'arrows': [{'arrow': a, 'dash': 'none'} for a in case['arrows']]})
    write(domain / 'labels/nl.yaml', {})
    write(domain / 'views.yaml', {'format': 'rezono.views/1', 'views': [json.loads(json.dumps(case['view']))]})
    return domain


def program(tmp_path_factory, case):
    return ir.load(pack.read(domain_pack(tmp_path_factory.mktemp(case['view']['theory']), case)).rules)


@pytest.fixture(scope='module')
def order(tmp_path_factory):
    return program(tmp_path_factory, ORDER)


@pytest.fixture(scope='module')
def part(tmp_path_factory):
    return program(tmp_path_factory, PART)


@pytest.fixture(scope='module')
def time(tmp_path_factory):
    return program(tmp_path_factory, TIME)


def run(prog, data):
    con = batch.connect(prog, {n: typed(prog, n, data.get(n, [])) for n, r in prog.relations.items() if r.role == 'base'},
                        threads=1)
    try:
        con.execute("SET memory_limit = '256MB'")
        batch.compute(con, prog)
        return batch.read(con, prog, list(prog.relations))
    finally:
        con.close()


def red(prog, rows):
    """The invariant relations with a row: each is a red check, and a red check blocks publication."""
    return {name for name, rel in prog.relations.items() if rel.invariant and rows.get(name)}


def reads(prog, relation):
    """The relations the rules of `relation` read."""
    return {b.atom.relation for r in prog.rules_for(relation) for b in r.body}


# std-order: precedes is a strict partial order, and a rank increases along it.

def steps(edges, levels=()):
    """Through the view: steps, the steps each leads to, and a level for some."""
    ids = sorted({x for e in edges for x in e} | {s for s, _ in levels})
    return {'step': [(s,) for s in ids], 'step__leads_to': list(edges),
            'step__level': [(s, str(n)) for s, n in levels]}


def ordered(edges, ranks=()):
    """The same rows in std-order's own tables."""
    ids = sorted({x for e in edges for x in e} | {s for s, _ in ranks})
    return {'ordered': [(s,) for s in ids], 'ordered__precedes': list(edges),
            'ordered__rank': [(s, str(n)) for s, n in ranks]}


def test_the_order_axioms_read_the_relation_that_holds_the_view(order):
    assert {n for n, r in order.relations.items() if r.invariant} >= {'order_cycle', 'rank_conflict'}
    assert reads(order, 'before') == {'std_order_ordered_precedes', 'before'}
    assert reads(order, 'rank_conflict') == {'before', 'std_order_ordered_rank'}


def test_a_cycle_through_the_view_breaks_the_order_and_blocks(order):
    edges = [('a', 'b'), ('b', 'c'), ('c', 'a')]
    rows = run(order, steps(edges))
    assert rows['order_cycle'] == {('a',), ('b',), ('c',)} and red(order, rows) == {'order_cycle'}
    assert run(order, ordered(edges))['order_cycle'] == rows['order_cycle']


def test_a_step_that_leads_to_itself_is_a_cycle(order):
    rows = run(order, steps([('a', 'a')]))
    assert rows['order_cycle'] == {('a',)} and red(order, rows) == {'order_cycle'}


def test_a_rank_against_the_order_through_the_view_conflicts_and_blocks(order):
    """a -> b -> c with level 9 for a, none for b and 2 for c: the conflict runs through the step without a level."""
    edges, levels = [('a', 'b'), ('b', 'c')], [('a', 9), ('c', 2)]
    rows = run(order, steps(edges, levels))
    assert rows['rank_conflict'] == {('a', 'c')} and red(order, rows) == {'rank_conflict'}
    assert run(order, ordered(edges, levels))['rank_conflict'] == rows['rank_conflict']


def test_an_equal_rank_along_the_order_conflicts_too(order):
    rows = run(order, steps([('a', 'b')], [('a', 4), ('b', 4)]))
    assert rows['rank_conflict'] == {('a', 'b')} and red(order, rows) == {'rank_conflict'}


def test_control_an_order_without_cycle_and_with_increasing_ranks_blocks_nothing(order):
    edges, levels = [('a', 'b'), ('b', 'c')], [('a', 1), ('c', 3)]
    rows = run(order, steps(edges, levels))
    assert rows['before'] == {('a', 'b'), ('b', 'c'), ('a', 'c')}   # the view supplied the order
    assert rows['std_order_ordered_rank'] == {('a', '1'), ('c', '3')}
    assert rows['order_cycle'] == rows['rank_conflict'] == set() and red(order, rows) == set()
    assert red(order, run(order, ordered(edges, levels))) == set()


def test_a_cycle_closed_half_by_the_view_and_half_by_the_theory_table_is_one_cycle(order):
    """The view and the theory's own table meet in one relation, so neither half alone hides the cycle."""
    data = steps([('a', 'b')]) | {'ordered': [('a',), ('b',)], 'ordered__precedes': [('b', 'a')]}
    rows = run(order, data)
    assert rows['order_cycle'] == {('a',), ('b',)} and red(order, rows) == {'order_cycle'}


# std-part: part_of is irreflexive and acyclic.

def components(inside):
    """Through the view: components, and the component each lies inside."""
    ids = sorted({x for e in inside for x in e})
    return {'component': [(c,) for c in ids], 'component__inside': list(inside)}


def constituents(part_of):
    """The same rows in std-part's own tables."""
    ids = sorted({x for e in part_of for x in e})
    return {'constituent': [(c,) for c in ids], 'constituent__part_of': list(part_of)}


def test_the_part_axiom_reads_the_relation_that_holds_the_view(part):
    assert part.relations['part_cycle'].invariant
    assert reads(part, 'within') == {'std_part_constituent_part_of', 'within'}


def test_a_part_cycle_through_the_view_breaks_the_forest_and_blocks(part):
    inside = [('x', 'y'), ('y', 'z'), ('z', 'x')]
    rows = run(part, components(inside))
    assert rows['part_cycle'] == {('x',), ('y',), ('z',)} and red(part, rows) == {'part_cycle'}
    assert run(part, constituents(inside))['part_cycle'] == rows['part_cycle']


def test_a_component_inside_itself_is_a_part_cycle(part):
    rows = run(part, components([('x', 'x')]))
    assert rows['part_cycle'] == {('x',)} and red(part, rows) == {'part_cycle'}


def test_control_a_tree_of_components_blocks_nothing(part):
    inside = [('wheel', 'axle'), ('axle', 'frame')]
    rows = run(part, components(inside))
    assert rows['within'] == {('wheel', 'axle'), ('axle', 'frame'), ('wheel', 'frame')}   # the view supplied the parts
    assert rows['outermost'] == {('wheel', 'frame'), ('axle', 'frame')}
    assert rows['part_cycle'] == set() and red(part, rows) == set()
    assert red(part, run(part, constituents(inside))) == set()


# std-time: an interval is proper; its dates are read with `days`.

def count(day):
    return (day - EPOCH).days


def terms(spans):
    """Through the view: terms on one calendar, (id, opens, closes)."""
    return {'calendar': [('c',)], 'term': [(t,) for t, _, _ in spans], 'term__calendar': [(t, 'c') for t, _, _ in spans],
            'term__opens': [(t, a.isoformat()) for t, a, _ in spans],
            'term__closes': [(t, b.isoformat()) for t, _, b in spans]}


def intervals(spans):
    """The same rows in std-time's own tables, the dates as day counts."""
    return {'axis': [('c',)], 'interval': [(t,) for t, _, _ in spans], 'interval__on_axis': [(t, 'c') for t, _, _ in spans],
            'interval__start': [(t, str(count(a))) for t, a, _ in spans],
            'interval__end': [(t, str(count(b))) for t, _, b in spans]}


def inverted(spans):
    """From the dates themselves: an interval is inverted when it closes on or before the day it opens."""
    return {(t,) for t, a, b in spans if b <= a}


def test_the_interval_axiom_reads_the_relations_that_hold_the_view(time):
    assert time.relations['interval_inverted'].invariant
    assert reads(time, 'interval_inverted') == {'std_time_interval_start', 'std_time_interval_end'}


SPANS = [('back', datetime.date(2024, 3, 1), datetime.date(2024, 2, 1)),
         ('year', datetime.date(2025, 1, 1), datetime.date(2024, 12, 31)),     # one day back, across a year
         ('leap', datetime.date(2024, 3, 1), datetime.date(2024, 2, 29)),      # one day back, across a leap day
         ('empty', datetime.date(2024, 5, 1), datetime.date(2024, 5, 1))]      # closes on the day it opens


def test_an_inverted_interval_read_with_days_through_the_view_blocks(time):
    rows = run(time, terms(SPANS))
    assert rows['interval_inverted'] == inverted(SPANS) == {('back',), ('year',), ('leap',), ('empty',)}
    assert red(time, rows) == {'interval_inverted'}
    assert run(time, intervals(SPANS))['interval_inverted'] == rows['interval_inverted']


def test_control_proper_intervals_read_with_days_block_nothing(time):
    spans = [('month', datetime.date(2024, 2, 1), datetime.date(2024, 3, 1)),
             ('year', datetime.date(2024, 12, 31), datetime.date(2025, 1, 1)),
             ('leap', datetime.date(2024, 2, 28), datetime.date(2024, 2, 29))]
    rows = run(time, terms(spans))
    assert rows['std_time_interval_start'] == {(t, str(count(a))) for t, a, _ in spans}   # the view supplied the days
    assert rows['interval_inverted'] == inverted(spans) == set() and red(time, rows) == set()
    assert red(time, run(time, intervals(spans))) == set()
