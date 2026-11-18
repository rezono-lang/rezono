from language_usage import inventory, passing_test, render, supported


def write(root, path, contents):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")


def test_tally_uses_files_once_and_traverses_each_import(tmp_path):
    pin = "a" * 64
    write(tmp_path, "packs/base/pack.yaml", "name: base\n")
    write(tmp_path, "packs/base/schema/core.yaml", """
classes:
  Amount:
    attributes:
      first: {range: integer, minimum_value: 0}
      second: {range: integer, maximum_value: 10}
""")
    write(tmp_path, "packs/middle/pack.yaml", f"name: middle\nimports:\n- {{name: base, path: ../base, sha256: {pin}}}\n")
    write(tmp_path, "run/outer/pack.yaml", f"name: outer\nimports:\n- {{name: middle, path: ../../packs/middle, sha256: {pin}}}\n")
    write(tmp_path, "run/outer/rules/project.dl", ".decl output(value:symbol)\n")
    write(tmp_path, "run/outer/messages/en.mf2", "example = example\n")

    packs = inventory(tmp_path)
    outer = packs[tmp_path / "run/outer"]
    assert [folder.name for folder in outer.imports] == ["base", "middle"]
    assert outer.files == {tmp_path / "run/outer/rules/project.dl": {"relational-rule"}}
    output = render(tmp_path)
    assert output.count("| numeric-limit | 1 |") == 1
    row = next(line for line in output.splitlines() if line.startswith("| run/outer |"))
    assert row.split("|")[3].strip() == "extended-scalar, kind, numeric-limit, optional-slot, slot"
    assert row.split("|")[4].strip().endswith("relational-rule, slot")


def test_unresolved_and_transitively_cyclic_imports_keep_a_pack_pending(tmp_path):
    pin = "a" * 64
    write(tmp_path, "packs/a/pack.yaml", f"name: a\nimports:\n- {{name: b, path: ../b, sha256: {pin}}}\n")
    write(tmp_path, "packs/b/pack.yaml", f"name: b\nimports:\n- {{name: a, path: ../a, sha256: {pin}}}\n")
    write(tmp_path, "examples/demo/pack.yaml", f"name: demo\nimports:\n- {{name: a, path: ../../packs/a, sha256: {pin}}}\n")
    write(tmp_path, "run/other/pack.yaml", f"name: other\nimports:\n- {{name: absent, path: ../absent, sha256: {pin}}}\n")

    for name in ("examples/demo", "run/other"):
        assert f"| {name} | — | — | unresolved-pack-import |" in render(tmp_path)


def test_schema_support_requires_both_positive_evidence_checks(tmp_path):
    reader = "rezono/test/test_numeric_limits.py"
    lowerer = "compiler/tests/rezono/test_lower_numeric_limits.py"
    write(tmp_path, reader, "def test_numeric_limits():\n    assert True\n")
    write(tmp_path, lowerer, "@pytest.mark.xfail(strict=True)\ndef test_lower_numeric_limits():\n    assert True\n")
    assert passing_test(tmp_path, (reader, "test_numeric_limits"))
    assert "numeric-limit" not in supported(tmp_path)
    write(tmp_path, lowerer, "def test_lower_numeric_limits():\n    assert True\n")
    assert "numeric-limit" in supported(tmp_path)


def test_authored_module_ignores_comments_and_exposes_unknown_declarations(tmp_path):
    write(tmp_path, "examples/demo/example.rezono", "rezono 0\npack demo\n-- kind Ignored\nunknown_declaration Demo\n")
    output = render(tmp_path)
    assert "| unclassified-authored-syntax | 1 | Pending |" in output
    assert "| kind |" not in output
    assert output == render(tmp_path)
