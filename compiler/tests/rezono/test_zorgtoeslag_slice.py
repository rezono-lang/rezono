"""The healthcare allowance slice: the constructs its module uses, and its published allowance
against the independent oracle reference.py (decisions/language-healthcare-allowance-slice.md,
decisions/healthcare-allowance-three-sources.md)."""

import ast
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
import yaml

from language_usage import authored_features


ROOT = Path(__file__).resolve().parents[3]
SLICE = ROOT / "examples/zorgtoeslag-slice"
ORACLE = SLICE / "reference.py"
MODULE = SLICE / "rezono/allowance.rezono"
PACK = SLICE / "pack.yaml"
# What the first slice may use, as scripts/language_usage.py names the constructs of a module.
SLICE_FEATURES = {"kind", "slot", "boolean-slot", "extended-scalar", "units", "parameters", "calculation",
                  "exceptions"}
# What the expanded in-place three-source slice may additionally use (decisions/healthcare-allowance-three-sources.md §1).
THREE_SOURCE_SLICE_FEATURES = SLICE_FEATURES | {
    "module-import", "enum", "reference", "optional-slot", "explicit-identifier", "numeric-limit",
    "slot-pattern", "schema-metadata", "time-policy", "relational-rule", "native-rule",
}
REQUIRED_FEATURES = {"units", "parameters", "calculation", "exceptions"}
REQUIRED_THREE_SOURCE_FEATURES = {"parameters", "calculation", "exceptions"}
# What the slice leaves out or writes otherwise, which the usage inventory does not name.
LEFT_OUT = {
    "a rounding declaration": re.compile(r"^rounding\b", re.MULTILINE),
    "date arithmetic": re.compile(r"[+-]\s*\d+\s+(?:year|month|day)s?\b"),
    "a time selection": re.compile(r"\b[a-z_]\w*\s+at\s+[a-z_]\w*\b(?!\s*:)"),
    "an aggregate": re.compile(r"\.(?:count|sum|min|max|any|all|none)\("),
    "a state test": re.compile(r"\bis\s+(?:known|unknown|invalid|n/a)\b"),
}
COMMENTS = re.compile(r"--[^\n]*")
INLINE_PARAM_VERSION = re.compile(r"^\s+version\b.*\bvalid\b.*\bknown\b", re.MULTILINE)


class MissingSlicePublication(AssertionError):
    pass


class MissingSliceModule(AssertionError):
    pass


def cases():
    return yaml.safe_load((SLICE / "allowance-cases.yaml").read_text(encoding="utf-8"))["cases"]


def expected(case):
    want = case["expect"]
    return want["cents"] if "cents" in want else (want["state"], want["reason"])


def _facts_root():
    facts_dir = SLICE / "facts"
    return facts_dir if facts_dir.is_dir() else SLICE / "facts.rezono"


def _claimant(case, three_sources):
    if three_sources:
        return str(case.get("claimant") or case.get("persoon") or case["household"])
    return str(case["household"])


