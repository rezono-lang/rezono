"""The healthcare allowance slice: the constructs its module uses, and its published allowance
against the independent oracle reference.py (decisions/language-healthcare-allowance-slice.md,
decisions/healthcare-allowance-three-sources.md, decisions/no-green-by-cheapest-route.md).

Supports both the initial first-slice form (`examples/zorgtoeslag-slice/facts.rezono`) and the
in-place three-source expansion (`examples/zorgtoeslag-slice/facts/`), paired with the strict
retirement test in `examples/test_zorgtoeslag_three_sources.py`
(decisions/no-green-by-cheapest-route.md section 1.3), and inspects parsed/compiled module forms
rather than regex or substring scans over raw source text.
"""

import ast
import datetime
import importlib.util
import json
import os
from pathlib import Path
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
FACTS = SLICE / "facts.rezono"
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
DATE_DURATION_UNITS = frozenset({"year", "years", "month", "months", "day", "days"})
INTEGER_TYPES = frozenset({"int", "integer", "number"})


class MissingSlicePublication(AssertionError):
    pass


class MissingSliceModule(AssertionError):
    pass


def cases():
    return yaml.safe_load((SLICE / "allowance-cases.yaml").read_text(encoding="utf-8"))["cases"]


def first_slice_cases():
    return [case for case in cases() if "household" in case]


def _facts_root():
    facts_dir = SLICE / "facts"
    return facts_dir if facts_dir.is_dir() else FACTS


def _claimant(case, three_sources):
    if three_sources:
        return str(case.get("claimant") or case.get("persoon") or case["household"])
    return str(case["household"])


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


def expected(case):
    want = case["expect"]
    return want["cents"] if "cents" in want else (want["state"], want["reason"])


