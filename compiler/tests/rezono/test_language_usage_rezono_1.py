"""Native rule conversion readiness waits for rezono 1 derivation lowering and covers build/
(decisions/language-rezono-1.md, sections 5.10 and 6)."""

import pytest

from language_usage import EVIDENCE, NATIVE_PACK_EVIDENCE, ROOT, inventory, render


def write(root, path, contents):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")


def readiness(root, name):
    row = next(line for line in render(root).splitlines() if line.startswith(f"| {name} |"))
    return tuple(value.strip() for value in row.split("|")[-3:-1])


def evidence(root, checks):
    for path, name in checks:
        write(root, path, f"def {name}():\n    assert True\n")


class PrematureNativeReadiness(AssertionError):
    """language_usage.py reported Ready for a ruled pack before rezono 1 lowering or omitted build/."""


@pytest.mark.xfail(
    strict=True,
    raises=PrematureNativeReadiness,
    reason="M3: decisions/language-rezono-1.md: In scripts/language_usage.py, include build/ beside examples/, packs/ "
           "and run/ in SCOPES, and gate the Native conversion column of ruled packs on rezono 1 derivation lowering "
           "evidence so no ruled pack reports Ready while only rezono 0 native rules are supported. Read sections 5.10 and 6.",
)
def test_native_conversion_waits_for_rezono_1_and_includes_build(tmp_path):
    write(tmp_path, "packs/base/pack.yaml", "name: base\n")
    write(tmp_path, "packs/base/rules/sample.dl", ".decl listed(item: symbol)\nlisted(x) :- item(x).\n")
    write(tmp_path, "packs/schema-only/pack.yaml", "name: schema-only\n")
    write(tmp_path, "packs/schema-only/schema/core.yaml", "classes:\n  Item:\n    attributes:\n      id: {identifier: true}\n")
    write(tmp_path, "build/pack.yaml", "name: build\n")
    write(tmp_path, "build/rules/tasks.dl", ".decl ready(item: symbol)\nready(x) :- item(x).\n")

    evidence(tmp_path, EVIDENCE["kind"])
    evidence(tmp_path, EVIDENCE["relational-rule"])
    evidence(tmp_path, EVIDENCE["native-rule"])
    evidence(tmp_path, NATIVE_PACK_EVIDENCE.values())

    problems = []
    packs = inventory(tmp_path)
    if (tmp_path / "build") not in packs:
        problems.append("inventory(tmp_path) omitted build/")
    else:
        _, build_native = readiness(tmp_path, "build")
        if build_native == "Ready":
            problems.append(f"build reported Native conversion = {build_native!r} without rezono 1 lowering evidence")

    _, ruled_native = readiness(tmp_path, "packs/base")
    if ruled_native == "Ready":
        problems.append("packs/base reported Native conversion = 'Ready' with only rezono 0 native-rule evidence")

    # Counter-case: a pack with no rules still reports Ready once its schema features are supported.
    _, schema_native = readiness(tmp_path, "packs/schema-only")
    if schema_native != "Ready":
        problems.append(f"packs/schema-only (no rules) should be Ready, got {schema_native!r}")

    # Real repository check: build/ is included and no ruled pack reports Ready until rezono 1 lowering exists.
    real_packs = inventory(ROOT)
    if (ROOT / "build") not in real_packs:
        problems.append("inventory(ROOT) omitted the repository build/ pack")
    real_rendered = render(ROOT)
    for folder, usage in sorted(real_packs.items()):
        has_rules = any(features & {"relational-rule", "native-rule"} for features in usage.files.values())
        if not has_rules:
            continue
        rel = folder.relative_to(ROOT).as_posix()
        row = next((line for line in real_rendered.splitlines() if line.startswith(f"| {rel} |")), None)
        if row is not None and row.split("|")[-2].strip() == "Ready":
            problems.append(f"real pack {rel} prematurely reported Native conversion = 'Ready'")

    if problems:
        raise PrematureNativeReadiness("\n".join(problems))
