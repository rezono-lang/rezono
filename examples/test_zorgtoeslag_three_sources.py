"""Three-source healthcare allowance slice (`examples/zorgtoeslag-slice/`): three independent source packs
glued along one shared `Persoon` pack, Rezono-only rules (`toeslagpartner`, `insured`, `joint_income`) with
zero `.dl` files and zero `calc/*.yaml` files, inline versioned `param` declarations, native `date` and
`Cents` types (zero `*_day` / `YYYYMMDD` stopgaps), structured statutory citations in compiled
`bundle/schema-bundle.json` rules, the lowered `rezono.calc/1` program (`model.calc` / `calc.Program`),
rule proof witnesses and `calc_sql.witnesses`, 17 cases (S01–S15 preserved + Case A S16 + Case B S17)
against the independently extended stdlib-only `reference.py`, the silent-merge counterexample,
retirement of the transitional legacy Household branch, and discoverability in `examples/README.md`
(decisions/healthcare-allowance-three-sources.md, decisions/no-green-by-cheapest-route.md).
"""

from __future__ import annotations

import ast
import datetime
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SLICE = ROOT / "examples" / "zorgtoeslag-slice"
SOURCES = SLICE / "sources"
PACK = SLICE / "pack.yaml"
README = SLICE / "README.md"
EXAMPLES_README = ROOT / "examples" / "README.md"
ORACLE = SLICE / "reference.py"
CASES_FILE = SLICE / "allowance-cases.yaml"

SOURCE_PACKS = {
    "person": "zorgtoeslag-person",
    "civil": "zorgtoeslag-civil",
    "tax": "zorgtoeslag-tax",
    "insurer": "zorgtoeslag-insurer",
}

EXPECTED_PARAMS = {
    "standard_premium": {"regeling-zt#art-1", "wijziging-zt#art-I"},
    "threshold_income": {"awir#art-2.1"},
    "income_limit_single": {"wzt#art-2.2"},
    "income_limit_partner": {"wzt#art-2.2"},
}

# Exact expected outcomes for all 15 original cases (S01–S15) plus Case A (S16) and Case B (S17).
EXPECTED_CASES: dict[str, int | tuple[str, str]] = {
    "S01": 13500,
    "S02": 13600,
    "S03": 13100,
    "S04": 10500,
    "S05": 0,
    "S06": 13500,
    "S07": 8500,
    "S08": 8500,
    "S09": ("unknown", "no_version_applies"),
    "S10": 0,
    "S11": 13600,
    "S12": 0,
    "S13": ("unknown", "no_version_applies"),
    "S14": 0,
    "S15": ("unknown", "no_version_applies"),
    # Case A: married in civil registry, living apart with a divorce petition, still in tax.Partner
    # -> NOT toeslagpartner; only own income (2600000) counts.
    "S16": 13500,
    # Case B: unmarried, same residential address, joint child -> IS toeslagpartner;
    # combined income (2200000 + 2000000 = 4200000) counts.
    "S17": 11600,
}

BSN_PATTERN = re.compile(r"\b\d{9}\b")


def _load_oracle():
    assert ORACLE.is_file(), f"{ORACLE.relative_to(ROOT).as_posix()} does not exist"
    spec = importlib.util.spec_from_file_location("zorgtoeslag_three_sources_reference", ORACLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add(".")
            elif node.module:
                names.add(node.module.partition(".")[0])
    return names


def _expected_value(case: dict) -> int | tuple[str, str]:
    want = case["expect"]
    return int(want["cents"]) if "cents" in want else (str(want["state"]), str(want["reason"]))


def _claimant_id(case: dict) -> str:
    return str(case.get("claimant") or case.get("persoon") or case["household"])


def _facts_root(pack_dir: Path) -> Path:
    facts_dir = pack_dir / "facts"
    return facts_dir if facts_dir.is_dir() else pack_dir / "facts.rezono"


def _as_date(value) -> datetime.date:
    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value))


def _load_pack_rows(model, pack_dir: Path, as_of: datetime.date, known: datetime.date) -> dict[str, list[tuple]]:
    """Load every Rezono fact dataset of `pack_dir` for one `(as_of, known)` case using native ISO dates only."""
    from rezono_compiler import facts

    as_of_iso, known_iso = as_of.isoformat(), known.isoformat()
    rows: dict[str, list[tuple]] = {}
    for path in facts.files(pack_dir):
        for table, table_rows in facts.load(model, path, as_of=as_of_iso, known=known_iso).items():
            rows.setdefault(table, []).extend(table_rows)
    return rows


