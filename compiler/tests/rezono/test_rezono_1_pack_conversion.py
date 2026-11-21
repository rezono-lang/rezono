"""Per-group strict red tests for single-pass pack rule conversion to native `rezono 1` modules
(decisions/language-rezono-1.md, sections 1, 2, 5.5, 5.8, 5.10, 6, 7 and 8).

Rollout order tracked here:
1. Standard packs (`packs/std-*`, M3)
2. Front-door / README / language-guide examples (`examples/subsidy`, `examples/subsidy-scheme`,
   `examples/library`, `examples/projects`, M3; `examples/zorgtoeslag` stays on `rezono 0` per
   section 5.9 item 3 and `examples/zorgtoeslag-slice` is tracked under its own slice tests)
3. `build/` and `epoch/` (`extra`)
4. `run/packs/*` (`extra`)
5. `examples/platform` including its safe steps and section 7 intended-difference contract (`extra`)
"""

from __future__ import annotations

from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import pytest
import yaml


REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
STD_ACCESS_LEGACY = FIXTURES / "std-access-legacy"
TIME = "2026-11-10T00:00:00Z"

# Standard packs that carry schema/rule definitions (std-explain and std-view are presentation-only).
RULED_STD_PACKS = (
    "std-access",
    "std-budget",
    "std-decision",
    "std-identity",
    "std-loop",
    "std-order",
    "std-part",
    "std-review",
    "std-time",
)

# Extensible rights added to packs/std-access after its initial Rezono conversion (matching test_whole_std_access.py).
POST_CONVERSION_RIGHTS = frozenset({
    "may_read_full",
    "may_propose",
    "may_review",
    "may_publish",
    "may_execute",
})

FRONT_DOOR_EXAMPLES = (
    ("examples/subsidy", True),
    ("examples/subsidy-scheme", True),
    ("examples/library", False),
    ("examples/projects", False),
)

# Per-derivation contract for examples/platform/rules/core.dl (decisions/language-rezono-1.md, section 7).
PLATFORM_RETIRED_RELATIONS = frozenset({
    "provider",
    "providers",
    "ambiguous_provider",
    "unmet_need",
    "stable_release",
    "has_stable",
})
PLATFORM_LEGACY_RENAMED_RELATIONS = frozenset({
    "zone_of",
    "on_cluster",
    "provider_chosen",
    "pinned",
    "runs",
    "newest_day",
    "behind_newest",
    "authenticates",
    "verified",
    "unverified_supply",
})
PLATFORM_CORE_FUNCTIONAL = frozenset({
    "chosen",
    "needs",
    "service_zone",
    "service_cluster",
    "service_pin",
    "service_runs",
})
PLATFORM_RENAMED_BOOL = frozenset({
    "service_behind_newest",
    "service_authenticates",
    "service_verified",
    "service_unverified_supply",
})
PLATFORM_UNCHANGED_BOOL = frozenset({
    "provides",
    "asks",
    "must_separate",
    "flow",
    "crossing",
    "firewall_rule",
    "in_zone_policy",
    "outside_reaches_inside",
    "recovery_reached",
    "recovery_reaches_out",
    "unauthenticated_target",
    "build_reaches_tenant",
})
PLATFORM_STEP_RELATIONS = frozenset({
    "platform_safe_frontier",
    "platform_safe_blocker",
    "platform_startup_goal",
    "platform_restore_goal",
})

LITERALS_AND_COMMENTS = re.compile(r'"(?:\\.|[^"\\])*"|\x60[^\x60\n]*\x60|--[^\n]*')
LEGACY_RULE_LINE = re.compile(r"^(?:rules|rule)\b", re.MULTILINE)
REZONO_1_HEADER = re.compile(r"^rezono\s+1\b")


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _dl_files_under(directory: Path) -> list[str]:
    return sorted(_rel(path) for path in directory.rglob("*.dl"))


def _first_code_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.split("--", 1)[0].strip()
        if stripped:
            return stripped
    return ""


def _form_has_derivation(decls: list[dict]) -> bool:
    for decl in decls:
        if not isinstance(decl, dict):
            continue
        if "derived" in decl and isinstance(decl["derived"], str):
            return True
        if "step" in decl:
            return True
        nested = decl.get("derived")
        if isinstance(nested, list) and nested:
            return True
    return False


