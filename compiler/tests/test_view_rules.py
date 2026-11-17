"""Tiny native RuleIR/DuckDB/proof cases against independently specified source expectations."""
from dataclasses import replace
from pathlib import Path
import copy
import hashlib
import shutil

import pytest
import yaml

from rede_checker.check import check
from rede_checker.rules import load_rules
from rede_compiler import batch, explain, modules, pack, rules as ir, view_rules, view_typing, views
from support import typed
import souffle

FIXTURE = Path(__file__).parent / 'fixtures/minimal'
NAMES = view_rules.RelationMap({'node': 'mapped_node'}, {'node__next': 'mapped_next'})


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding='utf-8')


def model(tmp_path, *, path='span', domain_change=None, theory_change=None, view_change=None):
    domain = Path(shutil.copytree(FIXTURE, tmp_path / 'domain'))
    theory = Path(shutil.copytree(FIXTURE, tmp_path / 'theory'))
    schema = {'id': 'https://rede.example/relations', 'name': 'relations', 'imports': ['linkml:types'],
              'default_range': 'string', 'annotations': {'layer': 'facts'}, 'classes': {
        'Node': {'attributes': {'id': {'identifier': True}, 'next': {'range': 'Node', 'multivalued': True}}}}}
    if theory_change:
        theory_change(schema)
    write(theory / 'schema/minimal.yaml', schema)
    write(theory / 'pack.yaml', {'name': 'relations', 'version': '0', 'default_language': 'nl', 'theory': True})
    write(theory / 'channels.yaml', {'kinds': [{'kind': 'node', 'shape': 'rect'}], 'arrows': [{'arrow': 'node.next', 'dash': 'none'}]})
    write(theory / 'labels/nl.yaml', {'node': 'Node', 'node.next': 'Next'})
    schema = {'id': 'https://rede.example/domain', 'name': 'domain', 'imports': ['linkml:types'],
              'default_range': 'string', 'annotations': {'layer': 'facts'}, 'classes': {
        'Parent': {'attributes': {'id': {'identifier': True}, 'next': {'range': 'Parent', 'multivalued': True}, 'child': {'range': 'Child'}}},
        'Child': {'is_a': 'Parent'},
        'Link': {'attributes': {'id': {'identifier': True}, 'left': {'range': 'Parent'}, 'right': {'range': 'Parent'}}}}}
    if domain_change:
        domain_change(schema)
    write(domain / 'schema/minimal.yaml', schema)
    write(domain / 'pack.yaml', {'name': 'domain', 'version': '0', 'default_language': 'nl',
          'imports': [{'name': 'relations', 'path': '../theory', 'sha256': modules.pack_hash(theory)}]})
    write(domain / 'channels.yaml', {'kinds': [{'kind': k, 'shape': 'rect'} for k in ['parent', 'child', 'link']],
          'arrows': [{'arrow': a, 'dash': 'none'} for a in ['parent.next', 'parent.child', 'link.left', 'link.right']]})
    write(domain / 'labels/nl.yaml', {})
    d, t = pack.read(domain), pack.read(theory)
    steps = [{'slot': 'left', 'inverse': True}, {'slot': 'right'}] if path == 'span' else [{'slot': path}]
    value = {'format': 'rede.views/1', 'views': [{'theory': 'relations', 'kinds': [{'name': 'node', 'union': [{'populated_from': 'parent'}]}],
             'arrows': [{'name': 'next', 'paths': [{'populated_from': 'parent', 'steps': steps}]}]}]}
    if view_change:
        view_change(value['views'][0])
    source = tmp_path / 'views.yaml'; write(source, value)
    checked = view_typing.resolve(views.read(source), d, {'relations': t}).views[0]
    program = ir.load({'format': ir.FORMAT, 'pack': d.meta['name'], 'relations': [], 'rules': []})
    return d, t, checked, program


def lowered(models, names=NAMES):
    d, t, view, program = models
    return view_rules.lower(view, d, t, program, names, namespace='vmap')


def run(program, data):
    con = batch.connect(program, {n: typed(program, n, rows) for n, rows in data.items()}, threads=1)
    try:
        con.execute("SET memory_limit = '128MB'")
        batch.compute(con, program)
        rows = batch.read(con, program, list(program.relations))
        witnesses = batch.witnesses(con, program)
        return rows, witnesses
    finally:
        con.close()


def span_facts():
    return {'parent': [('a:α',), ('b:β',)], 'link': [('l1',), ('l2',)],
            'link__left': [('l1', 'a:α'), ('l2', 'a:α')], 'link__right': [('l1', 'b:β'), ('l2', 'b:β')]}


