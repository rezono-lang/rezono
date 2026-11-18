"""A view with attribute maps executes, for the bounded execution profile (docs/compiler.md, "Views that execute").

A neutral theory (`spans`: a span covers a mark on its line) with rules of its own, and a domain whose terms have
dates and whose readings have a day written YYYYMMDD. The expectations are written here in Python, from the dates
themselves: not with the compiler's lowering, the engine's date function or the checker's.
"""
import datetime
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from hypothesis import example, given, settings, strategies as st

from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, explain, modules, pack, rules as ir
from support import typed
import souffle

FIXTURE = Path(__file__).parent / 'fixtures/minimal'
EPOCH = datetime.date(1970, 1, 1)
RULES = '''.decl first_stated(span: symbol)
first_stated(s) :- span__first(s, a).
// @absence
.decl first_not_recorded(span: symbol)
first_not_recorded(s) :- span__on(s, l), !first_stated(s).
.decl covers(span: symbol, mark: symbol)
covers(s, m) :- span__on(s, l), mark__on(m, l), mark__at(m, p), span__first(s, a), a <= p, span__last(s, b), p < b.
'''
VIEW = {'theory': 'spans',
        'kinds': [{'name': 'span', 'union': [{'populated_from': 'term'}]},
                  {'name': 'line', 'union': [{'populated_from': 'calendar'}]},
                  {'name': 'mark', 'union': [{'populated_from': 'reading'}]}],
        'attributes': [{'of': 'span', 'name': 'first', 'populated_from': 'starts', 'reading': 'days'},
                       {'of': 'span', 'name': 'last', 'populated_from': 'ends', 'reading': 'days'},
                       {'of': 'mark', 'name': 'at', 'populated_from': 'day', 'reading': 'yyyymmdd'}],
        'arrows': [{'name': 'on', 'of': 'span', 'paths': [{'populated_from': 'term', 'steps': [{'slot': 'calendar'}]}]},
                   {'name': 'on', 'of': 'mark', 'paths': [{'populated_from': 'reading', 'steps': [{'slot': 'calendar'}]}]}]}


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding='utf-8', newline='\n')


def packs(tmp_path, view=VIEW, change=None, theory_change=None):
    """The theory and the domain as pack directories; `change(view)` alters a copy of the view,
    `theory_change(classes)` the theory's classes."""
    theory = Path(shutil.copytree(FIXTURE, tmp_path / 'theory'))
    domain = Path(shutil.copytree(FIXTURE, tmp_path / 'domain'))
    whole = {'range': 'integer', 'annotations': {'world': 'open'}}
    classes = {
        'Span': {'attributes': {'id': {'identifier': True}, 'on': {'range': 'Line'}, 'first': dict(whole),
                                'last': dict(whole)}},
        'Line': {'attributes': {'id': {'identifier': True}}},
        'Mark': {'attributes': {'id': {'identifier': True}, 'on': {'range': 'Line'}, 'at': {'range': 'integer'}}}}
    if theory_change:
        theory_change(classes)
    write(theory / 'schema/minimal.yaml', {'id': 'https://rezono.example/spans', 'name': 'spans',
          'imports': ['linkml:types'], 'default_range': 'string', 'annotations': {'layer': 'facts'}, 'classes': classes})
    write(theory / 'pack.yaml', {'name': 'spans', 'version': '0', 'default_language': 'nl', 'theory': True})
    write(theory / 'channels.yaml', {'kinds': [{'kind': k, 'shape': 'rect'} for k in ('span', 'line', 'mark')],
          'arrows': [{'arrow': a, 'dash': 'none'} for a in ('span.on', 'mark.on')]})
    write(theory / 'labels/nl.yaml', {})
    (theory / 'rules').mkdir()
    (theory / 'rules/spans.dl').write_text(RULES, encoding='utf-8', newline='\n')
    write(domain / 'schema/minimal.yaml', {'id': 'https://rezono.example/domain', 'name': 'domain',
          'imports': ['linkml:types'], 'default_range': 'string', 'annotations': {'layer': 'facts'}, 'classes': {
        'Term': {'attributes': {'id': {'identifier': True}, 'starts': {'range': 'date'}, 'ends': {'range': 'date'},
                                'calendar': {'range': 'Calendar'}}},
        'Calendar': {'attributes': {'id': {'identifier': True}}},
        'Reading': {'attributes': {'id': {'identifier': True}, 'day': {'range': 'integer'},
                                   'calendar': {'range': 'Calendar'}}}}})
    write(domain / 'pack.yaml', {'name': 'domain', 'version': '0', 'default_language': 'nl',
          'imports': [{'name': 'spans', 'path': '../theory', 'sha256': modules.pack_hash(theory)}]})
    write(domain / 'channels.yaml', {'kinds': [{'kind': k, 'shape': 'rect'} for k in ('term', 'calendar', 'reading')],
          'arrows': [{'arrow': a, 'dash': 'none'} for a in ('term.calendar', 'reading.calendar')]})
    write(domain / 'labels/nl.yaml', {})
    if view is not None:
        view = json.loads(json.dumps(view))
        if change:
            change(view)
        write(domain / 'views.yaml', {'format': 'rezono.views/1', 'views': [view]})
    return domain, theory


