import pytest

from model_parity import compare_input, kind, slot


@pytest.mark.xfail(
    strict=True, raises=AssertionError,
    reason="Implement lower path equation in compiler/rezono_compiler/rezono_module.py. Read decisions/language-keys.md. Waits for test_lower_explicit_identifier while it owns the shared lowering module. Use the file priority in docs/rezono/language-coverage.md.",
)
def test_lower_path_equation(tmp_path):
    decl = kind("Task", slot("milestone", "Milestone", card="?"), slot("project", "Project"),
                equations=[{"equal": "same_project", "left": ["milestone", "project"], "right": ["project"]}])
    actual, oracle = compare_input(tmp_path, "projects", decl, external=["Milestone", "Project"])
    assert actual["classes"]["Task"].get("annotations", {}).get("path_equations") == (
        oracle["classes"]["Task"]["annotations"]["path_equations"]
    )