def span_expected(data):
    # Fixed independent source interpretation, not a configurable view/IR interpreter.
    parents = {r[0] for r in data['parent']}; links = {r[0] for r in data['link']}
    return {(a, b) for l, a in data['link__left'] for m, b in data['link__right']
            if l == m and l in links and a in parents and b in parents}


def test_native_span_is_a_set_with_two_actual_witnesses_and_checked_source_lineage(tmp_path):
    program = lowered(model(tmp_path))
    before = ir.to_doc(program)
    rows, witnesses = run(program, span_facts())
    assert rows['mapped_next'] == span_expected(span_facts()) == {('a:α', 'b:β')}
    assert rows['mapped_node'] == set(span_facts()['parent'])
    arrow = next(r for r in program.rules.values() if r.head.relation == 'mapped_next')
    assert arrow.variables == ('?v0', '?v1', '?v2')
    assert len(witnesses[arrow.id]) == 2
    assert {row[1] for row in witnesses[arrow.id]} == {'l1', 'l2'}
    ex = explain.Explainer(program, rows, witnesses)
    snaps = {n: ex.snapshot(n).encode() for n in program.relations}
    manifest = {'id': 'm', 'snapshots': [{'relation': n, 'role': 'all', 'complete': True, 'uri': n, 'format': 'json',
                'sha256': hashlib.sha256(raw).hexdigest()} for n, raw in sorted(snaps.items())]}
    doc = ir.to_doc(program); checked_rules = load_rules(doc)
    chosen = ex.proof('mapped_next', ('a:α', 'b:β'), 'm')
    for row in witnesses[arrow.id]:
        proof = copy.deepcopy(chosen)
        proof['witnesses'] = [ex.instance(arrow, dict(zip(arrow.variables, row))) if w['conclusion']['relation'] == 'mapped_next' else w
                              for w in proof['witnesses']]
        result = check(proof, manifest, checked_rules, lambda uri: snaps[uri])
        assert result['valid'], result['findings']
        direct = next(w for w in proof['witnesses'] if w['conclusion']['relation'] == 'mapped_next')
        premises = {p['row']['relation'] for p in direct['premises']}
        assert {'parent', 'link', 'link__left', 'link__right', 'mapped_node'} <= premises
    assert ir.to_doc(program) == before  # backend/explainer do not rewrite the IR.


def test_child_end_guard_catches_a_real_missing_membership_mutant(tmp_path):
    program = lowered(model(tmp_path, path='child'))
    data = {'parent': [('x',), ('y',)], 'child': [], 'parent__child': [('x', 'y')]}
    expected = {(a, b) for a, b in data['parent__child'] if (a,) in data['parent'] and (b,) in data['parent'] and (b,) in data['child']}
    assert run(program, data)[0]['mapped_next'] == expected == set()
    present = {**data, 'child': [('y',)]}
    assert run(program, present)[0]['mapped_next'] == {('x', 'y')}
    bad = ir.to_doc(program)
    arrow = next(r for r in bad['rules'] if r['head']['relation'] == 'mapped_next')
    arrow['body'] = [p for p in arrow['body'] if p['relation'] != 'child']
    mutant = ir.load(ir.with_strata(bad))
    assert run(mutant, data)[0]['mapped_next'] == {('x', 'y')} != expected


def test_direct_mapping_composes_without_replacing_existing_program_or_base_heads(tmp_path):
    d, t, view, _ = model(tmp_path, path='next')
    original = ir.load(ir.with_strata({'format': ir.FORMAT, 'pack': 'domain',
        'relations': [{'name': 'parent', 'role': 'base', 'key': [{'name': 'id', 'type': 'string'}]},
                      {'name': 'kept', 'role': 'derived', 'module': 'old', 'key': [{'name': 'id', 'type': 'string'}]}],
        'rules': [{'id': 'keep', 'module': 'old', 'head': {'relation': 'kept', 'terms': ['?x']},
                   'body': [{'relation': 'parent', 'terms': ['?x'], 'polarity': 'positive'}], 'origin': {'file': 'old.dl', 'line': '1'}}]}))
    before = ir.to_doc(original)
    program = view_rules.lower(view, d, t, original, NAMES, namespace='vmap')
    assert ir.to_doc(original) == before
    rows, _ = run(program, {'parent': [('x',), ('y',)], 'parent__next': [('x', 'y')]})
    assert rows['kept'] == rows['mapped_node'] == {('x',), ('y',)}
    assert rows['mapped_next'] == {('x', 'y')}
    assert program.relations['parent'].role == 'base'
    # The lines of the two entries in the views.yaml that `model` wrote: `- name: node` and `- name: next`.
    assert {r.id: r.origin for r in program.rules.values() if r.module == 'vmap'} == {
        'vmap_m_0': ('views.yaml', 5), 'vmap_a_0': ('views.yaml', 9)}