def _derived_joint_income_map(derived: dict[str, list[tuple]], calc_results: dict[str, dict]) -> dict[str, int]:
    """Read derived `joint_income` per person from M2 derived relations or M3 calculation rules."""
    if "joint_income" in derived:
        return {str(row[0]): int(row[1]) for row in derived["joint_income"]}
    if "joint_income" in calc_results:
        return {
            str(subject): int(val)
            for subject, (state, val, *_rest) in calc_results["joint_income"].items()
            if state == "known"
        }
    raise AssertionError("pack must derive `joint_income` as a derived relation or calculation rule")


def _strip_tax_partner_rezono_blocks(root: Path) -> None:
    """Drop `tax.Partner` fact files and `fact tax.Partner` blocks inside copied `.rezono` fact files."""
    for candidate in list(root.rglob("*.rezono")):
        if not candidate.is_file():
            continue
        if "tax" in candidate.stem.lower() and "partner" in candidate.stem.lower():
            candidate.write_text("rezono 1\npack zorgtoeslag-slice\n", encoding="utf-8", newline="\n")
            continue
        lines = candidate.read_text(encoding="utf-8").splitlines(keepends=True)
        kept: list[str] = []
        i = 0
        while i < len(lines):
            stripped = lines[i].split("--", 1)[0].strip()
            low = stripped.lower()
            if low.startswith("fact ") and "partner" in low and ("tax" in low or "fiscal" in low):
                i += 1
                while i < len(lines) and (
                    lines[i].startswith(" ")
                    or lines[i].startswith("\t")
                    or lines[i].lstrip().startswith("|")
                ):
                    i += 1
                continue
            kept.append(lines[i])
            i += 1
        if len(kept) != len(lines):
            candidate.write_text("".join(kept), encoding="utf-8", newline="\n")


def _assert_no_bsn_like_identifiers(pack_dir: Path) -> None:
    fact_files = [
        p
        for p in sorted(pack_dir.rglob("*.rezono"))
        if p.is_file() and ("facts" in p.parts or p.name == "facts.rezono")
    ]
    assert fact_files, f"no .rezono fact files found under {pack_dir}"
    for path in fact_files:
        text = path.read_text(encoding="utf-8")
        hits = [m.group(0) for m in BSN_PATTERN.finditer(text)]
        assert not hits, f"{path.relative_to(ROOT).as_posix()} contains 9-digit BSN-like numbers: {hits}"


def _assert_no_day_number_slots(bundle: dict) -> None:
    """Assert zero `*_day` or integer `day` / `YYYYMMDD` attributes exist in the compiled four-pack bundle."""
    offenders = []
    for attr in bundle.get("attributes") or []:
        slot_name = str(attr["id"]).rpartition(".")[2]
        typ = str(attr.get("type") or attr.get("range") or "").lower()
        desc = str(attr.get("description") or "").lower()
        if slot_name.endswith("_day") or (slot_name == "day" and typ in {"integer", "int"}) or "yyyymmdd" in desc:
            offenders.append((attr["id"], typ))
    assert not offenders, f"integer day-number attributes are forbidden in zorgtoeslag-slice and its sources: {offenders}"


def _assert_inline_versioned_params(model) -> None:
    """Verify inline versioned `param` declarations with valid, known and `@` sources on structured module forms."""
    found: dict[str, dict] = {}
    for mod in model.modules:
        if mod.pack != "zorgtoeslag-slice" or mod.form is None:
            continue
        assert mod.rel.startswith("rezono/") and mod.rel.endswith(".rezono"), mod.rel
        for decl in mod.form["module"]["decls"]:
            if isinstance(decl, dict) and isinstance(decl.get("param"), str):
                found[decl["param"]] = decl

    for param_name, expected_sources in EXPECTED_PARAMS.items():
        assert param_name in found, f"missing inline param {param_name!r} in examples/zorgtoeslag-slice/rezono/"
        decl = found[param_name]
        assert decl.get("type") == "Cents", (param_name, decl)
        assert "source" not in decl, f"param {param_name!r} must stay inline with versions, not row-backed: {decl}"
        versions = decl.get("versions") or []
        assert len(versions) >= 2, f"param {param_name!r} must declare versioned entries per year: {decl}"
        cited_sources: set[str] = set()
        for ver in versions:
            assert ver.get("valid") and ver.get("known"), f"param {param_name!r} version needs valid and known: {ver}"
            if isinstance(ver.get("source"), str) and ver["source"]:
                cited_sources.add(ver["source"])
        assert expected_sources <= cited_sources, (
            f"param {param_name!r} missing structured @ sources {sorted(expected_sources - cited_sources)}: {cited_sources}"
        )


