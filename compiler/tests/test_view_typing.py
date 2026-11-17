"""Static M2b admission on real, normally read and pinned neutral schema packs.

The independent 13-case reference remains separate: these tests cover its static
direction/span/membership obligations, not its instance projection or O8 claims.
"""
from dataclasses import asdict
from pathlib import Path
import copy
import json
import shutil

import pytest
import yaml

from rezono_compiler import identity, modules, pack, views, view_typing as typing
from rezono_compiler import rules as ir

FIXTURE = Path(__file__).parent / 'fixtures' / 'minimal'


def write(path, value):
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding='utf-8')


def models(tmp_path, domain_change=None, theory_change=None):
    domain = Path(shutil.copytree(FIXTURE, tmp_path / 'domain'))
    theory = Path(shutil.copytree(FIXTURE, tmp_path / 'theory'))
    meta = yaml.safe_load((theory / 'pack.yaml').read_text())
    write(theory / 'pack.yaml', meta | {'name': 'static-theory', 'theory': True})
    schema = yaml.safe_load((theory / 'schema/minimal.yaml').read_text())
    schema.update(id='https://rezono.example/static-theory', name='static_theory', classes={
        'Node': {'attributes': {'id': {'identifier': True}, 'next': {'range': 'Node', 'multivalued': True}, 'note': {'range': 'string'}}}})
    schema.pop('enums', None)  # The theory does not import the minimal fixture's unrelated State enum.
    if theory_change:
        theory_change(schema)
    write(theory / 'schema/minimal.yaml', schema)
    write(theory / 'channels.yaml', {'kinds': [{'kind': 'node', 'shape': 'rect'}], 'arrows': [{'arrow': 'node.next', 'dash': 'none'}]})
    write(theory / 'labels/nl.yaml', {'node': 'Node', 'node.next': 'Next', 'node.note': 'Note'})
    schema = yaml.safe_load((domain / 'schema/minimal.yaml').read_text())
    if domain_change:
        domain_change(schema)
    write(domain / 'schema/minimal.yaml', schema)
    meta = yaml.safe_load((domain / 'pack.yaml').read_text())
    meta['imports'] = [{'name': 'static-theory', 'path': '../theory', 'sha256': modules.pack_hash(theory)}]
    write(domain / 'pack.yaml', meta)
    # Use the ordinary pack reader and its pinned import checks.
    return pack.read(domain), pack.read(theory), domain, theory


def doc(start='beta', steps=None, targets=None):
    return {'format': 'rezono.views/1', 'views': [{'theory': 'static-theory',
        'kinds': [{'name': 'node', 'union': [{'populated_from': k} for k in (targets or [start, 'alpha'])]}],
        'arrows': [{'name': 'next', 'paths': [{'populated_from': start, 'steps': steps or [{'slot': 'alpha'}]}]}]}]}


def resolve(tmp_path, domain, theory, value):
    source = tmp_path / 'separate-views.yaml'
    write(source, value)
    return typing.resolve(views.read(source), domain, {theory.meta['name']: theory}, source=source)


def extend(schema):
    schema['classes'].update(
        Left={'is_a': 'Beta'}, Right={'is_a': 'Beta', 'attributes': {'next': {'range': 'Alpha'}}},
        Link={'attributes': {'id': {'identifier': True}, 'left': {'range': 'Alpha'}, 'right': {'range': 'Beta'}}})
    schema['classes']['Alpha']['attributes']['child'] = {'range': 'Right'}


def test_actual_pack_resolution_is_frozen_deterministic_and_retains_typed_roots(tmp_path):
    domain, theory, _, _ = models(tmp_path)
    first = resolve(tmp_path, domain, theory, doc())
    assert first == resolve(tmp_path, domain, theory, doc(targets=['alpha', 'beta']))
    view = first.views[0]
    assert view.import_sha256 == domain.imports[0]['sha256']
    assert [(k.name, [(b.name, b.root, b.id_type) for b in k.union]) for k in view.kinds] == [
        ('node', [('alpha', 'alpha', 'VARCHAR'), ('beta', 'beta', 'VARCHAR')])]
    assert view.arrows[0].paths[0].steps == (typing.Step('beta', 'alpha', 'beta__alpha', False, 'beta', 'alpha', False),)
    assert view.obligations == ()
    assert json.dumps(asdict(first), sort_keys=True) == json.dumps(asdict(resolve(tmp_path, domain, theory, doc())), sort_keys=True)
    with pytest.raises(AttributeError):
        view.theory = 'changed'