def _walk_nodes(node):
    """Yield every dict node recursively inside a parsed Rezono module form."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_nodes(item)


def _is_date_duration_literal(node) -> bool:
    if not isinstance(node, dict):
        return False
    lit = node.get("lit")
    if not isinstance(lit, str):
        return False
    parts = lit.strip().split()
    return len(parts) == 2 and parts[1].lower() in DATE_DURATION_UNITS


def _form_left_out_constructs(form: dict) -> list[str]:
    """Check constructs left out of the first slice directly on the parsed module form AST."""
    module = form["module"]
    decls = module.get("decls") or []
    found: list[str] = []
    if any(isinstance(decl, dict) and "rounding" in decl for decl in decls):
        found.append("a rounding declaration")
    has_date_arith = False
    has_timesel = False
    has_agg = False
    has_state_test = False
    for node in _walk_nodes(module):
        if set(node) == {"timesel"} and isinstance(node["timesel"], list):
            has_timesel = True
        if set(node) == {"agg"} and isinstance(node["agg"], list):
            has_agg = True
        if set(node) == {"is"} and isinstance(node["is"], list) and len(node["is"]) == 2:
            has_state_test = True
        arith = node.get("arith") if set(node) == {"arith"} else None
        if isinstance(arith, list) and len(arith) == 3 and arith[0] in {"+", "-"}:
            if _is_date_duration_literal(arith[1]) or _is_date_duration_literal(arith[2]):
                has_date_arith = True
    if has_date_arith:
        found.append("date arithmetic")
    if has_timesel:
        found.append("a time selection")
    if has_agg:
        found.append("an aggregate")
    if has_state_test:
        found.append("a state test")
    return found


def _form_has_inline_parameter_versions(form: dict) -> bool:
    """Whether the parsed module form declares inline parameter versions with valid and known."""
    for decl in form["module"].get("decls") or []:
        if not isinstance(decl, dict) or not isinstance(decl.get("param"), str):
            continue
        if "source" in decl:
            continue
        versions = decl.get("versions") or []
        if versions and all(isinstance(v, dict) and v.get("valid") and v.get("known") for v in versions):
            return True
    return False


def _form_unless_block_count(form: dict) -> int:
    """Count `unless` exception blocks across derived declarations in the parsed module form."""
    total = 0
    for decl in form["module"].get("decls") or []:
        if not isinstance(decl, dict):
            continue
        derived = decl.get("derived")
        if isinstance(derived, list):
            for entry in derived:
                if isinstance(entry, dict):
                    total += len(entry.get("unless") or [])
        elif isinstance(derived, str):
            total += len(decl.get("unless") or [])
    return total


def _resolve_alias(type_name: str, aliases: dict[str, str]) -> str:
    seen: set[str] = set()
    current = type_name
    while current in aliases and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def _assert_no_day_number_slots_in_form(form: dict, label: str) -> None:
    """Forbid `*_day` or integer `day` slots in a parsed Rezono module form."""
    decls = form["module"].get("decls") or []
    aliases = {
        decl["type"]: decl["base"]
        for decl in decls
        if isinstance(decl, dict) and isinstance(decl.get("type"), str) and isinstance(decl.get("base"), str)
    }
    hits: list[str] = []
    for decl in decls:
        if not isinstance(decl, dict):
            continue
        for slot in decl.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            name = str(slot.get("slot") or "")
            resolved = _resolve_alias(str(slot.get("type") or ""), aliases).lower()
            if name.endswith("_day") or (name == "day" and resolved in INTEGER_TYPES):
                hits.append(f"{label}: {name} ({slot.get('type')})")
        derived = decl.get("derived")
        if isinstance(derived, list):
            for entry in derived:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("derived") or "")
                resolved = _resolve_alias(str(entry.get("type") or ""), aliases).lower()
                if name.endswith("_day") or (name == "day" and resolved in INTEGER_TYPES):
                    hits.append(f"{label}: {name} ({entry.get('type')})")
    assert not hits, f"integer day-number slots are forbidden in zorgtoeslag-slice: {hits}"


def _assert_no_day_number_slots_in_slice_tree(tmp_path: Path) -> None:
    """Forbid `*_day` or integer `day` slots across parsed Rezono forms and LinkML schemas in SLICE."""
    from rezono_compiler.schemaview import SchemaView

    for path in sorted(SLICE.rglob("*.rezono")):
        rel = path.relative_to(ROOT).as_posix()
        _assert_no_day_number_slots_in_form(read_form(path, tmp_path), rel)

    hits: list[str] = []
    for path in sorted(SLICE.rglob("schema/*.yaml")):
        rel = path.relative_to(ROOT).as_posix()
        sv = SchemaView(str(path))
        for cls_name in sorted(sv.all_classes()):
            for slot in sv.class_induced_slots(cls_name):
                rng = str(slot.range or "string")
                ancestors = {t.lower() for t in (sv.type_ancestors(rng) or [])} | {rng.lower()}
                if slot.name.endswith("_day") or (slot.name == "day" and bool(ancestors & INTEGER_TYPES)):
                    hits.append(f"{rel}: {cls_name}.{slot.name} ({rng})")
    assert not hits, f"integer day-number slots are forbidden in zorgtoeslag-slice: {hits}"


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
    assert facts_source.exists(), f"{facts_source.relative_to(ROOT).as_posix()} does not exist"
    active_cases = cases() if three_sources else first_slice_cases()
    got = {
        case["id"]: oracle.allowance(facts_source, _claimant(case, three_sources), case["as_of"], case["known"])
        for case in active_cases
    }
    assert got == {case["id"]: expected(case) for case in active_cases}

    # Without the corrected estimate of gus, the January allowance on 2026-05-01 keeps the first estimate:
    # the oracle reads the rows it is given, not values of its own.
    if not three_sources:
        edited = tmp_path / "facts.rezono"
        edited.write_text(
            "rezono 0\n"
            "pack zorgtoeslag-slice\n\n"
            "fact Household\n"
            "  | id  | partner |\n"
            "  | gus | false   |\n\n"
            "fact household gus, valid 2018-01-01.., known 2018-01-05\n"
            "  insured = true\n"
            "fact household gus, valid 2026-01-01..<2027-01-01, known 2026-01-05\n"
            "  joint_income = 2800000\n",
            encoding="utf-8",
            newline="\n",
        )
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
    from rezono_compiler import calc, pack, scenarios

    model = pack.read(SLICE)
    if not any(
        mod.form is not None and _form_has_inline_parameter_versions(mod.form)
        for mod in model.modules
        if mod.pack == model.name
    ):
        raise MissingSlicePublication(
            f"{MODULE.relative_to(ROOT).as_posix()} does not yet publish inline parameter versions"
        )
    program = calc.build(model, model.calc)
    (_, rows), *_ = scenarios.states(model, SLICE)
    facts_source = _facts_root()
    three_sources = facts_source.is_dir()
    active_cases = cases() if three_sources else first_slice_cases()
    got = {case["id"]: published_allowance(model, program, rows, case, three_sources) for case in active_cases}
    assert got == {
        case["id"]: oracle.allowance(facts_source, _claimant(case, three_sources), case["as_of"], case["known"])
        for case in active_cases
    }


def read_form(path, tmp_path):
    rel_key = path.relative_to(ROOT).as_posix().replace("/", "__")
    form = tmp_path / f"{rel_key}.json"
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
    _assert_no_day_number_slots_in_slice_tree(tmp_path)

    form = read_form(MODULE, tmp_path)
    assert form["module"]["pack"] == "zorgtoeslag-slice"
    used = authored_features(MODULE)

    # Inline parameter versions with valid/known, left-out constructs, and two unless blocks hold in both forms.
    assert _form_has_inline_parameter_versions(form), (
        "no inline parameter version with valid and known per year in parsed module form"
    )
    assert not _form_left_out_constructs(form), (
        f"constructs left out of the first slice appeared in parsed module form: {_form_left_out_constructs(form)}"
    )
    assert _form_unless_block_count(form) == 2

    if not PACK.is_file():
        assert read_form(FACTS, tmp_path)["module"]["pack"] == "zorgtoeslag-slice"
        assert used <= SLICE_FEATURES, f"outside the first slice: {sorted(used - SLICE_FEATURES)}"
        assert REQUIRED_FEATURES <= used, f"the slice needs: {sorted(REQUIRED_FEATURES - used)}"
    else:
        # Transitional in-place three-source expansion (decisions/healthcare-allowance-three-sources.md §1),
        # paired with the strict retirement test in examples/test_zorgtoeslag_three_sources.py
        # (decisions/no-green-by-cheapest-route.md §1.3).
        facts_dir = SLICE / "facts"
        rezono_facts = sorted(facts_dir.rglob("*.rezono")) if facts_dir.is_dir() else []
        assert rezono_facts or FACTS.is_file(), "no .rezono facts found for zorgtoeslag-slice"
        yaml_facts = [
            p for p in (sorted(facts_dir.rglob("*")) if facts_dir.is_dir() else [])
            if p.is_file() and p.suffix in {".yaml", ".yml"} and not p.name.endswith(".sources.yaml")
        ]
        assert not yaml_facts, f"YAML fact files are forbidden in zorgtoeslag-slice: {[p.name for p in yaml_facts]}"
        for fact_path in rezono_facts:
            assert read_form(fact_path, tmp_path)["module"]["pack"] == "zorgtoeslag-slice"
        assert used <= THREE_SOURCE_SLICE_FEATURES, (
            f"outside the three-source slice: {sorted(used - THREE_SOURCE_SLICE_FEATURES)}"
        )
        assert REQUIRED_THREE_SOURCE_FEATURES <= used, (
            f"the three-source slice needs: {sorted(REQUIRED_THREE_SOURCE_FEATURES - used)}"
        )
        slice_module_features = set().union(
            *(
                authored_features(p)
                for p in sorted(SLICE.rglob("*.rezono"))
                if "facts" not in p.relative_to(SLICE).parts
            )
        )
        assert REQUIRED_FEATURES <= slice_module_features, (
            f"the three-source slice modules must retain units and all required features: "
            f"{sorted(REQUIRED_FEATURES - slice_module_features)}"
        )
