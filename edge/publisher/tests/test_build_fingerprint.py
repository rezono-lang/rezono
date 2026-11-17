"""Dependency-boundary mutations: real contract bytes and temporary installed-metadata records.

These tests do not install or execute the synthetic distributions, and do not claim that version
metadata fingerprints a library's executable bytes. No engine is needed.
"""
import pytest
from rede_canon import canonical_sha256
from rede_publisher import batch


@pytest.fixture
def distribution_metadata(tmp_path, monkeypatch):
    """A tiny independently specified dependency graph, discovered by importlib.metadata itself."""
    def write(name, version, requires=()):
        info = tmp_path / (name.replace('-', '_') + '-1.0.dist-info')
        info.mkdir(exist_ok=True)
        (info / 'METADATA').write_text('Metadata-Version: 2.1\n' + f'Name: {name}\nVersion: {version}\n'
                                     + ''.join(f'Requires-Dist: {req}\n' for req in requires), encoding='utf-8')
    a, b, c = 'rede-hash-probe-alpha', 'rede-hash-probe-beta', 'rede-hash-probe-gamma'
    write('rede-compiler', '0.1.0', [a, b])
    write('rede-canon', '0.1.0')
    write(a, '1.0', [c])
    write(b, '2.0', [c])
    write(c, '3.0', [a])  # The graph has both a shared dependency and a cycle.
    monkeypatch.syspath_prepend(str(tmp_path))
    return write, a, b, c


def test_contract_byte_change_changes_compiler_fingerprint_but_not_pack_hashes(tmp_path, monkeypatch):
    from rede_compiler import pack
    contract = tmp_path / 'contracts'
    contract.mkdir()
    file = contract / 'sentinel.yaml'
    file.write_bytes(b'id: urn:neutral\n')
    monkeypatch.setattr(pack, 'CONTRACTS', contract)
    source = tmp_path / 'pack'
    source.mkdir()
    (source / 'pack.yaml').write_bytes(b'name: neutral\nversion: 0.1.0\n')
    hashes = batch.tree_sha256(source), batch.definition_sha256(source)
    before = batch.compiler_parts()
    file.write_bytes(b'id: urn:neutral\n# contract byte mutation\n')
    after = batch.compiler_parts()
    assert before['contracts'] != after['contracts']
    assert canonical_sha256(before) != canonical_sha256(after)
    assert {k: v for k, v in before.items() if k != 'contracts'} == {k: v for k, v in after.items() if k != 'contracts'}
    assert (batch.tree_sha256(source), batch.definition_sha256(source)) == hashes


def test_transitive_installed_version_change_changes_compiler_and_build(distribution_metadata):
    write, a, b, c = distribution_metadata
    before = batch.build_record()
    assert before['compiler']['libraries'] == {a: '1.0', b: '2.0', c: '3.0'}
    write(c, '3.1', [a])
    after = batch.build_record()
    assert after['compiler']['libraries'][c] == '3.1'
    assert before['compiler_sha256'] != after['compiler_sha256']
    assert canonical_sha256(before) != canonical_sha256(after)


def test_dependency_context_order_and_repeated_paths_do_not_change_fingerprint(distribution_metadata):
    write, a, b, c = distribution_metadata
    before = batch.compiler_parts()
    assert before['libraries'] == {a: '1.0', b: '2.0', c: '3.0'}
    write('rede-compiler', '0.1.0', [b, a, b])
    write(c, '3.0', [b, a])
    after = batch.compiler_parts()
    assert after['libraries'] == {a: '1.0', b: '2.0', c: '3.0'}
    assert canonical_sha256(before) == canonical_sha256(after)


def test_an_admission_change_changes_compiler_fingerprint(tmp_path, monkeypatch):
    # Admission decides which rows the compiler takes from a fact file (ruling 2 of 11-11-2026), so its source is
    # part of what compiled output depends on, as rede-canon is.
    import shutil
    from pathlib import Path

    import rede_admission
    copy = tmp_path / 'rede_admission'
    shutil.copytree(Path(rede_admission.__file__).parent, copy, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setattr(rede_admission, '__file__', str(copy / '__init__.py'))
    before = batch.compiler_parts()
    (copy / 'rows.py').write_bytes((copy / 'rows.py').read_bytes() + b'\n# an admission byte mutation\n')
    after = batch.compiler_parts()
    assert before['admission'] != after['admission']
    assert canonical_sha256(before) != canonical_sha256(after)
    assert {k: v for k, v in before.items() if k != 'admission'} == {k: v for k, v in after.items() if k != 'admission'}