def _calc_override_reasons(program, rule_name: str) -> dict[str, set[str]]:
    """Map each compiled `Definition` (`d.id`, `(version, name)`, and `d.name`) of `rule_name` in
    `calc.Program` (lowered from `rezono.calc/1` / `model.calc`) to its structured override reasons."""
    reasons_by_def: dict[str, set[str]] = {}
    for vid in program.rules.get(rule_name) or []:
        ver = program.versions[vid]
        for defn in ver.definitions:
            reasons = {str(reason) for reason in defn.reasons if reason}
            reasons_by_def.setdefault(defn.id, set()).update(reasons)
            reasons_by_def.setdefault(defn.name, set()).update(reasons)
            reasons_by_def.setdefault(f"{ver.version}#{defn.name}", set()).update(reasons)
    return reasons_by_def


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: Expand examples/zorgtoeslag-slice/ into "
           "four Rezono packs (shared Persoon + civil, tax, insurer sources) with zero .dl files, zero "
           "calc/*.yaml files, zero *_day or YYYYMMDD slots, distinct civil.Partner and tax.Partner kinds, "
           "Polis with soort basis|aanvullend, no stored partner:Bool or insured:Bool, inline versioned "
           "param declarations with valid/known/@ sources, Rezono rules for toeslagpartner/insured/"
           "joint_income under rezono/, synthetic person keys, and structured statutory citations "
           "(awr#art-5a, awir#art-3, wzt#art-2.1, wzt#art-2.2) in compiled bundle/schema-bundle.json and "
           "the lowered rezono.calc/1 program (`model.calc` / `calc.Program`) "
           "(decisions/no-green-by-cheapest-route.md). "
           "Waits for compiler/tests/rezono/test_lower_rule_sentence.py--test_lower_rule_sentence and "
           "compiler/tests/rezono/test_zorgtoeslag_slice.py--test_published_slice_gives_the_oracle.",
)
def test_three_source_packs_and_schema_drop_stored_partner_and_insured(tmp_path: Path):
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"

    # Strict Rezono-only rule, calc & fact policy: zero .dl, zero calc/*.yaml, zero YAML fact files under the slice.
    dl_files = [p.relative_to(ROOT).as_posix() for p in sorted(SLICE.rglob("*.dl"))]
    assert not dl_files, f"examples/zorgtoeslag-slice must use Rezono under rezono/, never .dl: {dl_files}"
    calc_yamls = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(SLICE.rglob("*"))
        if p.is_file() and p.suffix in {".yaml", ".yml"} and "calc" in p.relative_to(SLICE).parts
    ]
    assert not calc_yamls and not (SLICE / "calc").exists(), (
        f"examples/zorgtoeslag-slice must author calculations in rezono/*.rezono, never calc/*.yaml: {calc_yamls}"
    )
    yaml_facts = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(SLICE.rglob("*"))
        if p.is_file()
        and p.suffix in {".yaml", ".yml"}
        and "facts" in p.relative_to(SLICE).parts
        and not p.name.endswith(".sources.yaml")
    ]
    assert not yaml_facts, f"three-source facts must be .rezono, not YAML: {yaml_facts}"

    for folder, expected_name in SOURCE_PACKS.items():
        sub_dir = SOURCES / folder
        sub_pack = sub_dir / "pack.yaml"
        assert sub_pack.is_file(), f"missing source pack {sub_pack.relative_to(ROOT).as_posix()}"
        meta = yaml.safe_load(sub_pack.read_text(encoding="utf-8"))
        assert meta.get("name") == expected_name, (sub_pack, meta)
        assert meta.get("rezono"), f"source pack {expected_name} must declare Rezono modules under rezono/"

    slice_meta = yaml.safe_load(PACK.read_text(encoding="utf-8"))
    imported_names = {entry["name"] for entry in slice_meta.get("imports") or []}
    assert set(SOURCE_PACKS.values()) <= imported_names, imported_names
    assert slice_meta.get("rezono"), "examples/zorgtoeslag-slice/pack.yaml must declare Rezono modules under rezono/"

    from rezono_compiler import calc, pack
    from support import compile_dir

    try:
        model = pack.read(SLICE)
        compiled = compile_dir(SLICE, tmp_path / "compiled")
    except pack.CompileError as error:
        raise AssertionError(f"examples/zorgtoeslag-slice failed to compile: {error}") from error

    bundle = json.loads(compiled["bundle/schema-bundle.json"])
    assert model.calc is not None and "ir/calc.json" in compiled, (
        "examples/zorgtoeslag-slice must lower a rezono.calc/1 calculation program and emit ir/calc.json"
    )
    program = calc.build(model, model.calc)

    kinds_by_pack: dict[str, list[dict]] = {}
    for kind in bundle["kinds"]:
        owner_pack = kind["module"].partition(":")[0] if ":" in kind["module"] else slice_meta["name"]
        kinds_by_pack.setdefault(owner_pack, []).append(kind)

    # One shared Persoon kind from zorgtoeslag-person.
    person_kinds = [k["id"] for k in kinds_by_pack.get("zorgtoeslag-person", [])]
    assert len(person_kinds) == 1 and person_kinds[0].endswith("persoon"), person_kinds

    # Civil registry declares Adres, Partner, Ouder.
    civil_ids = [k["id"] for k in kinds_by_pack.get("zorgtoeslag-civil", [])]
    civil_partner = [kid for kid in civil_ids if kid.endswith("partner")]
    assert any(kid.endswith("adres") for kid in civil_ids), civil_ids
    assert any(kid.endswith("ouder") for kid in civil_ids), civil_ids
    assert len(civil_partner) == 1, civil_ids

    # Tax authority declares Inkomen and its own distinct Partner kind.
    tax_ids = [k["id"] for k in kinds_by_pack.get("zorgtoeslag-tax", [])]
    tax_partner = [kid for kid in tax_ids if kid.endswith("partner")]
    assert any(kid.endswith("inkomen") for kid in tax_ids), tax_ids
    assert len(tax_partner) == 1, tax_ids
    assert civil_partner[0] != tax_partner[0], (
        "civil.Partner and tax.Partner silently merged into one kind"
    )

    # Health insurer declares Polis and enum PolisSoort with basis | aanvullend.
    insurer_ids = [k["id"] for k in kinds_by_pack.get("zorgtoeslag-insurer", [])]
    assert any(kid.endswith("polis") for kid in insurer_ids), insurer_ids
    enum_values = {
        enum["id"]: {
            (v["id"] if isinstance(v, dict) else str(v)).rpartition(".")[2]
            for v in enum.get("values") or []
        }
        for enum in bundle.get("enums") or []
    }
    assert any({"basis", "aanvullend"} <= vals for vals in enum_values.values()), enum_values

    # Stored boolean facts `partner` and `insured` must disappear from the schema, and no `*_day` stopgaps exist.
    for attr in bundle.get("attributes") or []:
        slot_name = attr["id"].rpartition(".")[2]
        assert slot_name not in {"partner", "insured"}, (
            f"stored attribute {attr['id']!r} must be derived instead of stored"
        )
    _assert_no_day_number_slots(bundle)

    # Inline versioned parameters stay declared in Rezono with valid, known and @ sources.
    _assert_inline_versioned_params(model)

    # toeslagpartner, insured and joint_income are authored in Rezono under rezono/*.rezono (never rules/*.dl).
    bundle_rules = bundle.get("rules") or []
    calc_rule_names = set(program.rules)
    tp_rules = [r for r in bundle_rules if r.get("relation") == "toeslagpartner"]
    assert tp_rules, "compiled bundle/schema-bundle.json must contain Rezono rules for `toeslagpartner`"
    for rule in tp_rules:
        origin_file = (rule.get("origin") or {}).get("file", "")
        assert origin_file.startswith("rezono/") and origin_file.endswith(".rezono"), (
            f"toeslagpartner rule must originate from rezono/*.rezono, got {origin_file!r}"
        )

    for derived_name in ("insured", "joint_income"):
        in_bundle = [r for r in bundle_rules if r.get("relation") == derived_name]
        for rule in in_bundle:
            origin_file = (rule.get("origin") or {}).get("file", "")
            assert origin_file.startswith("rezono/") and origin_file.endswith(".rezono"), (
                f"{derived_name} rule must originate from rezono/*.rezono, got {origin_file!r}"
            )
        assert in_bundle or derived_name in calc_rule_names, (
            f"`{derived_name}` must be compiled from examples/zorgtoeslag-slice/rezono/"
        )

    # Structured statutory citations in compiled bundle rules and calc.Program overrides (never raw source text).
    tp_sources = {r.get("source") for r in tp_rules if r.get("source")}
    assert "awr#art-5a" in tp_sources, f"compiled toeslagpartner rules missing structured source awr#art-5a: {tp_sources}"
    assert "awir#art-3" in tp_sources, f"compiled toeslagpartner rules missing structured source awir#art-3: {tp_sources}"

    allowance_overrides = {
        reason
        for reasons in _calc_override_reasons(program, "allowance").values()
        for reason in reasons
    }
    assert {"wzt#art-2.1", "wzt#art-2.2"} <= allowance_overrides, (
        f"compiled calc.Program allowance overrides missing wzt#art-2.1 / wzt#art-2.2: {allowance_overrides}"
    )

    # Monetary calculation outputs keep exact Cents unit (no floating point).
    allowance_versions = [program.versions[vid] for vid in program.rules.get("allowance") or []]
    assert allowance_versions and all(ver.unit == "Cents" for ver in allowance_versions), allowance_versions
    assert program.result("allowance").unit == "Cents"

    _assert_no_bsn_like_identifiers(SLICE)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: Extend examples/zorgtoeslag-slice/reference.py "
           "(stdlib-only, Rezono facts with native dates only) and allowance-cases.yaml with Case A (S16: married, "
           "living apart with divorce petition -> 13500) and Case B (S17: unmarried, same address, joint child -> "
           "11600), preserve S01–S15 exactly, match the compiled three-source Rezono pack against the oracle on all "
           "17 cases, and prove statutory citations (awr#art-5a, awir#art-3, wzt#art-2.1, wzt#art-2.2) in actual "
           "rule proof witnesses and calc_sql.witnesses linked to calc.Program (decisions/no-green-by-cheapest-route.md). "
           "Waits for examples/test_zorgtoeslag_three_sources.py--test_three_source_packs_and_schema_drop_stored_partner_and_insured.",
)
def test_three_source_allowance_matches_extended_oracle_for_all_17_cases():
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"
    assert not list(SLICE.rglob("*.dl")), "examples/zorgtoeslag-slice must contain zero .dl files"
    assert not (SLICE / "calc").exists() and not list(SLICE.rglob("calc/*.yaml")), (
        "examples/zorgtoeslag-slice must author calculations in rezono/*.rezono, never calc/*.yaml"
    )

    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    by_id = {case["id"]: case for case in cases}
    assert set(EXPECTED_CASES) <= set(by_id), (
        f"missing cases in allowance-cases.yaml: {sorted(set(EXPECTED_CASES) - set(by_id))}"
    )
    for cid, want in EXPECTED_CASES.items():
        assert _expected_value(by_id[cid]) == want, (cid, by_id[cid]["expect"], want)

    # Independent oracle check: stdlib only, exposes allowance(...) and toeslagpartner(...).
    foreign = _imported_modules(ORACLE) - set(sys.stdlib_module_names)
    assert not foreign, f"reference.py must use stdlib only, found: {sorted(foreign)}"
    oracle = _load_oracle()
    assert callable(getattr(oracle, "allowance", None)), "reference.py must expose allowance(...)"
    assert callable(getattr(oracle, "toeslagpartner", None)), "reference.py must expose toeslagpartner(...)"

    facts_source = _facts_root(SLICE)
    oracle_results = {
        cid: oracle.allowance(facts_source, _claimant_id(by_id[cid]), by_id[cid]["as_of"], by_id[cid]["known"])
        for cid in EXPECTED_CASES
    }
    assert oracle_results == EXPECTED_CASES

    # Explicit derived toeslagpartner checks on key pairs.
    feb = datetime.date(2026, 2, 1)
    cut = datetime.date(2026, 2, 10)
    assert oracle.toeslagpartner(facts_source, "p-leo", "p-mia", feb, cut) is False
    assert oracle.toeslagpartner(facts_source, "p-noa", "p-sam", feb, cut) is True
    assert oracle.toeslagpartner(facts_source, "p-bob", "p-bea", feb, cut) is True
    assert oracle.toeslagpartner(facts_source, "p-kim", "p-kai", feb, cut) is True

    # Compiled and evaluated pack must derive toeslagpartner, insured, joint_income, carry structured citations
    # in its proof/calculation witnesses, and agree with the independent oracle on all 17 cases.
    from calcsupport import connect, derived_rows, run_both
    from rezono_compiler import batch, calc, calc_sql, emit, explain, pack
    from rezono_compiler import rules as ir

    model = pack.read(SLICE)
    assert model.calc is not None, "examples/zorgtoeslag-slice must declare a calculation program"
    program = calc.build(model, model.calc)
    rule_prog = ir.load(model.rules)
    bundle = emit.bundle(model, [], rule_prog)
    rule_by_id = {rule["id"]: rule for rule in bundle.get("rules") or []}
    allowance_override_map = _calc_override_reasons(program, "allowance")

    # Directly verify the compiled engine's derived relations and proof witnesses on (2026-02-01, 2026-02-10).
    feb_rows = _load_pack_rows(model, SLICE, feb, cut)
    feb_day = {calc_sql.AS_OF: [("as_of", feb.isoformat(), cut.isoformat())]}
    feb_db = connect(model, program, feb_rows | feb_day)
    feb_derived = derived_rows(feb_db, model)
    feb_got, feb_ref = run_both(model, program, model.calc, feb_rows | feb_day)
    assert feb_got == feb_ref

    assert "toeslagpartner" in feb_derived, f"missing derived relation `toeslagpartner`: {sorted(feb_derived)}"
    tp_pairs = {(str(a), str(b)) for a, b in feb_derived["toeslagpartner"]}
    assert ("p-leo", "p-mia") not in tp_pairs and ("p-mia", "p-leo") not in tp_pairs, tp_pairs
    for left, right in (("p-noa", "p-sam"), ("p-bob", "p-bea"), ("p-kim", "p-kai")):
        assert (left, right) in tp_pairs and (right, left) in tp_pairs, (left, right, tp_pairs)

    # Proof witnesses for derived `toeslagpartner` rows must resolve to Rezono rules citing awr#art-5a and awir#art-3.
    feb_data = batch.read(feb_db, rule_prog, rule_prog.base_used() + rule_prog.calc_inputs()) | batch.read(
        feb_db, rule_prog
    )
    explainer = explain.Explainer(rule_prog, feb_data, batch.witnesses(feb_db, rule_prog))
    for pair, expected_citation in ((("p-bob", "p-bea"), "awr#art-5a"), (("p-noa", "p-sam"), "awir#art-3")):
        proof = explainer.proof("toeslagpartner", pair, "2026-02-01")
        witness_rules = [rule_by_id[w["rule_id"]] for w in proof["witnesses"] if w["rule_id"] in rule_by_id]
        assert witness_rules, f"proof for toeslagpartner{pair} has no compiled rule witness: {proof}"
        for rule in witness_rules:
            origin_file = (rule.get("origin") or {}).get("file", "")
            assert origin_file.startswith("rezono/") and origin_file.endswith(".rezono"), rule
        witness_sources = {rule.get("source") for rule in witness_rules if rule.get("source")}
        assert expected_citation in witness_sources, (
            f"proof witness for toeslagpartner{pair} must cite {expected_citation!r}, got {witness_sources}"
        )

    assert any("insured" in name for name in set(feb_derived) | set(feb_got)), (
        f"pack must derive `insured`, found relations {sorted(feb_derived)} and rules {sorted(feb_got)}"
    )
    ji_map = _derived_joint_income_map(feb_derived, feb_got)
    assert ji_map.get("p-leo") == 2600000, ji_map
    assert ji_map.get("p-noa") == 4200000, ji_map
    assert ji_map.get("p-bob") == 4300000, ji_map
    assert ji_map.get("p-kim") == 5100000, ji_map
    assert "p-hal" not in ji_map, f"p-hal has no 2026 income and must stay unknown: {ji_map}"

    # Evaluate every case S01–S17 on its own (as_of, known) date through DuckDB + calcoracle + checker,
    # and verify exception override citations in calc_sql.witnesses linked to calc.Program for S05, S10 and S14.
    expected_exception_citations = {
        "S05": "wzt#art-2.2",
        "S10": "wzt#art-2.1",
        "S14": "wzt#art-2.2",
    }
    for cid, want in EXPECTED_CASES.items():
        case = by_id[cid]
        as_of, known = _as_date(case["as_of"]), _as_date(case["known"])
        rows = _load_pack_rows(model, SLICE, as_of, known)
        day = {calc_sql.AS_OF: [("as_of", as_of.isoformat(), known.isoformat())]}
        case_db = connect(model, program, rows | day)
        got, reference = run_both(model, program, model.calc, rows | day)
        assert got == reference, cid
        claimant = _claimant_id(case)
        state, value, reason, *_ = got["allowance"][claimant]
        if isinstance(want, int):
            assert state == "known" and int(value) == want, (cid, state, value, reason, want)
        else:
            assert state == want[0] and reason, (cid, state, value, reason, want)

        if cid in expected_exception_citations:
            witnesses = [
                w
                for w in calc_sql.witnesses(case_db, program)
                if w["conclusion"]["relation"] == program.engine["allowance"]
                and json.loads(w["conclusion"]["key"])[0] == claimant
            ]
            assert len(witnesses) == 1, (cid, witnesses)
            winning_ver = str(witnesses[0]["version"])
            winning_def = str(witnesses[0]["definition"])
            def_reasons = (
                allowance_override_map.get(winning_def, set())
                | allowance_override_map.get(f"{winning_ver}#{winning_def}", set())
                | allowance_override_map.get(winning_def.rpartition("#")[2], set())
            )
            assert expected_exception_citations[cid] in def_reasons, (
                f"{cid}: calculation witness ({winning_ver}, {winning_def!r}) must carry structured override "
                f"citation {expected_exception_citations[cid]!r}, got {def_reasons}"
            )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: Counterexample test proving that silently "
           "merging civil.Partner and tax.Partner by bare name produces the wrong toeslagpartner outcome and "
           "wrong allowance for Case A (S16: flips from 13500 cents single to 0 cents partnered), while "
           "removing tax.Partner rows leaves the real derivation unchanged.",
)
def test_silently_merging_civil_and_tax_partner_gives_wrong_toeslagpartner_outcome(tmp_path: Path):
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"
    oracle = _load_oracle()
    assert callable(getattr(oracle, "toeslagpartner", None)), "reference.py must expose toeslagpartner(...)"
    assert callable(getattr(oracle, "allowance", None)), "reference.py must expose allowance(...)"

    feb = datetime.date(2026, 2, 1)
    cut = datetime.date(2026, 2, 10)
    facts_source = _facts_root(SLICE)

    # 1. Real (disjoint) sources: Case A (p-leo, p-mia) is NOT toeslagpartner -> 13500 cents.
    assert oracle.toeslagpartner(facts_source, "p-leo", "p-mia", feb, cut) is False
    assert oracle.allowance(facts_source, "p-leo", feb, cut) == 13500

    # 2. Removing tax.Partner rows leaves Case A unchanged (toeslagpartner never reads tax.Partner).
    assert callable(getattr(oracle, "merge_tax_partner_into_civil", None)), (
        "reference.py must expose merge_tax_partner_into_civil(facts_dir, dest_dir) to construct the silent-merge counterexample"
    )
    without_tax_partner = tmp_path / "no-tax-partner"
    if facts_source.is_dir():
        shutil.copytree(facts_source, without_tax_partner)
    else:
        without_tax_partner.mkdir()
        shutil.copy2(facts_source, without_tax_partner / facts_source.name)
    _strip_tax_partner_rezono_blocks(without_tax_partner)
    assert oracle.toeslagpartner(without_tax_partner, "p-leo", "p-mia", feb, cut) is False
    assert oracle.allowance(without_tax_partner, "p-leo", feb, cut) == 13500

    # 3. Counterexample: silently merging tax.Partner into civil.Partner flips Case A's outcome!
    merged_dir = tmp_path / "merged-partner"
    merged_source = oracle.merge_tax_partner_into_civil(facts_source, merged_dir)
    assert not list(Path(merged_source).rglob("*.yaml")), "counterexample merge must write .rezono facts, not YAML"
    assert oracle.toeslagpartner(merged_source, "p-leo", "p-mia", feb, cut) is True, (
        "silent merge of tax.Partner into civil.Partner must demonstrate the wrong toeslagpartner=True outcome"
    )
    assert oracle.allowance(merged_source, "p-leo", feb, cut) == 0, (
        "silent merge must demonstrate the wrong allowance (0 cents instead of 13500 cents for p-leo)"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/no-green-by-cheapest-route.md: Retire the transitional legacy single-source "
           "Household branch in examples/zorgtoeslag-slice/facts.rezono and examples/zorgtoeslag-slice/reference.py "
           "once the three-source slice publishes (cleanup of the protected compiler/tests/rezono/test_zorgtoeslag_slice.py "
           "happens in a separate planner PR per scripts/red_guard.py). "
           "Waits for examples/test_zorgtoeslag_three_sources.py--test_three_source_allowance_matches_extended_oracle_for_all_17_cases.",
)
def test_retire_legacy_single_source_household_branch_in_zorgtoeslag_slice(tmp_path: Path):
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"
    assert not (SLICE / "facts.rezono").exists(), (
        "transitional single-source examples/zorgtoeslag-slice/facts.rezono must be retired"
    )
    oracle = _load_oracle()
    assert not hasattr(oracle, "_is_legacy_household_source"), (
        "transitional _is_legacy_household_source branch in reference.py must be retired"
    )

    # Substantive check: no legacy `household` fact branch remains in reference.py's AST.
    oracle_strings = {
        node.value.lower()
        for node in ast.walk(ast.parse(ORACLE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "household" not in oracle_strings, (
        "examples/zorgtoeslag-slice/reference.py still contains a legacy 'household' branch"
    )

    # Behavioral counter-case: a legacy single-source Household `.rezono` file must be refused by reference.py.
    legacy = tmp_path / "legacy-household.rezono"
    legacy.write_text(
        "rezono 0\n"
        "pack zorgtoeslag-slice\n\n"
        "fact Household\n"
        "  | id  | partner |\n"
        "  | ann | false   |\n\n"
        "fact household ann, valid 2020-01-01.., known 2020-01-05\n"
        "  insured = true\n"
        "fact household ann, valid 2026-01-01..<2027-01-01, known 2025-12-01\n"
        "  joint_income = 2500000\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(ValueError):
        oracle.allowance(legacy, "ann", datetime.date(2026, 2, 1), datetime.date(2026, 2, 10))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: Give examples/zorgtoeslag-slice/ its "
           "pack.yaml and README.md explaining in ~5 lines why 'partner' means three different things here "
           "(civil, fiscal, benefit partner) and marking the toeslagpartner rule as a simplification, and "
           "add examples/README.md placing zorgtoeslag-slice on the learning ladder of examples.",
)
def test_zorgtoeslag_slice_readme_and_examples_learning_ladder():
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"
    meta = yaml.safe_load(PACK.read_text(encoding="utf-8"))
    assert meta.get("name") == "zorgtoeslag-slice", meta

    assert README.is_file(), f"{README.relative_to(ROOT).as_posix()} does not exist yet"
    slice_readme = README.read_text(encoding="utf-8")
    lower = slice_readme.lower()

    # Explains all three meanings of "partner" concisely.
    for term in ("civil", "fiscal", "toeslagpartner"):
        assert term in lower, f"examples/zorgtoeslag-slice/README.md must explain {term!r}"
    assert "simplif" in lower, (
        "examples/zorgtoeslag-slice/README.md must mark the toeslagpartner rule as a simplification"
    )
    assert "awr#art-5a" in slice_readme and "awir#art-3" in slice_readme, (
        "examples/zorgtoeslag-slice/README.md must cite awr#art-5a and awir#art-3"
    )
    assert "synthetic" in lower or "bsn" in lower, (
        "examples/zorgtoeslag-slice/README.md must state that person keys are synthetic (never real BSNs)"
    )

    # Verify the opening explanation of the three meanings of "partner" is concise (~5 lines, at most 8).
    intro_lines = [
        line.strip()
        for line in slice_readme.split("\n## ", 1)[0].splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert 1 <= len(intro_lines) <= 8, (
        f"opening partner explanation in examples/zorgtoeslag-slice/README.md should be ~5 lines, "
        f"found {len(intro_lines)}"
    )

    # examples/README.md presents the learning ladder including zorgtoeslag-slice.
    assert EXAMPLES_README.is_file(), "examples/README.md does not exist yet"
    ladder = EXAMPLES_README.read_text(encoding="utf-8")
    assert "zorgtoeslag-slice/README.md" in ladder, (
        "examples/README.md must link to zorgtoeslag-slice/README.md"
    )
    positions = {}
    for example_name in ("library", "subsidy", "zorgtoeslag-slice", "platform"):
        idx = ladder.find(example_name)
        assert idx != -1, f"examples/README.md learning ladder must include {example_name!r}"
        positions[example_name] = idx
    assert positions["library"] < positions["subsidy"] < positions["zorgtoeslag-slice"] < positions["platform"], (
        f"examples/README.md learning ladder should order library -> subsidy -> zorgtoeslag-slice -> platform, "
        f"got {positions}"
    )