def load_oracle():
    assert ORACLE.is_file(), f"{ORACLE.relative_to(ROOT).as_posix()} does not exist"
    spec = importlib.util.spec_from_file_location("zorgtoeslag_slice_reference", ORACLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(getattr(module, "allowance", None)), \
        "reference.py has no function allowance(facts, household, as_of, known)"
    return module


def imported_modules(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add(".")
            elif node.module:
                names.add(node.module.partition(".")[0])
    return names


def checked_oracle(tmp_path):
    """The oracle, checked before the publication is compared with it: with the standard library only it gives
    every case of allowance-cases.yaml, and it follows a change in the facts it reads."""
    oracle = load_oracle()
    foreign = imported_modules(ORACLE) - set(sys.stdlib_module_names)
    assert not foreign, f"the oracle shares code with the compiler or a library: {sorted(foreign)}"

    facts_source = _facts_root()
    three_sources = facts_source.is_dir()
    active_cases = cases() if three_sources else [c for c in cases() if "household" in c]
    got = {
        case["id"]: oracle.allowance(facts_source, _claimant(case, three_sources), case["as_of"], case["known"])
        for case in active_cases
    }
    assert got == {case["id"]: expected(case) for case in active_cases}

    # Without the corrected estimate of gus, the January allowance on 2026-05-01 keeps the first estimate:
    # the oracle reads the rows it is given, not values of its own.
    if not three_sources:
        lines = facts_source.read_text(encoding="utf-8").splitlines(keepends=True)
        at = next(i for i, line in enumerate(lines) if line.startswith("fact household gus,") and "2026-04-15" in line)
        edited = tmp_path / "facts.rezono"
        edited.write_text("".join(lines[:at] + lines[at + 2:]), encoding="utf-8", newline="\n")
        assert oracle.allowance(edited, "gus", datetime.date(2026, 1, 1), datetime.date(2026, 5, 1)) == 13600
    else:
        edited_dir = tmp_path / "edited-facts"
        shutil.copytree(facts_source, edited_dir)
        removed = False
        for path in sorted(edited_dir.rglob("*.yaml")):
            if path.name.endswith(".sources.yaml"):
                continue
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                continue
            changed = False
            for key, rows in list(doc.items()):
                if not isinstance(rows, list) or "inkomen" not in key.lower():
                    continue
                kept = [
                    r for r in rows
                    if not (
                        isinstance(r, dict)
                        and str(r.get("persoon")) == "p-gus"
                        and str(r.get("known_from", r.get("known_from_day", ""))).replace("-", "") == "20260415"
                    )
                ]
                if len(kept) != len(rows):
                    doc[key] = kept
                    changed = True
                    removed = True
            if changed:
                lines = []
                for sec, rows in doc.items():
                    lines.append(f"{sec}:")
                    for row in rows:
                        lines.append(f"  - {json.dumps(row, default=str)}")
                path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        assert removed, "could not locate p-gus corrected 2026-04-15 income row in facts/"
        assert oracle.allowance(edited_dir, "p-gus", datetime.date(2026, 1, 1), datetime.date(2026, 5, 1)) == 13600
    return oracle


def _has_inline_parameter_versions():
    if not MODULE.is_file():
        return False
    text = COMMENTS.sub("", MODULE.read_text(encoding="utf-8"))
    return bool(INLINE_PARAM_VERSION.search(text))


def published_allowance(model, program, rows, case, three_sources):
    """The allowance the published pack gives the claimant of `case`, evaluated on its `as of` day: whole cents,
    or the pair (state, reason) as the oracle gives it. Both evaluators of the calculation must agree."""
    from calcsupport import run_both
    from rezono_compiler import calc_sql

    day = {calc_sql.AS_OF: [("as_of", str(case["as_of"]), str(case["known"]))]}
    got, reference = run_both(model, program, model.calc, rows | day)
    assert got == reference, case["id"]
    state, value, reason, *_ = got["allowance"][_claimant(case, three_sources)]
    return int(value) if state == "known" else (state, reason)


@pytest.mark.xfail(
    strict=True,
    raises=MissingSlicePublication,
    reason="later: decisions/language-healthcare-allowance-slice.md: Publish examples/zorgtoeslag-slice with "
           "inline parameter versions in rezono/allowance.rezono once inline parameter versions lower in "
           "rezono_calc.py. Then for every case of allowance-cases.yaml the published allowance on its as-of "
           "day equals the independent oracle examples/zorgtoeslag-slice/reference.py",
)
def test_published_slice_gives_the_oracle(tmp_path):
    oracle = checked_oracle(tmp_path)
    if not PACK.is_file():
        raise MissingSlicePublication(f"{PACK.relative_to(ROOT).as_posix()} does not exist")
    if not _has_inline_parameter_versions():
        raise MissingSlicePublication(
            f"{MODULE.relative_to(ROOT).as_posix()} does not yet publish inline parameter versions"
        )
    from rezono_compiler import calc, pack, scenarios

    model = pack.read(SLICE)
    program = calc.build(model, model.calc)
    (_, rows), *_ = scenarios.states(model, SLICE)
    facts_source = _facts_root()
    three_sources = facts_source.is_dir()
    active_cases = cases() if three_sources else [c for c in cases() if "household" in c]
    got = {case["id"]: published_allowance(model, program, rows, case, three_sources) for case in active_cases}
    assert got == {
        case["id"]: oracle.allowance(facts_source, _claimant(case, three_sources), case["as_of"], case["known"])
        for case in active_cases
    }


def read_form(path, tmp_path):
    form = tmp_path / f"{path.stem}.json"
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(path), str(form)],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(form.read_bytes())


def test_slice_module_uses_only_the_first_slice(tmp_path):
    if not MODULE.is_file():
        raise MissingSliceModule(f"{MODULE.relative_to(ROOT).as_posix()} does not exist")
    form = read_form(MODULE, tmp_path)
    assert form["module"]["pack"] == "zorgtoeslag-slice"
    text = COMMENTS.sub("", MODULE.read_text(encoding="utf-8"))
    used = authored_features(MODULE)

    if not PACK.is_file():
        assert read_form(SLICE / "facts.rezono", tmp_path)["module"]["pack"] == "zorgtoeslag-slice"
        assert used <= SLICE_FEATURES, f"outside the first slice: {sorted(used - SLICE_FEATURES)}"
        assert REQUIRED_FEATURES <= used, f"the slice needs: {sorted(REQUIRED_FEATURES - used)}"
        assert not [name for name, pattern in LEFT_OUT.items() if pattern.search(text)]
        assert INLINE_PARAM_VERSION.search(text), "no parameter version per year"
        assert len(re.findall(r"^\s*unless\b", text, re.MULTILINE)) == 2
    else:
        # In-place expansion to three sources (decisions/healthcare-allowance-three-sources.md §1).
        assert (SLICE / "facts").is_dir() or (SLICE / "facts.rezono").is_file(), "no facts found for zorgtoeslag-slice"
        assert used <= THREE_SOURCE_SLICE_FEATURES, (
            f"outside the three-source slice: {sorted(used - THREE_SOURCE_SLICE_FEATURES)}"
        )
        assert REQUIRED_THREE_SOURCE_FEATURES <= used, (
            f"the three-source slice needs: {sorted(REQUIRED_THREE_SOURCE_FEATURES - used)}"
        )
        assert not [name for name, pattern in LEFT_OUT.items() if pattern.search(text)]
        assert len(re.findall(r"^\s*unless\b", text, re.MULTILINE)) == 2