def program(tmp_path, **options):
    domain, _ = packs(tmp_path, **options)
    return ir.load(pack.read(domain).rules)


@pytest.fixture(scope='module')
def model(tmp_path_factory):
    """The domain with the unchanged view, read once: reading a pack takes most of a test's time."""
    return pack.read(packs(tmp_path_factory.mktemp('view'))[0])


@pytest.fixture(scope='module')
def shared(model):
    return ir.load(model.rules)


def run(prog, data):
    con = batch.connect(prog, {n: typed(prog, n, data.get(n, [])) for n, r in prog.relations.items() if r.role == 'base'},
                        threads=1)
    try:
        con.execute("SET memory_limit = '256MB'")
        batch.compute(con, prog)
        return batch.read(con, prog, list(prog.relations)), batch.witnesses(con, prog)
    finally:
        con.close()


def facts(terms, readings, calendar='c'):
    """terms: (id, start or None, end or None); readings: (id, YYYYMMDD). One calendar."""
    return {'calendar': [(calendar,)], 'term': [(t,) for t, _, _ in terms], 'reading': [(r,) for r, _ in readings],
            'term__calendar': [(t, calendar) for t, _, _ in terms],
            'reading__calendar': [(r, calendar) for r, _ in readings],
            'term__starts': [(t, a.isoformat()) for t, a, _ in terms if a],
            'term__ends': [(t, b.isoformat()) for t, _, b in terms if b],
            'reading__day': [(r, str(n)) for r, n in readings]}


def count(day):
    return (day - EPOCH).days


def written(day):
    return day.year * 10000 + day.month * 100 + day.day