def _assert_pack_is_native_rezono_1(pack_dir: Path, *, expect_rules: bool) -> tuple[object, dict[str, bytes], dict, dict]:
    """Verify a pack has zero `.dl` rules, native `rezono 1` modules (`rezono.module/5`), and compiles cleanly."""
    dl_files = _dl_files_under(pack_dir)
    assert not dl_files, f"{_rel(pack_dir)} still contains .dl rule files: {dl_files}"

    meta_path = pack_dir / "pack.yaml"
    assert meta_path.is_file(), f"missing {_rel(meta_path)}"
    meta = yaml.safe_load(meta_path.read_bytes()) or {}
    entries = meta.get("rezono") or []
    assert entries, f"{_rel(pack_dir)}/pack.yaml must declare native rezono 1 modules under `rezono:`"

    has_derivation = False
    for entry in entries:
        module_rel = entry["module"]
        form_rel = entry["form"]
        module_path = pack_dir / module_rel
        form_path = pack_dir / form_rel
        assert module_path.is_file(), f"missing module {_rel(module_path)}"
        assert form_path.is_file(), f"missing module form {_rel(form_path)}"

        raw = module_path.read_text(encoding="utf-8")
        first = _first_code_line(raw)
        assert REZONO_1_HEADER.match(first), (
            f"{_rel(module_path)} must declare `rezono 1`, found {first!r}"
        )
        tokens = LITERALS_AND_COMMENTS.sub(" ", raw)
        assert not LEGACY_RULE_LINE.search(tokens), (
            f"{_rel(module_path)} still contains rezono 0 `rules` pipe blocks or `rule` declarations"
        )

        form = json.loads(form_path.read_bytes())
        assert form.get("format") == "rezono.module/5", (
            f"{_rel(form_path)} must use format rezono.module/5, got {form.get('format')!r}"
        )
        module = form.get("module") or {}
        assert module.get("rezono") == "1", (
            f"{_rel(form_path)} must record module.rezono == '1', got {module.get('rezono')!r}"
        )
        decls = module.get("decls") or []
        for decl in decls:
            if isinstance(decl, dict):
                assert "rules" not in decl, f"{_rel(form_path)} still contains a legacy `rules` pipe block"
                assert "rule" not in decl, f"{_rel(form_path)} still contains a rezono 0 `rule` declaration"
        if _form_has_derivation(decls):
            has_derivation = True

    if expect_rules:
        assert has_derivation, (
            f"{_rel(pack_dir)} must define native rezono 1 `derived` (or `step`) declarations"
        )

    from rezono_compiler import emit, pack

    model = pack.read(pack_dir)
    files = emit.compile_pack(model)
    bundle = json.loads(files["bundle/schema-bundle.json"])
    info = bundle.get("pack") or {}
    version = info.get("language_version", info.get("rezono"))
    assert version == "1", f"{_rel(pack_dir)} bundle/schema-bundle.json must record language version '1': {info!r}"

    ir = json.loads(files["ir/rules.json"]) if "ir/rules.json" in files else {}
    if expect_rules:
        non_base = [r for r in ir.get("relations", []) if r.get("role") != "base"]
        assert non_base, f"{_rel(pack_dir)} compiled ir/rules.json has no derived or functional relations"
    return model, files, bundle, ir


def _roles_for_pack(pack_dir: Path, model) -> dict[str, str]:
    """Discover declared `Role` ids in a pack (from facts/ YAML or compiled fact tables) for per-role publication."""
    roles: dict[str, str] = {"checker": "complete"}
    from rezono_compiler import facts as fact_files

    for path in fact_files.files(pack_dir):
        loaded = fact_files.load(model, path)
        for row in loaded.get("role", ()):
            roles[str(row[0])] = "may_read"
    return roles