@pytest.mark.parametrize('change,reason', [
    (lambda d: d['views'][0]['kinds'][0].update(name='missing'), 'unknown theory kind'),
    (lambda d: d['views'][0]['kinds'][0]['union'].append({'populated_from': 'missing'}), 'unknown source kind'),
    (lambda d: d['views'][0]['arrows'][0].update(name='note'), 'unambiguous theory arrow'),
    (lambda d: d['views'][0]['arrows'][0]['paths'][0].update(populated_from='alpha', steps=[{'slot': 'title'}]), 'expected an arrow slot'),
])
def test_real_names_and_arrow_types_fail_with_logical_location(tmp_path, change, reason):
    domain, theory, _, _ = models(tmp_path)
    value = doc(); change(value)
    with pytest.raises(typing.ViewTypingError, match=reason) as error:
        resolve(tmp_path, domain, theory, value)
    assert error.value.source.endswith('separate-views.yaml')
    assert error.value.key.startswith('views[static-theory]')


def test_each_union_has_a_typed_identity_and_each_path_its_roots(tmp_path):
    domain, theory, _, _ = models(tmp_path, extend)
    view = resolve(tmp_path, domain, theory, doc()).views[0]
    # alpha and beta are unrelated roots: an element of node is (root, id), so equal ids stay two elements.
    assert view.kinds[0].identity == identity.Union(('alpha', 'beta'), 'VARCHAR') and view.kinds[0].identity.tagged
    assert view.arrows[0].paths[0].roots == ('beta', 'alpha')
    # A subkind keeps its root's identity: a union of beta and its child left is one root, the id alone.
    view = resolve(tmp_path, domain, theory, doc('left', targets=['left', 'beta', 'alpha'])).views[0]
    assert view.arrows[0].paths[0].roots == ('beta', 'alpha')
    one = resolve(tmp_path, domain, theory, {'format': 'rezono.views/1', 'views': [{'theory': 'static-theory',
        'kinds': [{'name': 'node', 'union': [{'populated_from': 'left'}, {'populated_from': 'beta'}]}], 'arrows': []}]})
    assert one.views[0].kinds[0].identity == identity.Union(('beta',), 'VARCHAR')


def integer_ids(*classes):
    def change(schema):
        for name in classes:
            schema['classes'][name]['attributes']['id']['range'] = 'integer'
    return change


@pytest.mark.parametrize('change,value,key,reason', [
    (integer_ids('Beta'), doc(), 'views[static-theory].kinds[node].union', 'different identifier types'),
    (integer_ids('Alpha', 'Beta'), doc(), 'views[static-theory].kinds[node].union', 'theory kind identifier type'),
    (None, doc(targets=['beta']), 'views[static-theory].arrows[next].paths[0]', 'path end does not reach'),
], ids=['union-of-mixed-id-types', 'id-type-of-another-kind', 'path-to-a-kind-outside-the-union'])
def test_a_view_typed_against_a_wrong_kind_is_an_error_at_its_location(tmp_path, change, value, key, reason):
    domain, theory, _, _ = models(tmp_path, change)
    with pytest.raises(typing.ViewTypingError, match=reason) as error:
        resolve(tmp_path, domain, theory, value)
    assert error.value.source.endswith('separate-views.yaml') and error.value.key == key


def test_theory_must_be_admitted_and_match_theory_metadata(tmp_path):
    domain, theory, _, directory = models(tmp_path)
    source = tmp_path / 'separate.yaml'; write(source, doc()); value = views.read(source)
    with pytest.raises(typing.ViewTypingError, match='pinned import closure'):
        typing.resolve(value, domain, {})
    meta = yaml.safe_load((directory / 'pack.yaml').read_text()); write(directory / 'pack.yaml', meta | {'theory': False})
    ordinary = pack.read(directory)
    with pytest.raises(typing.ViewTypingError, match='theory metadata'):
        typing.resolve(value, domain, {'static-theory': ordinary})


def test_inherited_arrow_is_legal_without_erasing_child_membership(tmp_path):
    domain, theory, _, _ = models(tmp_path, extend)
    path = resolve(tmp_path, domain, theory, doc(start='left')).views[0].arrows[0].paths[0]
    assert path.memberships == (typing.Membership(0, 'left'), typing.Membership(0, 'beta'), typing.Membership(1, 'alpha'))
    assert path.steps[0].owner == 'beta'
    assert domain.root('left') == 'beta'