def calendar_day(n):
    """The calendar day a whole number YYYYMMDD writes, or None."""
    try:
        return datetime.date(n // 10000, n // 100 % 100, n % 100)
    except ValueError:
        return None


def counted_day(n):
    """The day `yyyymmdd` counts for n (docs/compiler/schema-operations.md, "Views that execute"): a year, month
    and day within 1 to 9999, 1 to 12 and 1 to 31 are counted from the first of that month, so 31 February counts
    as 2 or 3 March and the invariant `<relation>_no_day` blocks its publication; outside those ranges no count."""
    y, m, d = n // 10000, n // 100 % 100, n % 100
    if not (1 <= y <= 9999 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return datetime.date(y, m, 1) + datetime.timedelta(days=d - 1)


def expected_covers(terms, readings):
    """From the dates themselves: a term covers a reading when start <= day < end, the day as `yyyymmdd` counts it."""
    days = {r: counted_day(n) for r, n in readings}
    return {(t, r) for t, a, b in terms for r, _ in readings if a and b and days[r] and a <= days[r] < b}


def span(first, last):
    return [first + datetime.timedelta(days=i) for i in range((last - first).days + 1)]


def test_the_theory_rules_run_over_the_view_and_the_checker_follows_the_proof_to_the_fact(shared):
    prog = shared
    terms = [('t1', datetime.date(2024, 2, 1), datetime.date(2024, 3, 1)), ('t2', datetime.date(2024, 3, 1), None)]
    readings = [('r1', 20240229), ('r2', 20240301)]
    rows, witnesses = run(prog, facts(terms, readings))
    assert rows['covers'] == {('t1', 'r1')} == expected_covers(terms, readings)
    assert rows['spans_span_first'] == {('t1', str(count(terms[0][1]))), ('t2', str(count(terms[1][1])))}
    assert rows['spans_span_last'] == {('t1', str(count(terms[0][2])))}          # no end recorded: no row, no number
    # The theory's rule is as written; only its relation names are bound to the view's relations.
    rule = prog.rules['covers']
    assert [b.atom.relation for b in rule.body] == ['spans_span_on', 'spans_mark_on', 'spans_mark_at',
                                                    'spans_span_first', 'spans_span_last']
    assert rule.origin == ('spans:rules/spans.dl', 7)
    ex = explain.Explainer(prog, rows, witnesses)
    snaps = {n: ex.snapshot(n).encode() for n in prog.relations}
    manifest = {'id': 'm', 'snapshots': [{'relation': n, 'role': 'all', 'complete': True, 'uri': n, 'format': 'json',
                'sha256': hashlib.sha256(raw).hexdigest()} for n, raw in sorted(snaps.items())]}
    rules = load_rules(ir.to_doc(prog))
    proof = ex.proof('covers', ('t1', 'r1'), 'm')
    result = check(proof, manifest, rules, lambda uri: snaps[uri])
    assert result['valid'], result['findings']
    premises = {(p['row']['relation'], tuple(json.loads(p['row']['key']))) for w in proof['witnesses'] for p in w['premises']}
    assert ('term__starts', ('t1', '2024-02-01')) in premises and ('reading__day', ('r1', '20240229')) in premises
    # A proof with another day count for the same fact does not pass: the checker counts the days itself.
    right, wrong = f'"{count(terms[0][1])}"', f'"{count(terms[0][1]) + 1}"'
    forged = dict(proof, witnesses=[json.loads(json.dumps(w).replace(right, wrong))
                                    if w['conclusion']['relation'] == 'spans_span_first' else w for w in proof['witnesses']])
    refused = check(forged, manifest, rules, lambda uri: snaps[uri])
    assert forged != proof and not refused['valid'] and 'assignment_mismatch' in json.dumps(refused['findings'])


def test_days_and_yyyymmdd_agree_on_every_day_across_a_leap_day_and_a_century(shared):
    prog = shared
    days = (span(datetime.date(1899, 12, 20), datetime.date(1900, 3, 10)) + span(datetime.date(1999, 12, 20), datetime.date(2000, 3, 10))
            + span(datetime.date(2023, 12, 20), datetime.date(2024, 3, 10)) + span(datetime.date(1969, 12, 25), datetime.date(1970, 1, 5))
            + [datetime.date(1, 1, 1), datetime.date(1600, 2, 29), datetime.date(2100, 2, 28), datetime.date(2100, 3, 1),
               datetime.date(9999, 12, 31)])
    terms = [(f't{i}', d, None) for i, d in enumerate(days)]
    readings = [(f'r{i}', written(d)) for i, d in enumerate(days)]
    rows, _ = run(prog, facts(terms, readings))
    assert rows['spans_span_first'] == {(f't{i}', str(count(d))) for i, d in enumerate(days)}
    assert rows['spans_mark_at'] == {(f'r{i}', str(count(d))) for i, d in enumerate(days)}
    assert rows['spans_mark_at_no_day'] == set()


def test_a_whole_number_that_is_no_calendar_day_gives_no_row_and_a_blocking_finding(shared):
    prog = shared
    bad = [20230229, 19000229, 20240230, 20240431, 20241301, 20240001, 20240100, 20240132, 21000229, 101, 100000101]
    good = [20240229, 20000229, 20240430, 20241231]
    readings = [(f'r{n}', n) for n in bad + good]
    rows, _ = run(prog, facts([], readings))
    assert rows['spans_mark_at_no_day'] == {(f'r{n}',) for n in bad}
    # A year outside 1..9999, a month or a day outside 1..12 and 1..31 gives no row at all; 30 February gives a count, and the
    # invariant above keeps the epoch from being published, so no published row rests on it.
    got = {r for r, _ in rows['spans_mark_at']}
    assert {f'r{n}' for n in good} <= got and got.isdisjoint({'r20241301', 'r20240001', 'r20240100', 'r20240132', 'r101', 'r100000101'})
    assert prog.relations['spans_mark_at_no_day'].invariant


def test_an_open_target_stays_open_and_a_missing_value_is_not_recorded_never_a_number(shared):
    prog = shared
    assert prog.relations['spans_span_first'].world == 'open' and prog.relations['first_not_recorded'].absence
    rows, _ = run(prog, facts([('t1', None, datetime.date(2024, 1, 1))], [('r1', 20231231)]))
    assert rows['first_not_recorded'] == {('t1',)} and rows['spans_span_first'] == set() and rows['covers'] == set()


def test_the_theory_table_itself_and_the_view_meet_in_one_relation(shared):
    prog = shared
    data = facts([('t1', datetime.date(2024, 1, 1), datetime.date(2024, 2, 1))], [])
    data |= {'line': [('c',)], 'mark': [('m',)], 'mark__on': [('m', 'c')], 'mark__at': [('m', str(count(datetime.date(2024, 1, 15))))]}
    assert run(prog, data)[0]['covers'] == {('t1', 'm')}


def test_a_role_that_may_not_read_the_fact_gets_no_row_and_no_proof_through_the_view(model, shared):
    """O8 for the view's rows as for any derived row: the publisher's filter, on the engine's own witnesses.
    The grants are stated here; in a pack the read rules derive them (std-access)."""
    from rezono_publisher import access
    from rezono_publisher.batch import columns
    day = datetime.date(2024, 2, 1)
    terms = [('seen', day, day + datetime.timedelta(days=30)), ('t-secret', day, day + datetime.timedelta(days=30))]
    rows, witnesses = run(shared, facts(terms, [('r1', 20240215)]))
    assert rows['covers'] == {('seen', 'r1'), ('t-secret', 'r1')}
    ex = explain.Explainer(shared, rows, witnesses)
    instances = [ex.instance(shared.rules[rule], dict(zip(shared.rules[rule].variables, theta)))
                 for rule, thetas in sorted(witnesses.items()) for theta in thetas]
    grants = [('reader', 'term', 'seen'), ('reader', 'calendar', 'c'), ('reader', 'reading', 'r1')]
    given = {name: sorted(map(list, found)) for name, found in rows.items()} | {'may_read': [list(g) for g in grants]}
    readable, sees, _ = access.for_role(given, frozenset(model.kinds), {k: v.parent for k, v in model.kinds.items() if v.parent},
                                        columns(model) | {'may_read': (None, None, None)}, ir.to_doc(shared), instances, 'reader')
    assert readable['covers'] == [['seen', 'r1']] and readable['spans_span_first'] == [['seen', str(count(day))]]
    assert sees['witnesses'] and 't-secret' not in json.dumps([readable, sees])
    # A role with no grant on the term at all: no row, no day count, no proof of anything through the view.
    readable, sees, _ = access.for_role(given, frozenset(model.kinds), {k: v.parent for k, v in model.kinds.items() if v.parent},
                                        columns(model) | {'may_read': (None, None, None)}, ir.to_doc(shared), instances, 'other')
    assert not any(readable[name] for name in shared.relations if name != 'may_read') and sees['witnesses'] == []


READ_RULES = '''.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("reader", "span", x) :- span(x).
may_read("reader", "term", x) :- term(x).
may_read("reader", "calendar", x) :- calendar(x).
may_read("half", "term", x) :- term(x).
may_read("half", "calendar", x) :- calendar(x).
'''


def test_a_read_rule_names_the_elements_of_the_theory_kind_so_a_role_reads_it_in_full(tmp_path):
    """An access rule names elements, and the view retypes none: `span(x)` under a head that grants x as a span
    stays the kind's own table, while the theory's rules read the view's relation. So the kind is read in full by
    the shape of the rule, and the role may read what rests on the absence of a row; a role without that
    grant gets no row from the absence, though it reads every term."""
    from rezono_publisher import access
    from rezono_publisher.batch import columns
    domain, _ = packs(tmp_path)
    (domain / 'rules').mkdir()
    (domain / 'rules/access.dl').write_text(READ_RULES, encoding='utf-8', newline='\n')
    model = pack.read(domain)
    prog = ir.load(model.rules)
    doc = ir.to_doc(prog)
    bodies = {r['id']: [b['relation'] for b in r['body']] for r in doc['rules']}
    assert bodies['may_read_1'] == ['span'] and bodies['first_not_recorded'][0] == 'spans_span_on'
    rows, witnesses = run(prog, facts([('t1', None, datetime.date(2024, 1, 1))], []))
    assert rows['first_not_recorded'] == {('t1',)} and ('reader', 'span', 't1') not in rows['may_read']
    ex = explain.Explainer(prog, rows, witnesses)
    instances = [ex.instance(prog.rules[rule], dict(zip(prog.rules[rule].variables, theta)))
                 for rule, thetas in sorted(witnesses.items()) for theta in thetas]
    given = {name: sorted(map(list, found)) for name, found in rows.items()}
    parents = {k: v.parent for k, v in model.kinds.items() if v.parent}
    seen = {role: access.for_role(given, frozenset(model.kinds), parents, columns(model), doc, instances, role)
            for role in ('reader', 'half')}
    assert seen['reader'][0]['first_not_recorded'] == [['t1']] and 'first_stated' in seen['reader'][2]
    assert seen['half'][0]['first_not_recorded'] == [] and 'first_stated' not in seen['half'][2]
    assert seen['half'][0]['term'] == [['t1']]


def test_the_same_input_gives_the_same_bytes(tmp_path):
    domain, _ = packs(tmp_path)
    one, two = (json.dumps(pack.read(domain).rules, sort_keys=True) for _ in range(2))
    assert one == two and '"days"' in one


# What VIEW says, in another order and layout, so that no entry stands where its index would put it.
LINED = '''# line 1: a comment
format: rezono.views/1
views:
  - kinds:
      - name: span
        union: [{populated_from: term}]
      - {name: line, union: [{populated_from: calendar}]}
      - {name: mark, union: [{populated_from: reading}]}
    theory: spans
    attributes:
      - {of: span, name: first, populated_from: starts, reading: days}
      - {of: span, name: last, populated_from: ends, reading: days}
      - of: mark
        name: at
        populated_from: day
        reading: yyyymmdd
    arrows:
      - {name: "on", of: span, paths: [{populated_from: term, steps: [{slot: calendar}]}]}
      - {name: "on", of: mark, paths: [{populated_from: reading, steps: [{slot: calendar}]}]}
'''


def test_a_rule_of_the_view_has_the_line_of_its_entry_and_a_pass_through_the_line_of_the_theory_key(tmp_path, shared):
    """A rule the view is lowered to names the line of the entry of views.yaml it comes from, as the reader found
    it. The pass-through of a theory table comes from no entry: it names the line of the view's `theory` key."""
    domain, _ = packs(tmp_path)
    (domain / 'views.yaml').write_text(LINED, encoding='utf-8', newline='\n')
    prog = ir.load(pack.read(domain).rules)
    lines = {r.id: r.origin[1] for r in prog.rules.values() if r.origin[0] == 'views.yaml'}
    theory, entry = 9, {'spans_span': 5, 'spans_line': 7, 'spans_mark': 8, 'spans_span_first': 11,
                        'spans_span_last': 12, 'spans_mark_at': 13, 'spans_span_on': 18, 'spans_mark_on': 19}
    expected = {f'{relation}_1': theory for relation in entry}                    # the table itself, passed through
    expected.update({f'{relation}_2': line for relation, line in entry.items()})  # what the entry supplies
    expected.update({f'spans_mark_at_no_day_{n}': entry['spans_mark_at'] for n in range(1, 14)})
    assert lines == expected
    assert {r.id for r in prog.rules.values() if r.module == 'view_spans'} == set(expected)

    def without_lines(program):
        doc = ir.to_doc(program)
        for r in doc['rules']:
            if r['origin']['file'] == 'views.yaml':
                del r['origin']['line']
        return doc
    assert without_lines(prog) == without_lines(shared)  # a line says where an entry stood, not what the view says


@pytest.mark.parametrize('change, message', [
    (lambda v: v['kinds'][0]['union'].append({'populated_from': 'reading'}), 'union'),
    (lambda v: v['arrows'][0]['paths'].append({'populated_from': 'term', 'steps': [{'slot': 'calendar'}, {'slot': 'calendar', 'inverse': True}, {'slot': 'calendar'}]}), 'paths'),
    (lambda v: v['attributes'][0].update(reading='yyyymmdd'), 'does not read DATE'),       # a reading swapped
    (lambda v: v['attributes'][2].update(reading='days'), 'does not read BIGINT'),
    (lambda v: v['attributes'][0].update(reading='year'), 'expected one of'),
    (lambda v: v['attributes'][0].update(expr='starts + 1'), "unknown field 'expr'"),
    (lambda v: v['attributes'][0].update(populated_from='calendar'), 'single-valued attribute'),
    (lambda v: v['arrows'][0]['paths'][0]['steps'][0].update(inverse=True), 'inverse'),      # an arrow reversed
    (lambda v: v['arrows'][0].pop('of'), 'with and without'),
])
def test_outside_the_profile_nothing_is_emitted(tmp_path, change, message):
    domain, _ = packs(tmp_path, change=change)
    with pytest.raises(pack.CompileError, match=message):
        pack.read(domain)


def test_a_limit_of_the_theory_is_held_on_the_rows_the_view_supplies(tmp_path):
    """The theory's own range check reads only its own table; the invariant holds the limit on the view's rows."""
    prog = program(tmp_path, theory_change=lambda c: c['Mark']['attributes']['at'].update(minimum_value=0,
                                                                                          maximum_value=20000))
    assert prog.relations['spans_mark_at_out_of_range'].invariant
    low, high = datetime.date(1969, 12, 31), datetime.date(2025, 1, 1)  # counts -1 and 20089
    readings = [('r-low', written(low)), ('r-ok', 20240101), ('r-high', written(high))]
    rows, _ = run(prog, facts([], readings))
    assert rows['spans_mark_at_out_of_range'] == {('r-low',), ('r-high',)}
    assert rows['spans_mark_at_no_day'] == set()


@pytest.mark.parametrize('theory_change', [
    lambda c: c['Span']['attributes']['first'].update(equals_number=5),                        # a constant
    lambda c: c['Span'].update(unique_keys={'k': {'unique_key_slots': ['on', 'first']}}),        # a unique key
    lambda c: c['Span']['attributes']['id'].update(pattern='^t'),                                # an id pattern
])
def test_a_constraint_the_view_does_not_hold_is_refused(tmp_path, theory_change):
    domain, _ = packs(tmp_path, theory_change=theory_change)
    with pytest.raises(pack.CompileError, match='does not hold on the rows it supplies'):
        pack.read(domain)


def test_a_view_in_an_imported_pack_is_refused(tmp_path):
    domain, theory = packs(tmp_path, view=None)
    write(theory / 'views.yaml', {'format': 'rezono.views/1', 'views': [VIEW]})
    write(domain / 'pack.yaml', {'name': 'domain', 'version': '0', 'default_language': 'nl',
          'imports': [{'name': 'spans', 'path': '../theory', 'sha256': modules.pack_hash(theory)}]})
    with pytest.raises(pack.CompileError, match='view execution is not supported here'):
        pack.read(domain)


def test_a_generated_name_that_collides_is_an_error(tmp_path):
    domain, theory = packs(tmp_path)
    (domain / 'rules').mkdir()
    (domain / 'rules/own.dl').write_text('.decl spans_span_first(t: symbol)\nspans_span_first(t) :- term(t).\n',
                                         encoding='utf-8', newline='\n')
    with pytest.raises(pack.CompileError, match='spans_span_first collides'):
        pack.read(domain)


DAY = st.dates(min_value=datetime.date(1890, 1, 1), max_value=datetime.date(2110, 12, 31))
CASE = st.tuples(st.lists(st.tuples(st.one_of(st.none(), DAY), st.one_of(st.none(), DAY)), max_size=6),
                 st.lists(st.one_of(DAY.map(written), st.integers(min_value=18900000, max_value=21101231)), max_size=6))


@settings(max_examples=10, deadline=None)
@given(st.lists(CASE, min_size=20, max_size=20))
# A whole number that is no calendar day within a term (found by the nightly profile, 14-11-2026).
@example([([(datetime.date(1972, 1, 1), datetime.date(1972, 12, 31))], [19720231, 19720230, 19721131])] + [([], [])] * 19)
def test_property_the_engine_agrees_with_the_dates_themselves(shared, cases):
    """200 cases in ten engine runs: each case has a calendar of its own, and a term covers a reading only on its
    own calendar, so the cases of one run do not meet."""
    data, expected, no_day = {}, set(), set()
    for k, case in enumerate(cases):
        terms = [(f'c{k}t{i}', a, b) for i, (a, b) in enumerate(case[0])]
        readings = [(f'c{k}r{i}', n) for i, n in enumerate(case[1])]
        for name, rows in facts(terms, readings, calendar=f'c{k}').items():
            data.setdefault(name, []).extend(rows)
        expected |= expected_covers(terms, readings)
        no_day |= {(r,) for r, n in readings if calendar_day(n) is None}
    rows = run(shared, data)[0]
    assert rows['covers'] == expected
    assert rows['spans_mark_at_no_day'] == no_day  # a reading that is no calendar day blocks publication


def test_the_control_fails_with_the_bounds_swapped(tmp_path):
    """The property is no tautology: the same expectation refuses a view that reads the end as the start."""
    def swap(v):
        v['attributes'][0]['populated_from'], v['attributes'][1]['populated_from'] = 'ends', 'starts'
    prog = program(tmp_path, change=swap)
    terms, readings = [('t1', datetime.date(2024, 1, 1), datetime.date(2024, 2, 1))], [('r1', 20240115)]
    assert run(prog, facts(terms, readings))[0]['covers'] == set() != expected_covers(terms, readings)


@pytest.mark.skipif(shutil.which('souffle') is None, reason='Souffle is not installed; no oracle pass claimed')
def test_souffle_agrees_on_the_lowered_program_as_a_set(shared):
    prog = shared
    days = span(datetime.date(1999, 12, 28), datetime.date(2000, 3, 2)) + span(datetime.date(1900, 2, 26), datetime.date(1900, 3, 2))
    terms = [(f't{i}', d, d + datetime.timedelta(days=3)) for i, d in enumerate(days)] + [('open', None, days[0])]
    readings = [(f'r{i}', written(d)) for i, d in enumerate(days)] + [('bad', 20230229)]
    data = facts(terms, readings)
    rows, _ = run(prog, data)
    oracle = souffle.run(prog, data)
    for name, rel in prog.relations.items():
        if rel.role == 'derived':
            assert oracle[name] == rows[name], name
    assert rows['covers'] == expected_covers(terms, readings) and rows['covers']
