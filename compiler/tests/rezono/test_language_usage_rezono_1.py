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
        if path.endswith(".ts"):
            snippet = f"test({name!r}, () => {{}});\n"
        else:
            snippet = f"def {name}():\n    assert True\n"
        target = root / path
        if target.exists():
            snippet = target.read_text(encoding="utf-8") + "\n" + snippet
        write(root, path, snippet)


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
    evidence(tmp_path, (
        NATIVE_PACK_EVIDENCE["native-rule-signatures"],
        NATIVE_PACK_EVIDENCE["native-rule-publication-parity"],
    ))

    problems = []
    packs = inventory(tmp_path)
    if (tmp_path / "build") not in packs:
        problems.append("inventory(tmp_path) omitted build/")
    else:
        _, build_native = readiness(tmp_path, "build")
        if not build_native.startswith("Pending: "):
            problems.append(
                f"build should be Pending without rezono 1 lowering evidence, got {build_native!r}"
            )

    _, ruled_native = readiness(tmp_path, "packs/base")
    if not ruled_native.startswith("Pending: "):
        problems.append(
            f"packs/base should be Pending without rezono 1 lowering evidence, got {ruled_native!r}"
        )

    # Counter-case: a pack with no rules still reports Ready once its schema features are supported.
    _, schema_native = readiness(tmp_path, "packs/schema-only")
    if schema_native != "Ready":
        problems.append(f"packs/schema-only (no rules) should be Ready, got {schema_native!r}")

    # Real repository check: build/ is inventoried and rendered alongside examples/, packs/ and run/.
    real_packs = inventory(ROOT)
    if (ROOT / "build") not in real_packs:
        problems.append("inventory(ROOT) omitted the repository build/ pack")
    elif not any(line.startswith("| build |") for line in render(ROOT).splitlines()):
        problems.append("render(ROOT) omitted the repository build/ row")

    if problems:
        raise PrematureNativeReadiness("\n".join(problems))
