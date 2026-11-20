"""Three-source healthcare allowance slice (`examples/zorgtoeslag-slice/`): three independent source packs
glued along one shared `Persoon` pack, derived `toeslagpartner` / `insured` / `joint_income`, 17 cases
(S01–S15 preserved + Case A S16 + Case B S17) against an independently extended stdlib-only `reference.py`,
the silent-merge counterexample, and discoverability in `examples/README.md`
(decisions/healthcare-allowance-three-sources.md).
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


def _assert_no_bsn_like_identifiers(pack_dir: Path) -> None:
    fact_files = [
        p
        for p in sorted(pack_dir.rglob("*"))
        if p.is_file()
        and p.suffix in {".rezono", ".yaml", ".yml"}
        and ("facts" in p.parts or p.name == "facts.rezono")
    ]
    assert fact_files, f"no fact files found under {pack_dir}"
    for path in fact_files:
        text = path.read_text(encoding="utf-8")
        # Exclude 64-hex hashes or comments mentioning BSN policy; catch 9-digit numbers.
        hits = [m.group(0) for m in BSN_PATTERN.finditer(text)]
        assert not hits, f"{path.relative_to(ROOT).as_posix()} contains 9-digit BSN-like numbers: {hits}"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: Expand examples/zorgtoeslag-slice/ into "
           "four packs (shared Persoon + civil, tax, insurer sources) with distinct civil.Partner and "
           "tax.Partner kinds, Polis with soort basis|aanvullend, no stored partner:Bool or insured:Bool, "
           "synthetic person keys, and toeslagpartner rules citing @ awr#art-5a and @ awir#art-3.",
)
def test_three_source_packs_and_schema_drop_stored_partner_and_insured(tmp_path: Path):
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"
    for folder, expected_name in SOURCE_PACKS.items():
        sub_pack = SOURCES / folder / "pack.yaml"
        assert sub_pack.is_file(), f"missing source pack {sub_pack.relative_to(ROOT).as_posix()}"
        meta = yaml.safe_load(sub_pack.read_text(encoding="utf-8"))
        assert meta.get("name") == expected_name, (sub_pack, meta)

    slice_meta = yaml.safe_load(PACK.read_text(encoding="utf-8"))
    imported_names = {entry["name"] for entry in slice_meta.get("imports") or []}
    assert set(SOURCE_PACKS.values()) <= imported_names, imported_names

    from rezono_compiler import pack
    from support import compile_dir

    try:
        compiled = compile_dir(SLICE, tmp_path / "compiled")
    except pack.CompileError as error:
        raise AssertionError(f"examples/zorgtoeslag-slice failed to compile: {error}") from error

    bundle = json.loads(compiled["bundle/schema-bundle.json"])
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
        enum["id"]: {v["id"] for v in enum.get("values") or []}
        for enum in bundle.get("enums") or []
    }
    assert any({"basis", "aanvullend"} <= vals for vals in enum_values.values()), enum_values

    # Stored boolean facts `partner` and `insured` must disappear from the schema.
    for attr in bundle.get("attributes") or []:
        slot_name = attr["id"].rpartition(".")[2]
        assert slot_name not in {"partner", "insured"}, (
            f"stored attribute {attr['id']!r} must be derived instead of stored"
        )

    # Authored rules/modules cite both @ awr#art-5a and @ awir#art-3.
    authored_text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in sorted(SLICE.rglob("*"))
        if p.is_file() and p.suffix in {".rezono", ".dl"}
    )
    assert "@ awr#art-5a" in authored_text or "awr#art-5a" in authored_text, "missing awr#art-5a citation"
    assert "@ awir#art-3" in authored_text or "awir#art-3" in authored_text, "missing awir#art-3 citation"

    _assert_no_bsn_like_identifiers(SLICE)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: Extend examples/zorgtoeslag-slice/reference.py "
           "(stdlib-only, no shared compiler code) and allowance-cases.yaml with Case A (S16: married, living "
           "apart with divorce petition -> 13500) and Case B (S17: unmarried, same address, joint child -> 11600), "
           "preserve S01–S15 exactly, and match the compiled three-source pack against the oracle on all 17 cases.",
)
def test_three_source_allowance_matches_extended_oracle_for_all_17_cases():
    assert PACK.is_file(), f"{PACK.relative_to(ROOT).as_posix()} does not exist yet"
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

    # Compiled and evaluated pack must agree with the independent oracle on all 17 cases.
    from calcsupport import run_both
    from rezono_compiler import calc, calc_sql, pack, scenarios

    model = pack.read(SLICE)
    program = calc.build(model, model.calc)
    (_, rows), *_ = scenarios.states(model, SLICE)
    for cid, want in EXPECTED_CASES.items():
        case = by_id[cid]
        day = {calc_sql.AS_OF: [("as_of", str(case["as_of"]), str(case["known"]))]}
        got, reference = run_both(model, program, model.calc, rows | day)
        assert got == reference, cid
        state, value, reason, *_ = got["allowance"][_claimant_id(case)]
        actual = int(value) if state == "known" else (state, reason)
        assert actual == want, (cid, actual, want)


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
    assert callable(getattr(oracle, "allowance_with_merged_partner", None)) or callable(
        getattr(oracle, "merge_tax_partner_into_civil", None)
    ), (
        "reference.py (or a test-visible helper on the three-source facts) must expose "
        "merge_tax_partner_into_civil(facts_dir, dest_dir) to construct the silent-merge counterexample"
    )
    without_tax_partner = tmp_path / "no-tax-partner"
    if facts_source.is_dir():
        shutil.copytree(facts_source, without_tax_partner)
    else:
        without_tax_partner.mkdir()
        shutil.copy2(facts_source, without_tax_partner / facts_source.name)
    # Drop any tax partner fact file/rows and re-evaluate Case A.
    for candidate in list(without_tax_partner.rglob("*tax*partner*")):
        if candidate.is_file():
            candidate.write_text("", encoding="utf-8")
    assert oracle.toeslagpartner(without_tax_partner, "p-leo", "p-mia", feb, cut) is False
    assert oracle.allowance(without_tax_partner, "p-leo", feb, cut) == 13500

    # 3. Counterexample: silently merging tax.Partner into civil.Partner flips Case A's outcome!
    merged_dir = tmp_path / "merged-partner"
    merged_source = oracle.merge_tax_partner_into_civil(facts_source, merged_dir)
    assert oracle.toeslagpartner(merged_source, "p-leo", "p-mia", feb, cut) is True, (
        "silent merge of tax.Partner into civil.Partner must demonstrate the wrong toeslagpartner=True outcome"
    )
    assert oracle.allowance(merged_source, "p-leo", feb, cut) == 0, (
        "silent merge must demonstrate the wrong allowance (0 cents instead of 13500 cents for p-leo)"
    )


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