@pytest.mark.parametrize('names', [
    view_rules.RelationMap({}, {'node__next': 'mapped_next'}),
    view_rules.RelationMap({'node': 'parent'}, {'node__next': 'mapped_next'}),
    view_rules.RelationMap({'node': 'node'}, {'node__next': 'mapped_next'}),
    view_rules.RelationMap({'node': 'same'}, {'node__next': 'same'}),
    view_rules.RelationMap({'node': 'mapped_node'}, {'node__next': 'bad__derived'}),
])
def test_relation_map_is_exact_and_cannot_override_a_base_kind(tmp_path, names):
    with pytest.raises(view_rules.ViewRuleError, match='relation map'):
        lowered(model(tmp_path), names)


def test_existing_source_signature_and_witness_names_are_checked(tmp_path):
    d, t, view, _ = model(tmp_path)
    for relation in [
        {'name': 'parent', 'role': 'base', 'key': [{'name': 'id', 'type': 'integer'}]},
        {'name': 'vmap_m_0__witness', 'role': 'base', 'key': [{'name': 'id', 'type': 'string'}]},
    ]:
        program = ir.load({'format': ir.FORMAT, 'pack': 'domain', 'relations': [relation], 'rules': []})
        with pytest.raises(view_rules.ViewRuleError, match='signature|namespace'):
            view_rules.lower(view, d, t, program, NAMES, namespace='vmap')


@pytest.mark.parametrize('change', [
    lambda s: s['classes']['Node']['attributes'].update(note={'range': 'string'}),
    lambda s: s['classes']['Node'].update(annotations={'world': {'value': 'open'}}),
    lambda s: s['classes']['Node']['attributes']['id'].update(pattern='^[a-z]+$'),
    lambda s: s['classes']['Node']['attributes']['next'].update(minimum_cardinality=1),
    lambda s: s.update(enums={'Unused': {'permissible_values': {'one': {}}}}),
])
def test_empty_obligations_do_not_bless_unhandled_theory_profiles(tmp_path, change):
    models = model(tmp_path, theory_change=change)
    assert models[2].obligations == ()  # deliberately exercises constraints not represented by that list.
    with pytest.raises(view_rules.ViewRuleError, match='unsupported theory'):
        lowered(models)


def test_reader_still_refuses_raw_mixins_before_a_model_can_be_lowered(tmp_path):
    def mixin(schema):
        schema['classes']['Other'] = {'attributes': {'id': {'identifier': True}}}
        schema['classes']['Node']['mixins'] = ['Other']
    with pytest.raises(pack.CompileError, match='mixins and slot_usage'):
        model(tmp_path, theory_change=mixin)


def test_source_world_and_forged_membership_plan_are_not_silently_accepted(tmp_path):
    def opened(schema):
        schema['classes']['Parent']['annotations'] = {'world': {'value': 'open'}}
    with pytest.raises(view_rules.ViewRuleError, match='source signature/world'):
        lowered(model(tmp_path, domain_change=opened))
    other = tmp_path / 'other'; other.mkdir()
    d, t, view, program = model(other, path='child')
    path = view.arrows[0].paths[0]
    forged = replace(view, arrows=(replace(view.arrows[0], paths=(replace(path, memberships=()),)),))
    with pytest.raises(view_rules.ViewRuleError, match='stale or inconsistent'):
        view_rules.lower(forged, d, t, program, NAMES, namespace='vmap')


def test_unions_and_ID_type_conversion_stay_unsupported(tmp_path):
    d, t, view, program = model(tmp_path)
    union = replace(view, kinds=(replace(view.kinds[0], union=view.kinds[0].union * 2),))
    with pytest.raises(view_rules.ViewRuleError, match='unsupported union'):
        view_rules.lower(union, d, t, program, NAMES, namespace='vmap')
    other = tmp_path / 'other'; other.mkdir()
    def integers(schema):
        schema['classes']['Parent']['attributes']['id']['range'] = 'integer'
    # B11: the typed identity refuses an ID type conversion already when the view is typed, at its location.
    with pytest.raises(view_typing.ViewTypingError, match='no conversion is selected') as error:
        model(other, domain_change=integers)
    assert error.value.key == 'views[relations].kinds[node].union'