@pytest.mark.parametrize('start', ['beta', 'left'])
def test_root_identity_does_not_authorize_parent_or_sibling_downcast(tmp_path, start):
    domain, theory, _, _ = models(tmp_path, extend)
    with pytest.raises(typing.ViewTypingError, match='current kind or an ancestor'):
        resolve(tmp_path, domain, theory, doc(start, [{'slot': 'next'}]))


def test_child_range_requires_child_membership_even_with_parent_union_branch(tmp_path):
    domain, theory, _, _ = models(tmp_path, extend)
    path = resolve(tmp_path, domain, theory, doc('alpha', [{'slot': 'child'}], ['alpha', 'beta'])).views[0].arrows[0].paths[0]
    assert path.end == 'right' and path.target_branches == ('beta',)
    assert typing.Membership(1, 'right') in path.memberships
    assert typing.Membership(1, 'beta') not in path.memberships  # final membership alternatives are separate.
    with pytest.raises(typing.ViewTypingError, match='path end'):
        resolve(tmp_path, domain, theory, doc('alpha', [{'slot': 'child'}], ['alpha', 'left']))


def test_inverse_span_retains_intermediate_link_and_declared_end_memberships(tmp_path):
    domain, theory, _, _ = models(tmp_path, extend)
    path = resolve(tmp_path, domain, theory, doc('alpha', [{'slot': 'left', 'inverse': True}, {'slot': 'right'}], ['alpha', 'beta'])).views[0].arrows[0].paths[0]
    assert path.steps == (typing.Step('link', 'left', 'link__left', True, 'alpha', 'link', True),
                          typing.Step('link', 'right', 'link__right', False, 'link', 'beta', False))
    assert path.memberships == (typing.Membership(0, 'alpha'), typing.Membership(1, 'link'), typing.Membership(2, 'beta'))
    with pytest.raises(typing.ViewTypingError, match='type-compatible incoming'):
        resolve(tmp_path, domain, theory, doc('beta', [{'slot': 'left', 'inverse': True}], ['alpha', 'beta']))


def test_inverse_and_theory_slot_ambiguity_are_not_resolved_by_first_match(tmp_path):
    def two_links(schema):
        extend(schema)
        schema['classes']['OtherLink'] = {'attributes': {'id': {'identifier': True}, 'left': {'range': 'Alpha'}}}
    domain, theory, _, _ = models(tmp_path, two_links)
    with pytest.raises(typing.ViewTypingError, match='ambiguous'):
        resolve(tmp_path, domain, theory, doc('alpha', [{'slot': 'left', 'inverse': True}], ['alpha', 'beta']))
    other = tmp_path / 'other'; other.mkdir()
    def ambiguous(schema):
        schema['classes']['Other'] = {'attributes': {'id': {'identifier': True}, 'next': {'range': 'Node'}}}
    domain, theory, _, _ = models(other, theory_change=ambiguous)
    with pytest.raises(typing.ViewTypingError, match='unambiguous theory arrow'):
        resolve(other, domain, theory, doc())


def test_functionality_is_conservative_and_assumption_is_only_pending(tmp_path):
    def many(schema):
        schema['classes']['Beta']['attributes']['alpha']['multivalued'] = True
    def function(schema):
        schema['classes']['Node']['attributes']['next'].update(multivalued=False, required=True)
    domain, theory, _, _ = models(tmp_path, many, function)
    value = doc()
    with pytest.raises(typing.ViewTypingError, match='not statically functional'):
        resolve(tmp_path, domain, theory, value)
    value['views'][0]['arrows'][0]['assume_functional'] = True
    checked = resolve(tmp_path, domain, theory, value).views[0]
    assert checked.obligations == (typing.Obligation('functionality', 'node__next'), typing.Obligation('totality', 'node__next'))


def test_alternative_paths_and_unmapped_axioms_are_explicit(tmp_path):
    def extra(schema):
        schema['classes']['Beta']['attributes']['direct'] = {'range': 'Alpha'}
    domain, theory, _, _ = models(tmp_path, extra)
    value = doc(); value['views'][0]['arrows'][0]['paths'].append({'populated_from': 'beta', 'steps': [{'slot': 'direct'}]})
    result = resolve(tmp_path, domain, theory, value)
    assert len(result.views[0].arrows[0].paths) == 2
    other = copy.deepcopy(value); other['views'][0]['arrows'][0]['paths'].reverse()
    assert result == resolve(tmp_path, domain, theory, other)
    value['views'][0]['arrows'] = []
    assert resolve(tmp_path, domain, theory, value).views[0].obligations == (typing.Obligation('unmapped_arrow', 'node__next'),)


