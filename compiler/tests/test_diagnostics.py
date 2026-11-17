"""D15: compiler and admission errors in one diagnostic contract (contracts/diagnostic.yaml).

View typing's own diagnostics are tested with view typing (test_view_typing.py)."""

import shutil
from pathlib import Path

import pytest
import yaml
from rede_admission import Refusal
from rede_compiler import diagnostics, facts, pack

FIXTURE = Path(__file__).parent / 'fixtures' / 'minimal'
contract = pytest.importorskip('rede_contracts.diagnostic')


def test_an_error_raised_as_a_sentence_is_one_compile_error_per_line():
    error = pack.CompileError('class A: one\n\nclass B: two')
    assert [d.doc() for d in error.diagnostics] == [{'code': 'compile_error', 'severity': 'error', 'message': 'class A: one'},
                                                    {'code': 'compile_error', 'severity': 'error', 'message': 'class B: two'}]
    assert str(error) == 'class A: one\n\nclass B: two'
    contract.DiagnosticList.model_validate(diagnostics.listed(error.diagnostics))


def test_a_pack_that_does_not_compile_has_its_errors_as_diagnostics(tmp_path):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / 'pack'))
    schema = yaml.safe_load((directory / 'schema/minimal.yaml').read_text())
    schema['classes']['Alpha']['attributes']['size']['equals_expression'] = '1'
    (directory / 'schema/minimal.yaml').write_text(yaml.safe_dump(schema), encoding='utf-8')
    with pytest.raises(pack.CompileError) as error:
        pack.read(directory)
    assert error.value.diagnostics and all(d.code == 'compile_error' for d in error.value.diagnostics)
    assert '\n'.join(map(str, error.value.diagnostics)) == str(error.value)


def test_admission_refusals_keep_their_codes_and_get_the_span_of_their_place(tmp_path):
    model = pack.read(FIXTURE)
    path = tmp_path / 'facts' / 'one.yaml'
    path.parent.mkdir()
    path.write_text('alpha:\n  - id: a1\n    title: t\nbeta:\n  - id: b1\n    alpha: a1\n    state: 3\ngamma: []\n',
                    encoding='utf-8')
    with pytest.raises(facts.LoadError) as error:
        facts.load(model, path)
    assert [d.doc() for d in error.value.diagnostics] == [
        {'code': 'wrong_type', 'severity': 'error', 'message': 'beta[1].state: is not a VARCHAR', 'where': 'beta[1].state',
         'span': {'file': 'facts/one.yaml', 'line': '7', 'column': '5'}},
        {'code': 'unknown_kind', 'severity': 'error', 'message': "unknown kind 'gamma'", 'where': 'gamma',
         'span': {'file': 'facts/one.yaml', 'line': '8', 'column': '1'}}]
    contract.DiagnosticList.model_validate(diagnostics.listed(error.value.diagnostics))
    # Admission alone, without the compiler or the file, gives the same code and place.
    assert Refusal('wrong_type', 'beta[1].state', 'h').diagnostic() == {k: error.value.diagnostics[0].doc()[k]
                                                                         for k in ('code', 'severity', 'where')}


def test_a_document_refusal_has_no_place():
    with pytest.raises(facts.LoadError) as error:
        facts.sections(None)
    [found] = error.value.diagnostics
    assert found.doc() == {'code': 'document_null', 'severity': 'error', 'message': str(error.value)}
    assert Refusal('document_null', '', 'h').diagnostic() == {'code': 'document_null', 'severity': 'error'}
