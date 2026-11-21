"""The healthcare allowance slice: the constructs its module uses, and its published allowance
against the independent oracle reference.py (decisions/language-healthcare-allowance-slice.md,
decisions/healthcare-allowance-three-sources.md, decisions/no-green-by-cheapest-route.md)."""

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
DAY_NUMBER_SLOT_RE = re.compile(r"^\s+([a-z][a-z0-9_]*_day|day)\s*:\s*Int\b", re.MULTILINE)


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


def _assert_no_day_number_slots_in_slice_tree():
    """Forbid `*_day` or integer `day` slots in examples/zorgtoeslag-slice/ and its four source packs."""
    hits = []
    for path in sorted(SLICE.rglob("*.rezono")):
        text = COMMENTS.sub("", path.read_text(encoding="utf-8"))
        for match in DAY_NUMBER_SLOT_RE.finditer(text):
            hits.append(f"{path.relative_to(ROOT).as_posix()}: {match.group(1)}")
        for match in re.finditer(r"^\s+([a-z][a-z0-9_]*_day)\s*:", text, re.MULTILINE):
            entry = f"{path.relative_to(ROOT).as_posix()}: {match.group(1)}"
            if entry not in hits:
                hits.append(entry)
    for path in sorted(SLICE.rglob("schema/*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for cls_name, cls_body in (doc.get("classes") or {}).items():
            for slot_name, slot_body in ((cls_body or {}).get("attributes") or {}).items():
                rng = str((slot_body or {}).get("range") or "")
                if slot_name.endswith("_day") or (slot_name == "day" and rng == "integer"):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}: {cls_name}.{slot_name} ({rng})")
    assert not hits, f"integer day-number slots are forbidden in zorgtoeslag-slice and its sources: {hits}"


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


def _remove_dated_rezono_block(lines: list[str], target_id: str, target_known: str) -> tuple[list[str], bool]:
    """Remove a dated Rezono fact block for `target_id` with `known <target_known>` (ISO date)."""
    out: list[str] = []
    removed = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.split("--", 1)[0].strip()
        if stripped.startswith("fact ") and f"known {target_known}" in stripped:
            block = [line]
            j = i + 1
            while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
                block.append(lines[j])
                j += 1
            block_text = "\n".join(block)
            if target_id in block_text:
                removed = True
                i = j
                continue
        out.append(line)
        i += 1
    return out, removed


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
        yaml_facts = [
            p for p in sorted(facts_source.rglob("*"))
            if p.is_file() and p.suffix in {".yaml", ".yml"} and not p.name.endswith(".sources.yaml")
        ]
        assert not yaml_facts, f"YAML fact files are forbidden in zorgtoeslag-slice: {[p.name for p in yaml_facts]}"
        edited_dir = tmp_path / "edited-facts"
        shutil.copytree(facts_source, edited_dir)
        removed = False
        for path in sorted(edited_dir.rglob("*.rezono")):
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            kept, did_remove = _remove_dated_rezono_block(lines, "p-gus", "2026-04-15")
            if did_remove:
                path.write_text("".join(kept), encoding="utf-8", newline="\n")
                removed = True
        assert removed, "could not locate p-gus corrected 2026-04-15 income block in .rezono facts"
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
    assert not list(SLICE.rglob("*.dl")), "examples/zorgtoeslag-slice must use Rezono, never .dl rules"
    _assert_no_day_number_slots_in_slice_tree()

    form = read_form(MODULE, tmp_path)
    assert form["module"]["pack"] == "zorgtoeslag-slice"
    text = COMMENTS.sub("", MODULE.read_text(encoding="utf-8"))
    used = authored_features(MODULE)

    # Inline parameter versions with valid/known stay mandatory in both the first slice and the three-source slice.
    assert INLINE_PARAM_VERSION.search(text), "no inline parameter version with valid and known per year"
    assert not [name for name, pattern in LEFT_OUT.items() if pattern.search(text)]
    assert len(re.findall(r"^\s*unless\b", text, re.MULTILINE)) == 2

    if not PACK.is_file():
        assert read_form(SLICE / "facts.rezono", tmp_path)["module"]["pack"] == "zorgtoeslag-slice"
        assert used <= SLICE_FEATURES, f"outside the first slice: {sorted(used - SLICE_FEATURES)}"
        assert REQUIRED_FEATURES <= used, f"the slice needs: {sorted(REQUIRED_FEATURES - used)}"
    else:
        # In-place expansion to three sources (decisions/healthcare-allowance-three-sources.md §1).
        facts_dir = SLICE / "facts"
        rezono_facts = sorted(facts_dir.rglob("*.rezono")) if facts_dir.is_dir() else []
        assert rezono_facts or (SLICE / "facts.rezono").is_file(), "no .rezono facts found for zorgtoeslag-slice"
        yaml_facts = [
            p for p in (sorted(facts_dir.rglob("*")) if facts_dir.is_dir() else [])
            if p.is_file() and p.suffix in {".yaml", ".yml"} and not p.name.endswith(".sources.yaml")
        ]
        assert not yaml_facts, f"YAML fact files are forbidden in zorgtoeslag-slice: {[p.name for p in yaml_facts]}"
        assert used <= THREE_SOURCE_SLICE_FEATURES, (
            f"outside the three-source slice: {sorted(used - THREE_SOURCE_SLICE_FEATURES)}"
        )
        assert REQUIRED_THREE_SOURCE_FEATURES <= used, (
            f"the three-source slice needs: {sorted(REQUIRED_THREE_SOURCE_FEATURES - used)}"
        )