def test_pack_and_import_guards_are_not_bypassed(tmp_path):
    domain, theory, directory, imported = models(tmp_path)
    resolve(tmp_path, domain, theory, doc())
    write(directory / 'views.yaml', doc())
    with pytest.raises(pack.CompileError, match='view execution is not supported for'):
        pack.read(directory)
    (directory / 'views.yaml').unlink()
    (imported / 'rules').mkdir()
    (imported / 'rules/one.dl').write_text('.decl neutral(x: symbol)\nneutral(x) :- node(x).\n', encoding='utf-8')
    with pytest.raises(pack.CompileError, match='not the pinned'):
        pack.read(directory)

    meta = yaml.safe_load((directory / 'pack.yaml').read_text())
    meta['imports'][0]['sha256'] = modules.pack_hash(imported)
    write(directory / 'pack.yaml', meta)
    domain = pack.read(directory)
    theory = pack.read(imported)
    typed = resolve(tmp_path, domain, theory, doc())
    assert typed.views[0].import_sha256 == meta['imports'][0]['sha256']
    rule = ir.load(domain.rules).rules['neutral']
    assert rule.body[0].atom.relation == 'node'
    assert rule.origin == ('static-theory:rules/one.dl', 2)

    (directory / 'rules').mkdir()
    (directory / 'rules/one.dl').write_text('neutral(x) :- alpha(x).\n', encoding='utf-8')
    with pytest.raises(pack.CompileError, match='only its owner can mark it @extend'):
        pack.read(directory)


def test_registered_theory_and_version_do_not_replace_normal_pin_checks(tmp_path):
    domain, theory, directory, imported = models(tmp_path)
    source = tmp_path / 'separate.yaml'; write(source, doc()); value = views.read(source)
    with pytest.raises(typing.ViewTypingError, match='pinned import closure'):
        typing.resolve(value, pack.read(FIXTURE), {'static-theory': theory})
    meta = yaml.safe_load((imported / 'pack.yaml').read_text())
    write(imported / 'pack.yaml', meta | {'version': '9'})
    with pytest.raises(typing.ViewTypingError, match='theory metadata'):
        typing.resolve(value, domain, {'static-theory': pack.read(imported)})
    with pytest.raises(pack.CompileError, match='hash'):
        pack.read(directory)


def test_unmapped_kinds_and_real_schema_axioms_remain_pending(tmp_path):
    def axioms(schema):
        node = schema['classes']['Node']
        node['attributes']['next']['multivalued'] = False
        node['attributes']['other'] = {'range': 'Node'}
        node['annotations'] = {'path_equations': {'value': [{'name': 'same_end', 'left': 'next', 'right': 'other'}]}}
        node['rules'] = [{'preconditions': {'slot_conditions': {'note': {'value_presence': 'PRESENT'}}},
                          'postconditions': {'slot_conditions': {'note': {'required': True}}}}]
        schema['classes']['Extra'] = {'attributes': {'id': {'identifier': True}}}
    domain, theory, _, _ = models(tmp_path, theory_change=axioms)
    result = resolve(tmp_path, domain, theory, doc()).views[0]
    assert set(result.obligations) == {typing.Obligation('axiom', 'node.same_end'), typing.Obligation('axiom', 'node.rule[0]'),
                                       typing.Obligation('unmapped_kind', 'extra'), typing.Obligation('unmapped_arrow', 'node__other')}


def test_theory_arrow_endpoints_need_explicit_kind_maps(tmp_path):
    def other_endpoint(schema):
        schema['classes']['Other'] = {'attributes': {'id': {'identifier': True}}}
        schema['classes']['Node']['attributes']['peer'] = {'range': 'Other'}
    domain, theory, _, _ = models(tmp_path, theory_change=other_endpoint)
    value = doc(); value['views'][0]['arrows'][0]['name'] = 'peer'
    with pytest.raises(typing.ViewTypingError, match='mapped source and target kinds'):
        resolve(tmp_path, domain, theory, value)


def test_alternative_function_paths_require_a_pending_distinct_target_check(tmp_path):
    def extra(schema):
        schema['classes']['Beta']['attributes']['direct'] = {'range': 'Alpha'}
    def functional(schema):
        schema['classes']['Node']['attributes']['next']['multivalued'] = False
    domain, theory, _, _ = models(tmp_path, extra, functional)
    value = doc(); value['views'][0]['arrows'][0]['paths'].append({'populated_from': 'beta', 'steps': [{'slot': 'direct'}]})
    with pytest.raises(typing.ViewTypingError, match='not statically functional'):
        resolve(tmp_path, domain, theory, value)
    value['views'][0]['arrows'][0]['assume_functional'] = True
    result = resolve(tmp_path, domain, theory, value).views[0]
    assert len(result.arrows[0].paths) == 2
    assert result.obligations == (typing.Obligation('functionality', 'node__next'),)