@pytest.mark.skipif(shutil.which('souffle') is None, reason='Souffle is not installed; no oracle pass claimed')
def test_independent_literal_source_program_when_souffle_is_already_available(tmp_path):
    program = lowered(model(tmp_path))
    source = """.decl parent(id:symbol)
.input parent
.decl link(id:symbol)
.input link
.decl link__left(id:symbol,v:symbol)
.input link__left
.decl link__right(id:symbol,v:symbol)
.input link__right
.decl mapped_node(id:symbol)
.output mapped_node
.decl mapped_next(id:symbol,v:symbol)
.output mapped_next
mapped_node(x) :- parent(x).
mapped_next(x,y) :- parent(x), parent(y), link(l), link__left(l,x), link__right(l,y).
"""
    expected = souffle.run(program, span_facts(), program_text=source)
    assert expected['mapped_next'] == span_expected(span_facts()) == run(program, span_facts())[0]['mapped_next']


def test_matching_integer_endpoint_types_preserve_native_IDs_without_an_encoder(tmp_path):
    def domain_integer(schema):
        schema['classes']['Parent']['attributes']['id']['range'] = 'integer'
    def theory_integer(schema):
        schema['classes']['Node']['attributes']['id']['range'] = 'integer'
    program = lowered(model(tmp_path, domain_change=domain_integer, theory_change=theory_integer))
    data = {'parent': [('1',), ('2',)], 'link': [('1',)], 'link__left': [('1', '1')], 'link__right': [('1', '2')]}
    rows, witnesses = run(program, data)
    assert rows['mapped_next'] == {('1', '2')}
    assert [c.type for c in program.relations['mapped_next'].key] == ['integer', 'integer']
    assert [c.type for c in program.relations['link__left'].key] == ['string', 'integer']
    assert len(witnesses['vmap_a_0']) == 1


def test_different_source_roots_are_rejected_even_with_a_complete_relation_map(tmp_path):
    def theory_two(schema):
        schema['classes']['Other'] = {'attributes': {'id': {'identifier': True}}}
        schema['classes']['Node']['attributes']['next']['range'] = 'Other'
    def other_map(value):
        value['kinds'].append({'name': 'other', 'union': [{'populated_from': 'link'}]})
        value['arrows'][0]['paths'][0]['steps'] = [{'slot': 'left', 'inverse': True}]
    models = model(tmp_path, theory_change=theory_two, view_change=other_map)
    names = view_rules.RelationMap({'node': 'mapped_node', 'other': 'mapped_other'}, {'node__next': 'mapped_next'})
    with pytest.raises(view_rules.ViewRuleError, match='one canonical source root'):
        lowered(models, names)


def test_inherited_slot_keeps_both_child_start_and_declared_parent_membership(tmp_path):
    def two_kinds(schema):
        schema['classes']['Other'] = {'attributes': {'id': {'identifier': True}}}
        schema['classes']['Node']['attributes']['next']['range'] = 'Other'
    def mapped(value):
        value['kinds'] = [{'name': 'node', 'union': [{'populated_from': 'child'}]},
                          {'name': 'other', 'union': [{'populated_from': 'parent'}]}]
        value['arrows'][0]['paths'][0]['populated_from'] = 'child'
    names = view_rules.RelationMap({'node': 'mapped_child', 'other': 'mapped_parent'}, {'node__next': 'mapped_next'})
    program = lowered(model(tmp_path, path='next', theory_change=two_kinds, view_change=mapped), names)
    data = {'parent': [('a',), ('b',)], 'child': [('a',)], 'parent__next': [('a', 'b')]}
    assert run(program, data)[0]['mapped_next'] == {('a', 'b')}
    assert run(program, {**data, 'parent': [('b',)]})[0]['mapped_next'] == set()


def test_fresh_rule_namespace_does_not_merge_an_existing_module(tmp_path):
    d, t, view, _ = model(tmp_path)
    program = ir.load(ir.with_strata({'format': ir.FORMAT, 'pack': 'domain',
        'relations': [{'name': 'parent', 'role': 'base', 'key': [{'name': 'id', 'type': 'string'}]},
                      {'name': 'held', 'role': 'derived', 'module': 'vmap', 'key': [{'name': 'id', 'type': 'string'}]}],
        'rules': [{'id': 'old', 'module': 'vmap', 'head': {'relation': 'held', 'terms': ['?x']},
                   'body': [{'relation': 'parent', 'terms': ['?x'], 'polarity': 'positive'}], 'origin': {'file': 'old.dl', 'line': '1'}}]}))
    with pytest.raises(view_rules.ViewRuleError, match='namespace collides'):
        view_rules.lower(view, d, t, program, NAMES, namespace='vmap')