def _publish_checked(pack_dir: Path, store_dir: Path, roles: dict[str, str], *, epoch_num: int = 1):
    """Publish a pack through rezono_publisher and read its checked publication meaning."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_publisher import batch as publisher_batch
    from rezono_publisher import publish, store
    from scripts import convert_pack

    epoch = publisher_batch.epoch(pack_dir, epoch=epoch_num, knowledge_time=TIME, sources=[("rules", "rezono-1")])
    bucket = store.FileStore(store_dir / "verify")
    manifest = publish.publish(epoch, bucket, roles)
    proofs = next(check for check in manifest["checks"] if check["name"] == "rezono:proofs")
    assert proofs["status"] == "green" and proofs["violations"] == 0, proofs
    meaning = convert_pack.read_publication(epoch, store_dir / "meaning", roles)
    return epoch, manifest, meaning


def _load_python_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _filter_post_conversion_rights(rows: dict, visible: dict) -> tuple[dict, dict]:
    """Omit empty post-conversion @extend right relations when comparing packs/std-access against std-access-legacy."""
    filtered_rows = {
        rel: vals for rel, vals in rows.items() if not (rel in POST_CONVERSION_RIGHTS and not vals)
    }
    filtered_visible = {}
    for role, (snapshots, full, dynamic, form) in visible.items():
        kept_snaps = {
            name: body
            for name, body in snapshots.items()
            if not (name[len("relations/"):-len(".json")] in POST_CONVERSION_RIGHTS and json.loads(body) == [])
        }
        kept_full = full - POST_CONVERSION_RIGHTS
        filtered_visible[role] = (kept_snaps, kept_full, dynamic, form)
    return filtered_rows, filtered_visible


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert every standard pack under packs/std-* to native rezono 1 "
        "modules (zero .dl files and zero rezono 0 rules pipe blocks remaining in packs/std-*) with whole-pack "
        "equivalence across facts, conclusions, checked grounds, and per-role views. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "and examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch."
    ),
)
def test_standard_packs_convert_to_rezono_1(tmp_path: Path):
    std_packs = sorted(p.parent for p in (REPO / "packs").glob("std-*/pack.yaml"))
    assert std_packs, "expected standard packs under packs/std-*"

    dl_files = sorted(
        _rel(path) for pack_dir in std_packs for path in pack_dir.rglob("*.dl")
    )
    assert not dl_files, f"packs/std-* still contains .dl files: {dl_files}"

    by_name = {pack_dir.name: pack_dir for pack_dir in std_packs}
    for name in RULED_STD_PACKS:
        assert name in by_name, f"missing expected standard pack packs/{name}"
        _assert_pack_is_native_rezono_1(by_name[name], expect_rules=True)

    # Any additional std-* pack that declares rules or schemas must also be native rezono 1.
    for pack_dir in std_packs:
        if pack_dir.name in RULED_STD_PACKS:
            continue
        meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
        if meta.get("rezono") or (pack_dir / "schema").is_dir():
            _assert_pack_is_native_rezono_1(pack_dir, expect_rules=False)

    # scripts/language_usage.py must report zero legacy `relational-rule` files across packs/std-*.
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from scripts import convert_pack, language_usage

    packs_inv = language_usage.inventory(REPO)
    legacy_std = [
        _rel(folder)
        for folder in std_packs
        if "relational-rule" in {f for vals in packs_inv.get(folder.resolve(), language_usage.PackUsage({}, (), False)).files.values() for f in vals}
    ]
    assert not legacy_std, f"language_usage.py still reports legacy relational-rule in packs/std-*: {legacy_std}"

    # Independent legacy oracle whole-pack equivalence for packs/std-access through examples/subsidy.
    from rezono_compiler import modules, pack, standard_packs

    def _subsidy_over_std_access(form: str):
        root = tmp_path / f"std-access-{form}"
        shutil.copytree(REPO / "packs", root / "packs")
        for example in ("examples/subsidy", "examples/subsidy-scheme"):
            shutil.copytree(REPO / example, root / example)
        access = root / "packs" / "std-access"
        meta_path = access / "pack.yaml"
        meta = yaml.safe_load(meta_path.read_bytes())
        if form == "legacy":
            shutil.rmtree(access / "rezono", ignore_errors=True)
            for rel_name in ("schema/access.yaml", "rules/access.dl"):
                dest = access / rel_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(STD_ACCESS_LEGACY / rel_name, dest)
            meta.pop("rezono", None)
            meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
        consumer = root / "examples" / "subsidy"
        consumer_meta = yaml.safe_load((consumer / "pack.yaml").read_bytes())
        pin = modules.pack_hash(access)
        for entry in consumer_meta["imports"]:
            if entry["name"] == "std-access":
                entry["sha256"] = pin
        (consumer / "pack.yaml").write_text(yaml.safe_dump(consumer_meta, sort_keys=False), encoding="utf-8")
        ctx = standard_packs.trial("std-access", pin) if form == "legacy" else nullcontext()
        with ctx:
            model = pack.read(consumer)
            roles = _roles_for_pack(consumer, model)
            _, _, meaning = _publish_checked(consumer, tmp_path / f"store-{form}", roles)
        return _filter_post_conversion_rights(meaning.rows, meaning.visible)

    legacy_rows, legacy_visible = _subsidy_over_std_access("legacy")
    native_rows, native_visible = _subsidy_over_std_access("rezono1")
    assert native_rows == legacy_rows, "packs/std-access rezono 1 conversion changed derived rows"
    assert native_visible == legacy_visible, "packs/std-access rezono 1 conversion changed per-role views"

    # Any standard pack with a committed legacy oracle fixture under fixtures/<name>-legacy/ must match via compare_publications.
    for pack_dir in std_packs:
        if pack_dir.name == "std-access":
            continue
        legacy_oracle = FIXTURES / f"{pack_dir.name}-legacy"
        if legacy_oracle.is_dir() and (pack_dir / "facts").is_dir():
            from rezono_publisher import batch as publisher_batch

            base_epoch = publisher_batch.epoch(legacy_oracle, epoch=1, knowledge_time=TIME, sources=[("rules", "legacy")])
            trial_epoch = publisher_batch.epoch(pack_dir, epoch=1, knowledge_time=TIME, sources=[("rules", "rezono-1")])
            convert_pack.compare_publications(base_epoch, trial_epoch, {"checker": "complete"})


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert the front-door, README, and language-guide examples "
        "(examples/subsidy, examples/subsidy-scheme, examples/library, examples/projects) to native rezono 1 "
        "modules with zero .dl files and whole-pack equivalence against independent reference/expected oracles "
        "and per-role checked publications. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and compiler/tests/rezono/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
    ),
)
def test_front_door_examples_convert_to_rezono_1(tmp_path: Path):
    compiled = {}
    for rel_path, expect_rules in FRONT_DOOR_EXAMPLES:
        pack_dir = REPO / rel_path
        compiled[rel_path] = _assert_pack_is_native_rezono_1(pack_dir, expect_rules=expect_rules)

    # 1. examples/subsidy (importing examples/subsidy-scheme): checked publication + per-role views + reference.py oracle.
    subsidy_dir = REPO / "examples" / "subsidy"
    subsidy_model, _, _, _ = compiled["examples/subsidy"]
    roles = _roles_for_pack(subsidy_dir, subsidy_model)
    assert {"checker", "case_officer", "policy_adviser", "propose", "public", "viewer"} <= set(roles), roles
    _, _, meaning = _publish_checked(subsidy_dir, tmp_path / "subsidy-store", roles)

    # Role scoping check: every reader sees scheme articles; case_officer/propose see applications; public sees none.
    for role in ("case_officer", "policy_adviser", "propose", "public", "viewer"):
        snaps = meaning.visible[role][0]
        assert json.loads(snaps["relations/article.json"]), f"{role} must see scheme articles"
    for role in ("case_officer", "propose"):
        assert json.loads(meaning.visible[role][0]["relations/application.json"]), f"{role} must see applications"
    assert json.loads(meaning.visible["public"][0]["relations/application.json"]) == [], (
        "public role must see zero applications"
    )

    # Compare derived conclusions & award calculations against the independent stdlib oracle reference.py.
    ref = _load_python_module(subsidy_dir / "reference.py", "subsidy_reference_oracle")
    (_, base_state), *_ = list(ref.states())
    expected_rules = ref.rules(base_state)
    for rel_name, want_rows in expected_rules.items():
        if rel_name in meaning.rows:
            got_rows = sorted([str(cell) for cell in row] for row in meaning.rows[rel_name])
            assert got_rows == want_rows, f"examples/subsidy derived relation {rel_name} diverged from reference.py"
        else:
            # Functional replacement `<k>_<d>` for a single-key derived property.
            alt = f"application_{rel_name}"
            assert alt in meaning.rows, f"examples/subsidy missing derived relation {rel_name!r} (or {alt!r})"
            got_known = sorted([str(row[0]), str(row[-1])] for row in meaning.rows[alt] if row[1] == "known")
            assert got_known == want_rows, f"examples/subsidy functional {alt} diverged from reference.py"

    expected_calc = ref.calc(base_state)
    for rule_name, by_app in expected_calc.items():
        functional_name = next(
            (cand for cand in (f"application_{rule_name}", rule_name) if cand in meaning.rows),
            None,
        )
        assert functional_name is not None, (
            f"examples/subsidy must publish rezono 1 functional derivation for {rule_name!r}"
        )
        observed = {}
        for row in meaning.rows[functional_name]:
            subject, state, _reason, value = str(row[0]), str(row[1]), str(row[2]), str(row[3])
            observed[subject] = value if state == "known" else state
        assert observed == by_app, f"examples/subsidy {functional_name} diverged from reference.py"

    # 2. examples/library and examples/projects: dataset violation equivalence + checked valid publication.
    from rezono_compiler import facts as fact_files
    from support import text, violations

    for rel_path in ("examples/library", "examples/projects"):
        pack_dir = REPO / rel_path
        model, files, _, _ = compiled[rel_path]
        datasets = fact_files.files(pack_dir)
        assert {path.stem for path in datasets} == {"valid", "errors"}, (rel_path, datasets)
        for path in datasets:
            rows = fact_files.load(model, path)
            got = violations(files, rows)
            want = json.loads((pack_dir / "expected" / "violations" / f"{path.stem}.json").read_text(encoding="utf-8"))
            assert got == text({k: {tuple(r) for r in v} for k, v in want.items()}), (rel_path, path.stem)

    # Publish the valid slice of examples/library (matching README.md quickstart step 1).
    lib_copy = tmp_path / "library-valid"
    shutil.copytree(REPO / "examples" / "library", lib_copy)
    for err_file in list(lib_copy.rglob("errors.yaml")) + list(lib_copy.rglob("errors.rezono")) + list(lib_copy.rglob("errors.json")):
        err_file.unlink()
    lib_meta_path = lib_copy / "pack.yaml"
    lib_meta = yaml.safe_load(lib_meta_path.read_bytes())
    if lib_meta.get("rezono"):
        lib_meta["rezono"] = [e for e in lib_meta["rezono"] if Path(e["module"]).stem != "errors"]
        lib_meta_path.write_text(yaml.safe_dump(lib_meta, sort_keys=False), encoding="utf-8")
    _publish_checked(lib_copy, tmp_path / "library-store", {"reader": "complete"})


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/language-rezono-1.md: Convert build/ and epoch/ .dl rules to native rezono 1 modules "
        "(zero .dl files remaining in build/ and epoch/) with whole-pack equivalence across compiled relations, "
        "checked publications, and per-role views. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and compiler/tests/rezono/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
    ),
)
def test_build_and_epoch_packs_convert_to_rezono_1(tmp_path: Path):
    build_dir = REPO / "build"
    epoch_dir = REPO / "epoch"

    build_model, _, _, build_ir = _assert_pack_is_native_rezono_1(build_dir, expect_rules=True)
    _, _, _, epoch_ir = _assert_pack_is_native_rezono_1(epoch_dir, expect_rules=True)

    build_relations = {r["name"] for r in build_ir.get("relations", []) if r.get("role") != "base"}
    assert {
        "may_read",
        "may_read_full",
        "build_milestone_progress",
        "release_1_done",
        "build_offboard_work_count",
        "build_offboard_work_unknown",
    } <= build_relations, sorted(build_relations)

    epoch_relations = {r["name"] for r in epoch_ir.get("relations", []) if r.get("role") != "base"}
    assert {"publish_allowed", "epoch_allowed", "derived_refusal"} <= epoch_relations, sorted(epoch_relations)

    build_roles = _roles_for_pack(build_dir, build_model)
    assert {"checker", "coordinator", "owner"} <= set(build_roles), build_roles
    _, _, build_meaning = _publish_checked(build_dir, tmp_path / "build-store", build_roles)
    for role in ("coordinator", "owner"):
        assert json.loads(build_meaning.visible[role][0]["relations/role.json"]), (
            f"build/ role {role} must see declared roles under rezono 1 access rules"
        )

    _publish_checked(epoch_dir, tmp_path / "epoch-store", {"checker": "complete"})


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/language-rezono-1.md: Convert every run/packs/* pack (.dl rules and embedded rezono 0 "
        "rules pipe blocks) to native rezono 1 modules with zero .dl files remaining under run/packs/ and "
        "whole-pack equivalence (including run/packs/exact-quote exact amount_digit output). "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and compiler/tests/rezono/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
    ),
)
def test_run_packs_convert_to_rezono_1(tmp_path: Path):
    run_packs_dir = REPO / "run" / "packs"
    run_packs = sorted(p.parent for p in run_packs_dir.glob("*/pack.yaml"))
    assert run_packs, "expected packs under run/packs/*"

    dl_files = _dl_files_under(run_packs_dir)
    assert not dl_files, f"run/packs/ still contains .dl files: {dl_files}"

    for pack_dir in run_packs:
        model, _, _, _ = _assert_pack_is_native_rezono_1(pack_dir, expect_rules=True)
        if (pack_dir / "facts").is_dir():
            roles = _roles_for_pack(pack_dir, model)
            _publish_checked(pack_dir, tmp_path / f"store-{pack_dir.name}", roles)

    # Exact amount_digit verification for run/packs/exact-quote using RecordedQuote / RecordedLine /
    # QuoteDigit / QuoteCarry facts: 2 * (3 * 4 + 5) = 34 (little-endian digits: pos 0 -> 4, pos 1 -> 3).
    sample_quote = {
        "recorded_quote": [{"id": "q-1"}],
        "recorded_line": [{"id": "l-1", "quote": "q-1"}],
        "quote_digit": [
            {"id": "d-qty-0", "line": "l-1", "operand": "quantity", "position": 0, "value": 2},
            {"id": "d-per-0", "line": "l-1", "operand": "billed_periods", "position": 0, "value": 3},
            {"id": "d-ppm-0", "line": "l-1", "operand": "period_price_micros", "position": 0, "value": 4},
            {"id": "d-spm-0", "line": "l-1", "operand": "setup_price_micros", "position": 0, "value": 5},
        ],
        "quote_carry": [
            {"id": f"c-{amount}-{pos}", "amount": amount, "position": pos, "value": val}
            for amount in ("l-1", "q-1")
            for pos, val in ((0, 0), (1, 3), (2, 0))
        ],
    }
    sample_sources = (
        "default:\n"
        "  kind: git\n"
        "  name: rezono-lang/rezono\n"
        '  revision: "0000000"\n'
        "  position: compiler/tests/rezono/test_rezono_1_pack_conversion.py#exact-quote-sample\n"
    )
    native_copy = tmp_path / "exact-quote-rezono1"
    shutil.copytree(run_packs_dir / "exact-quote", native_copy)
    (native_copy / "facts").mkdir(exist_ok=True)
    (native_copy / "facts" / "sample.yaml").write_text(
        yaml.safe_dump(sample_quote, sort_keys=False), encoding="utf-8", newline="\n"
    )
    (native_copy / "facts" / "sample.sources.yaml").write_text(sample_sources, encoding="utf-8", newline="\n")
    _, _, native_meaning = _publish_checked(native_copy, tmp_path / "eq-native-store", {"checker": "complete"})
    expected_digits = {
        ("l-1", "0", "4"),
        ("l-1", "1", "3"),
        ("q-1", "0", "4"),
        ("q-1", "1", "3"),
    }
    got_digits = {tuple(str(cell) for cell in row) for row in native_meaning.rows["amount_digit"]}
    assert got_digits == expected_digits, (
        f"run/packs/exact-quote rezono 1 conversion changed derived amount_digit rows: {got_digits!r}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/language-rezono-1.md: Convert examples/platform/rules/*.dl (including its safe steps "
        "and examples/platform/tenant-capacity/interface) to native rezono 1 modules with whole-pack equivalence "
        "and explicit verification of every intended semantic difference in decisions/language-rezono-1.md section 7. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and compiler/tests/rezono/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
    ),
)
def test_platform_pack_converts_to_rezono_1_with_intended_differences(tmp_path: Path):
    platform_dir = REPO / "examples" / "platform"
    iface_dir = platform_dir / "tenant-capacity" / "interface"

    dl_files = _dl_files_under(platform_dir)
    assert not dl_files, f"examples/platform still contains .dl files: {dl_files}"

    _assert_pack_is_native_rezono_1(iface_dir, expect_rules=True)
    platform_model, _, _, platform_ir = _assert_pack_is_native_rezono_1(platform_dir, expect_rules=True)

    by_name = {r["name"]: r for r in platform_ir.get("relations", []) if r.get("role") != "base"}

    # Safe-step / round relations remain compiled under rezono 1.
    assert PLATFORM_STEP_RELATIONS <= set(by_name), sorted(PLATFORM_STEP_RELATIONS - set(by_name))

    # Section 7 contract: retired helpers/findings and legacy renamed names must be absent.
    leftover_retired = sorted((PLATFORM_RETIRED_RELATIONS | PLATFORM_LEGACY_RENAMED_RELATIONS) & set(by_name))
    assert not leftover_retired, f"retired or renamed legacy core.dl relations still present: {leftover_retired}"

    # Section 7 contract: functional derivations use role == "functional".
    for rel_name in sorted(PLATFORM_CORE_FUNCTIONAL):
        assert rel_name in by_name, f"missing rezono 1 functional derivation {rel_name!r}"
        assert by_name[rel_name].get("role") == "functional", (rel_name, by_name[rel_name])

    # Section 7 forward note (decisions/platform-facts-not-conclusions.md §§4-5): product_newest_day and
    # flow_from_step/needs_service are functional/derived unless already retired with released_on_day / Service.step.
    if "product_newest_day" in by_name:
        assert by_name["product_newest_day"].get("role") == "functional", by_name["product_newest_day"]
    if "flow_from_step" in by_name:
        assert by_name["flow_from_step"].get("role") == "functional", by_name["flow_from_step"]
        assert by_name.get("needs_service", {}).get("role") == "derived", by_name.get("needs_service")

    # Section 7 contract: renamed and unchanged Bool derivations use role == "derived".
    for rel_name in sorted(PLATFORM_RENAMED_BOOL | PLATFORM_UNCHANGED_BOOL):
        assert rel_name in by_name, f"missing rezono 1 Bool derivation {rel_name!r}"
        assert by_name[rel_name].get("role") == "derived", (rel_name, by_name[rel_name])
    assert len(by_name["service_behind_newest"].get("key", [])) == 1, (
        "service_behind_newest must have arity-1 key (s: Service) per section 7"
    )

    # Whole-pack checked publication and parity against examples/platform/oracle-rows.json.
    roles = _roles_for_pack(platform_dir, platform_model)
    assert "checker" in roles and len(roles) > 1, roles
    _, _, base_meaning = _publish_checked(platform_dir, tmp_path / "platform-store", roles)

    oracle_rows = json.loads((platform_dir / "oracle-rows.json").read_text(encoding="utf-8"))
    for retired in ("ambiguous_provider", "unmet_need", "zone_of", "on_cluster", "runs", "behind_newest", "unverified_supply"):
        assert retired not in oracle_rows, (
            f"examples/platform/oracle-rows.json must migrate off legacy key {retired!r} in lockstep (section 5.5)"
        )
    for rel_name, want in oracle_rows.items():
        assert rel_name in base_meaning.rows, f"oracle-rows.json relation {rel_name!r} missing from publication"
        got = sorted([str(cell) for cell in row] for row in base_meaning.rows[rel_name])
        want_str = sorted([str(cell) for cell in row] for row in want)
        assert got == want_str, f"examples/platform published relation {rel_name!r} diverged from oracle-rows.json"

    # Explicit behavioral verification of section 7 intended semantic differences on isolated copies.
    core_facts = yaml.safe_load((platform_dir / "facts" / "core.yaml").read_text(encoding="utf-8"))
    services = [row["id"] for row in core_facts["service"]]
    asks_rows = sorted(base_meaning.rows["asks"])
    assert asks_rows, "examples/platform must derive non-empty asks(s, f)"
    sample_consumer, sample_fn = asks_rows[0]
    other_providers = [s for s in services if s != sample_consumer][:2]
    assert len(other_providers) == 2

    # 1. Conflicting Choice rows for (sample_consumer, sample_fn) -> chosen & needs become invalid multiple_values,
    # and flow emits no tuple for (sample_consumer, *, sample_fn, *).
    choice_copy = tmp_path / "platform-choice-conflict"
    shutil.copytree(REPO / "packs", choice_copy / "packs")
    shutil.copytree(platform_dir, choice_copy / "examples" / "platform")
    c_pack = choice_copy / "examples" / "platform"
    c_core_path = c_pack / "facts" / "core.yaml"
    c_core = yaml.safe_load(c_core_path.read_text(encoding="utf-8"))
    c_core["choice"] = [
        row for row in c_core.get("choice", [])
        if not (row.get("service") == sample_consumer and row.get("function") == sample_fn)
    ] + [
        {"id": "conflict-choice-a", "service": sample_consumer, "function": sample_fn, "provider": other_providers[0]},
        {"id": "conflict-choice-b", "service": sample_consumer, "function": sample_fn, "provider": other_providers[1]},
    ]
    c_core_path.write_text(yaml.safe_dump(c_core, sort_keys=False), encoding="utf-8")
    _, _, choice_meaning = _publish_checked(c_pack, tmp_path / "choice-store", {"checker": "complete"})
    chosen_state = {(r[0], r[1]): (r[2], r[3]) for r in choice_meaning.rows["chosen"]}
    needs_state = {(r[0], r[1]): (r[2], r[3]) for r in choice_meaning.rows["needs"]}
    assert chosen_state[(sample_consumer, sample_fn)] == ("invalid", "multiple_values"), chosen_state
    assert needs_state[(sample_consumer, sample_fn)] == ("invalid", "multiple_values"), needs_state
    assert not [r for r in choice_meaning.rows["flow"] if r[0] == sample_consumer and r[2] == sample_fn], (
        "section 7: conflicting Choice rows must suppress flow for (a, *, f, *)"
    )

    # 2. Conflicting Pin rows for one service (same product per Pin.same_product) -> service_pin & service_runs
    # become invalid multiple_values, and service_behind_newest emits no tuple for that service.
    releases_by_product: dict[str, list[str]] = {}
    for row in core_facts["release"]:
        releases_by_product.setdefault(row["product"], []).append(row["id"])
    pinned_candidates = [
        (row["id"], releases_by_product[row["product"]][:2])
        for row in core_facts["service"]
        if len(releases_by_product.get(row["product"], ())) >= 2
    ]
    assert pinned_candidates, "examples/platform must have a service whose product has >= 2 releases"
    sample_service, sample_releases = pinned_candidates[0]
    pin_copy = tmp_path / "platform-pin-conflict"
    shutil.copytree(REPO / "packs", pin_copy / "packs")
    shutil.copytree(platform_dir, pin_copy / "examples" / "platform")
    p_pack = pin_copy / "examples" / "platform"
    p_core_path = p_pack / "facts" / "core.yaml"
    p_core = yaml.safe_load(p_core_path.read_text(encoding="utf-8"))
    p_core["pin"] = [
        row for row in p_core.get("pin", []) if row.get("service") != sample_service
    ] + [
        {"id": "conflict-pin-a", "service": sample_service, "release": sample_releases[0]},
        {"id": "conflict-pin-b", "service": sample_service, "release": sample_releases[1]},
    ]
    p_core_path.write_text(yaml.safe_dump(p_core, sort_keys=False), encoding="utf-8")
    _, _, pin_meaning = _publish_checked(p_pack, tmp_path / "pin-store", {"checker": "complete"})
    pin_state = {r[0]: (r[1], r[2]) for r in pin_meaning.rows["service_pin"]}
    runs_state = {r[0]: (r[1], r[2]) for r in pin_meaning.rows["service_runs"]}
    assert pin_state[sample_service] == ("invalid", "multiple_values"), pin_state
    assert runs_state[sample_service] == ("invalid", "multiple_values"), runs_state
    assert not [r for r in pin_meaning.rows["service_behind_newest"] if r[0] == sample_service], (
        "section 7: conflicting Pin rows must suppress service_behind_newest for that service"
    )