def test_a_refusal_is_a_diagnostic_with_code_place_span_and_hint(tmp_path):
    """D15: a view typing error is one diagnostic of contracts/diagnostic.yaml; its span is the entry it is in."""
    def many(schema):
        schema['classes']['Beta']['attributes']['alpha']['multivalued'] = True
    def function(schema):
        schema['classes']['Node']['attributes']['next']['multivalued'] = False
    domain, theory, _, _ = models(tmp_path, many, function)
    with pytest.raises(typing.ViewTypingError) as error:
        resolve(tmp_path, domain, theory, doc())
    found = error.value.diagnostic
    assert error.value.diagnostics == (found,) and str(found) == str(error.value)
    arrow = (tmp_path / 'separate-views.yaml').read_text().splitlines().index('  - name: next') + 1
    assert found.doc() == {'code': 'not_functional', 'severity': 'error', 'message': str(error.value),
                           'where': 'views[static-theory].arrows[next]',
                           'span': {'file': 'separate-views.yaml', 'line': str(arrow), 'column': '5'},
                           'hint': 'add assume_functional: true to the arrow map, which becomes a pending obligation'}
    contract = pytest.importorskip('rezono_contracts.diagnostic')
    contract.DiagnosticList.model_validate({'diagnostics': [found.doc()]})


@pytest.mark.parametrize('steps,code,at', [
    ([{'slot': 'state'}], 'not_an_arrow', 0),
    ([{'slot': 'alpha'}, {'slot': 'missing', 'inverse': True}], 'inverse_missing', 1),
])
def test_a_path_step_is_refused_at_its_step_with_its_code(tmp_path, steps, code, at):
    domain, theory, _, _ = models(tmp_path)
    with pytest.raises(typing.ViewTypingError) as error:
        resolve(tmp_path, domain, theory, doc(steps=steps))
    assert error.value.code == code and error.value.key == f'views[static-theory].arrows[next].paths[0].steps[{at}]'
    # The shared resolver says the same without a view around it: the step, the code and the reason.
    with pytest.raises(typing.PathTypingError) as bare:
        typing.directed_path(domain, 'beta', [(s['slot'], s.get('inverse', False)) for s in steps])
    assert (bare.value.step, bare.value.code, bare.value.reason) == (at, code, error.value.reason)


def test_the_shared_path_resolver_types_what_a_view_path_types(tmp_path):
    domain, theory, _, _ = models(tmp_path, extend)
    given = [{'slot': 'left', 'inverse': True}, {'slot': 'right'}]
    path = resolve(tmp_path, domain, theory, doc('alpha', given, ['alpha', 'beta'])).views[0].arrows[0].paths[0]
    assert typing.directed_path(domain, 'alpha', [('left', True), ('right', False)]) == (path.end, path.steps, path.memberships)


def test_a_view_given_as_data_has_no_span(tmp_path):
    domain, theory, _, _ = models(tmp_path)
    source = tmp_path / 'separate.yaml'; write(source, doc()); value = views.read(source)
    with pytest.raises(typing.ViewTypingError) as error:
        typing.resolve(value, pack.read(FIXTURE), {'static-theory': theory})
    assert error.value.diagnostic.span is None and error.value.code == 'theory_not_imported'
    assert error.value.diagnostic.hint


def test_a_pack_that_does_not_compile_keeps_the_view_typing_diagnostic(tmp_path):
    domain, theory, directory, _ = models(tmp_path)
    write(directory / 'views.yaml', {'format': 'rezono.views/1', 'views': [{'theory': 'static-theory',
        'kinds': [{'name': 'node', 'union': [{'populated_from': 'beta'}]}],
        'arrows': [{'name': 'next', 'paths': [{'populated_from': 'beta', 'steps': [{'slot': 'state'}]}]}]}]})
    with pytest.raises(pack.CompileError) as error:
        pack.read(directory)
    [found] = error.value.diagnostics
    assert (found.code, found.where) == ('not_an_arrow', 'views[static-theory].arrows[next].paths[0].steps[0]')
    assert found.span is not None and found.span[0] == 'views.yaml' and str(found) == str(error.value)
