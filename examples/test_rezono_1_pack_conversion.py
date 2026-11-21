"""Strict red tests for single-pass pack rule conversion to native `rezono 1` modules, one case per pack, for
the standard packs (`packs/std-*`), the front-door examples (`examples/subsidy`, `examples/subsidy-scheme`,
`examples/library`, `examples/projects`), and one for `examples/platform`
(decisions/language-rezono-1.md, sections 1, 2, 5.5, 5.8, 5.10, 6, 7 and 8;
decisions/standard-packs-everywhere.md, section 1.4;
decisions/platform-facts-not-conclusions.md, sections 3, 4 and 5).

Each standard pack and each front-door example has a strict red case of its own (`examples/subsidy-scheme` and
`examples/subsidy` share one), so that each converts on its own task branch, leaves first: a case waits for the cases
of the packs it imports, and for the red tests of the rezono 1 rule constructs its rules need
(`compiler/tests/rezono/test_lower_rezono_1_imported_derived.py`, `test_lower_rezono_1_rule_constructs.py`). The cases keep every assertion of the
former whole-group tests `test_standard_packs_convert_to_rezono_1` and `test_front_door_examples_convert_to_rezono_1`;
`test_every_standard_pack_has_its_own_conversion_case` keeps their reach over every pack under `packs/std-*`.

Companions for the other two conversion groups live in their owning components:
- `loop/tests/test_rezono_1_build_epoch_conversion.py` (`build/` and `epoch/`)
- `run/tests/test_rezono_1_run_packs_conversion.py` (`run/packs/*`)
"""
from __future__ import annotations

from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
LEGACY_HELPERS_PATH = REPO / "examples" / "fixtures" / "rezono-1-legacy" / "helpers.py"


def _load_python_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LEGACY = _load_python_module(LEGACY_HELPERS_PATH, "rezono_1_legacy_helpers")
TIME = _LEGACY.TIME

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

# Synthetic exercise facts (with `kind: synthetic` origins per decisions/fact-origin-required.md §3)
# used to compare every ruled standard pack non-vacuously via `scripts.convert_pack.compare_publications`.
# Theory packs with abstract kinds (`std-identity`, `std-order`, `std-part`, `std-time`) are exercised
# through a minimal consumer schema declaring a concrete child kind (`is_a: ...`).
# Calendar dates use ISO dates only (no day-number stopgaps; decisions/standard-packs-everywhere.md §1.4).
STD_PACK_EXERCISES: dict[str, dict] = {
    "std-budget": {
        "rows": {
            "budget_entry": [
                {"id": "e-base", "budget": "demo", "cell": "a", "ceiling": 5, "revision": "base"},
                {"id": "e-head", "budget": "demo", "cell": "a", "ceiling": 5, "revision": "head"},
            ],
            "budget_reading": [
                {"id": "r-base", "budget": "demo", "cell": "a", "observed": 3, "revision": "base"},
                {"id": "r-head", "budget": "demo", "cell": "a", "observed": 3, "revision": "head"},
            ],
        },
    },
    "std-decision": {
        "rows": {
            "decision": [
                {"id": "d-1", "title": "Sample", "state": "in_force", "decider": ["board"], "valid_from": "2026-01-01"},
            ],
            "reference_date": [
                {"id": "now", "title": "Now", "date": "2026-06-01"},
            ],
        },
    },
    "std-identity": {
        "import_module": "std-identity:identity",
        "child_class": ("Item", "Referent", "item"),
        "rows": {
            "item": [{"id": "r1"}, {"id": "r2", "same_as": ["r1"]}],
        },
    },
    "std-loop": {
        "rows": {
            "loop_active_run": [{"id": "run-1"}],
            "loop_step": [{"id": "step-1"}],
            "loop_goal": [{"id": "g-1", "run": "run-1", "token": "tok-1"}],
        },
    },
    "std-order": {
        "import_module": "std-order:order",
        "child_class": ("Item", "Ordered", "item"),
        "rows": {
            "item": [{"id": "o1", "precedes": ["o2"]}, {"id": "o2"}],
        },
    },
    "std-part": {
        "import_module": "std-part:part",
        "child_class": ("Item", "Constituent", "item"),
        "rows": {
            "item": [{"id": "whole"}, {"id": "part", "part_of": "whole"}],
        },
    },
    # Waits for packs/std-review native date migration (decisions/standard-packs-everywhere.md §1.4 step 5).
    "std-review": {
        "rows": {
            "change": [
                {"id": "ch-1", "author": "alice", "content_sha256": "a" * 64, "support_sha256": "b" * 64},
            ],
            "change_member": [
                {"id": "cm-1", "change": "ch-1", "kind": "item", "element": "x1"},
            ],
            "review": [
                {
                    "id": "rev-1",
                    "change": "ch-1",
                    "reviewer": "bob",
                    "role": "reviewer",
                    "verdict": "accepted",
                    "date": "2026-06-10",
                    "content_sha256": "a" * 64,
                    "support_sha256": "b" * 64,
                },
            ],
            "role_grant": [
                {"id": "rg-1", "subject": "bob", "role": "reviewer", "valid_from": "2026-06-01"},
            ],
            "review_phase": [
                {"id": "ph-1", "phase": "strict", "owner": "owner"},
            ],
            "review_policy": [
                {"id": "pol-1", "kind": "item", "policy": "require"},
            ],
        },
    },
    "std-time": {
        "import_module": "std-time:time",
        "child_class": ("Item", "Interval", "item"),
        "rows": {
            "axis": [{"id": "ax-1"}],
            "item": [{"id": "iv-1", "on_axis": "ax-1", "start": 1, "end": 10}],
            "reference_point": [{"id": "rp-1", "on_axis": "ax-1", "position": 5, "horizon": 2}],
        },
    },
}

# Exact bundle relation names for examples/subsidy calculations in rezono 1 (<k>_<d>, section 2 & 5.6).
SUBSIDY_CALC_RELATIONS = (
    "income_threshold",
    "income_limit",
    "cost_share",
    "advice_allowance",
    "entitlement",
    "award",
    "payment_difference",
)

# Per-derivation contract for examples/platform/rules/core.dl
# (decisions/language-rezono-1.md §7 + forward note from decisions/platform-facts-not-conclusions.md §§4-5).
PLATFORM_RETIRED_RELATIONS = frozenset({
    "provider",
    "providers",
    "ambiguous_provider",
    "unmet_need",
    "stable_release",
    "has_stable",
    "newest_day",
    "product_newest_day",
    "flow_from_step",
    "needs_service",
})
PLATFORM_LEGACY_RENAMED_RELATIONS = frozenset({
    "zone_of",
    "on_cluster",
    "provider_chosen",
    "pinned",
    "runs",
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
# All legacy and native relation names covered by section 7's explicit intended-difference mapping.
PLATFORM_SECTION_7_LEGACY = (
    PLATFORM_RETIRED_RELATIONS
    | PLATFORM_LEGACY_RENAMED_RELATIONS
    | {"needs"}
)
PLATFORM_SECTION_7_NATIVE = (
    PLATFORM_CORE_FUNCTIONAL
    | PLATFORM_RENAMED_BOOL
)


def _build_consumer_for_std_pack(root: Path, std_name: str, spec: dict, label: str) -> Path:
    """Wrap `root/packs/<std_name>` in a minimal consumer pack carrying synthetic exercise facts."""
    from rezono_compiler import modules

    std_dir = root / "packs" / std_name
    consumer = root / f"exercise-{std_name}-{label}"
    consumer.mkdir(parents=True)
    meta = {
        "name": f"exercise-{std_name}",
        "version": "0.1.0",
        "default_language": "en",
        "imports": [{"name": std_name, "path": f"../packs/{std_name}", "sha256": modules.pack_hash(std_dir)}],
    }
    (consumer / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")

    imports = ["linkml:types"]
    if "import_module" in spec:
        imports.append(spec["import_module"])
    if "child_class" in spec:
        cls_name, parent_name, snake_name = spec["child_class"]
        classes = {cls_name: {"is_a": parent_name}}
    else:
        cls_name, snake_name = "HarnessMarker", "harness_marker"
        classes = {cls_name: {"attributes": {"id": {"identifier": True}}}}

    schema_doc = {
        "id": f"https://rezono.org/test/exercise-{std_name}",
        "name": f"exercise_{std_name.replace('-', '_')}",
        "default_range": "string",
        "imports": imports,
        "annotations": {"layer": "facts"},
        "classes": classes,
    }
    (consumer / "schema").mkdir()
    (consumer / "schema" / "harness.yaml").write_text(
        yaml.safe_dump(schema_doc, sort_keys=False), encoding="utf-8", newline="\n"
    )
    (consumer / "channels.yaml").write_text(
        f"kinds:\n  - {{kind: {snake_name}, shape: rect}}\narrows: []\n", encoding="utf-8", newline="\n"
    )
    (consumer / "labels").mkdir()
    (consumer / "labels" / "en.yaml").write_text(
        f"{snake_name}: Exercise {snake_name}\n", encoding="utf-8", newline="\n"
    )
    (consumer / "facts").mkdir()
    (consumer / "facts" / "exercise.yaml").write_text(
        yaml.safe_dump(spec["rows"], sort_keys=False), encoding="utf-8", newline="\n"
    )
    (consumer / "facts" / "exercise.sources.yaml").write_text(
        _LEGACY.synthetic_sidecar("examples/test_rezono_1_pack_conversion.py", f"std-pack-exercise:{std_name}"),
        encoding="utf-8",
        newline="\n",
    )
    return consumer


def _publish_with_witnesses(pack_dir: Path, store_dir: Path, roles: dict[str, str]):
    """Publish a pack through rezono_publisher, verify `rezono:proofs` green, and return meaning + witnesses."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_publisher import batch as publisher_batch
    from rezono_publisher import publish, store
    from scripts import convert_pack

    epoch = publisher_batch.epoch(pack_dir, epoch=1, knowledge_time=TIME, sources=[("rules", "rezono-1")])
    bucket = store.FileStore(store_dir / "verify")
    manifest = publish.publish(epoch, bucket, roles)
    proofs = next(check for check in manifest["checks"] if check["name"] == "rezono:proofs")
    assert proofs["status"] == "green" and proofs["violations"] == 0, proofs
    meaning = convert_pack.read_publication(epoch, store_dir / "meaning", roles)
    complete_role = next(role for role, mode in roles.items() if mode == "complete")
    objects = publish.role_objects(bucket, epoch.pack, manifest["id"], complete_role)
    witnesses = json.loads(bucket.get(objects["witnesses.json"]))
    return epoch, manifest, meaning, witnesses


def _conflict_witness_candidates(witnesses: dict, relation: str, key: list[str]) -> set[str]:
    """Read competing candidate identifiers from one canonical place: positive `premises` reachable from
    the `invalid multiple_values` Witness for `(relation, key)` (contracts/proof.yaml)."""
    by_conclusion: dict[tuple[str, str], list[dict]] = {}
    for witness in witnesses.get("witnesses", ()):
        conclusion = witness.get("conclusion") or {}
        by_conclusion.setdefault((conclusion.get("relation", ""), conclusion.get("key", "")), []).append(witness)

    root = (relation, json.dumps([*key, "invalid", "multiple_values", ""], separators=(",", ":")))
    seen: set[tuple[str, str]] = set()
    queue = [root]
    found: set[str] = set()
    while queue:
        node = queue.pop()
        if node in seen:
            continue
        seen.add(node)
        for witness in by_conclusion.get(node, ()):
            for premise in witness.get("premises", ()):
                if premise.get("polarity") != "positive":
                    continue
                row = premise["row"]
                found.update(str(cell) for cell in json.loads(row["key"]))
                ref = (row["relation"], row["key"])
                if ref in by_conclusion and ref not in seen:
                    queue.append(ref)
    return found


def test_legacy_example_and_std_archive_integrity():
    """Verify the shared legacy archive is well-formed and holds every expected standard/example pack.

    Live byte-for-byte drift checks (`_LEGACY.assert_legacy_packs_match_archive`) run during explicit
    planner archive refreshes rather than PR CI, because `legacy-packs.tar.gz` is protected by
    `scripts/red_guard.py` while worker PRs legitimately update unconverted legacy packs.
    """
    expected_packs = {
        *(f"packs/{name}" for name in RULED_STD_PACKS),
        "packs/std-explain",
        "packs/std-view",
        "examples/subsidy",
        "examples/subsidy-scheme",
        "examples/library",
        "examples/projects",
        "examples/platform",
        "examples/platform/tenant-capacity/interface",
    }
    expected_dl_packs = {
        *(f"packs/{name}" for name in RULED_STD_PACKS if name != "std-access"),
        "examples/subsidy",
        "examples/subsidy-scheme",
        "examples/platform",
        "examples/platform/tenant-capacity/interface",
    }
    _LEGACY.assert_legacy_archive_integrity(
        expected_packs,
        expected_dl_packs=expected_dl_packs,
        expected_files={
            "packs/std-access": {"rezono/access.rezono"},
            "examples/library": {"facts/valid.yaml", "facts/errors.yaml"},
            "examples/projects": {"facts/valid.yaml", "facts/errors.yaml"},
        },
    )


def _assert_std_pack_converts(std_name: str, tmp_path: Path) -> None:
    """The conversion of one standard pack, as the former whole-group test checked it for every pack.

    `packs/<std_name>` has zero `.dl` files and zero `rezono 0` rule pipes, declares native `rezono 1` modules that
    compile with derivations, carries no legacy relational rule in `scripts/language_usage.py`, and publishes the
    same meaning as its frozen legacy snapshot through `compare_publications`: `std-access` through
    `examples/subsidy` for every role, every other pack through a consumer pack on its synthetic exercise facts,
    which must derive rows on the legacy snapshot so that the comparison is not vacuous.
    """
    pack_dir = REPO / "packs" / std_name
    assert (pack_dir / "pack.yaml").is_file(), f"missing expected standard pack packs/{std_name}"
    dl_files = _LEGACY.dl_files_under(pack_dir)
    assert not dl_files, f"packs/{std_name} still contains .dl files: {dl_files}"
    _LEGACY.assert_pack_is_native_rezono_1(pack_dir, expect_rules=True)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from scripts import language_usage

    usage = language_usage.inventory(REPO).get(pack_dir.resolve(), language_usage.PackUsage({}, (), False))
    assert "relational-rule" not in {form for forms in usage.files.values() for form in forms}, (
        f"language_usage.py still reports legacy relational-rule in packs/{std_name}"
    )

    # The legacy snapshot of every standard pack beside the live standard packs, which hold this pack converted.
    legacy_root = tmp_path / "legacy-root"
    _LEGACY.materialize_legacy_packs(legacy_root, ("packs",))
    native_root = tmp_path / "native-root"
    shutil.copytree(REPO / "packs", native_root / "packs")
    if std_name == "std-access":
        _compare_std_access_through_subsidy(legacy_root, native_root)
    else:
        _compare_std_pack_on_exercise(std_name, legacy_root, native_root, tmp_path)


def _compare_std_access_through_subsidy(legacy_root: Path, native_root: Path) -> None:
    """Compare whole-pack publications of `examples/subsidy` (over `examples/subsidy-scheme`) on the legacy and on the
    live `packs/std-access` across every role."""
    from rezono_compiler import modules, pack
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    def _subsidy_over_std_access(root: Path, *, legacy: bool):
        for example in ("examples/subsidy", "examples/subsidy-scheme"):
            dst = root / example
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(REPO / example, dst)
        scheme = root / "examples" / "subsidy-scheme"
        scheme_meta = yaml.safe_load((scheme / "pack.yaml").read_bytes())
        for entry in scheme_meta.get("imports", ()):
            if entry["name"].startswith("std-"):
                entry["sha256"] = modules.pack_hash(root / "packs" / entry["name"])
        (scheme / "pack.yaml").write_text(
            yaml.safe_dump(scheme_meta, sort_keys=False), encoding="utf-8", newline="\n"
        )
        consumer = root / "examples" / "subsidy"
        meta = yaml.safe_load((consumer / "pack.yaml").read_bytes())
        for entry in meta.get("imports", ()):
            if entry["name"].startswith("std-"):
                entry["sha256"] = modules.pack_hash(root / "packs" / entry["name"])
            elif entry["name"] == "subsidy-scheme":
                entry["sha256"] = modules.pack_hash(scheme)
        (consumer / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
        with ExitStack() as stack:
            if legacy:
                _LEGACY.admit_legacy_std_packs(stack, root)
            model = pack.read(consumer)
            roles = _LEGACY.roles_for_pack(consumer, model)
            epoch = publisher_batch.epoch(consumer, epoch=1, knowledge_time=TIME, sources=[("rules", "std-access")])
        return epoch, roles

    legacy_access_epoch, access_roles = _subsidy_over_std_access(legacy_root, legacy=True)
    native_access_epoch, _ = _subsidy_over_std_access(native_root, legacy=False)
    convert_pack.compare_publications(legacy_access_epoch, native_access_epoch, access_roles)


def _compare_std_pack_on_exercise(std_name: str, legacy_root: Path, native_root: Path, tmp_path: Path) -> None:
    """Compare every derived relation and checked ground of one standard pack through a consumer pack that carries
    its synthetic exercise facts, after showing that those facts derive rows on the legacy snapshot."""
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    spec = STD_PACK_EXERCISES[std_name]
    legacy_consumer = _build_consumer_for_std_pack(legacy_root, std_name, spec, "legacy")
    native_consumer = _build_consumer_for_std_pack(native_root, std_name, spec, "native")
    with ExitStack() as stack:
        _LEGACY.admit_legacy_std_packs(stack, legacy_root)
        legacy_epoch = publisher_batch.epoch(
            legacy_consumer, epoch=1, knowledge_time=TIME, sources=[("rules", f"legacy-{std_name}")]
        )
        legacy_meaning = convert_pack.read_publication(
            legacy_epoch, tmp_path / f"check-nonempty-{std_name}", {"checker": "complete"}
        )
    native_epoch = publisher_batch.epoch(
        native_consumer, epoch=1, knowledge_time=TIME, sources=[("rules", f"native-{std_name}")]
    )
    non_empty_derived = [
        rel for rel, rows in legacy_meaning.rows.items()
        if rows and rel not in spec["rows"] and "__" not in rel
    ]
    assert non_empty_derived, f"exercise facts for packs/{std_name} derived zero rows (vacuous comparison)"
    convert_pack.compare_publications(legacy_epoch, native_epoch, {"checker": "complete"})


def test_every_standard_pack_has_its_own_conversion_case():
    """Every `packs/std-*` pack is covered as the former whole-group test covered it: a pack with rules is one of
    RULED_STD_PACKS and has its own strict red case below, and a pack without rules (`std-explain`, `std-view`)
    holds no `.dl` file and, if it carries modules or schemas, native `rezono 1` modules without rules."""
    std_packs = sorted(p.parent for p in (REPO / "packs").glob("std-*/pack.yaml"))
    assert std_packs, "expected standard packs under packs/std-*"
    names = {pack_dir.name for pack_dir in std_packs}
    assert set(RULED_STD_PACKS) <= names, f"missing standard packs: {sorted(set(RULED_STD_PACKS) - names)}"
    assert set(STD_PACK_EXERCISES) == set(RULED_STD_PACKS) - {"std-access"}, sorted(STD_PACK_EXERCISES)
    for name in RULED_STD_PACKS:
        case = globals().get(f"test_{name.replace('-', '_')}_converts_to_rezono_1")
        assert callable(case), f"packs/{name} has no conversion case of its own"
    for pack_dir in std_packs:
        if pack_dir.name in RULED_STD_PACKS:
            continue
        assert not _LEGACY.dl_files_under(pack_dir), f"packs/{pack_dir.name} carries rules: add it to RULED_STD_PACKS"
        assert not (pack_dir / "rules").exists(), f"packs/{pack_dir.name} carries rules: add it to RULED_STD_PACKS"
        meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
        if meta.get("rezono") or (pack_dir / "schema").is_dir():
            _LEGACY.assert_pack_is_native_rezono_1(pack_dir, expect_rules=False)


# One strict red case per standard pack, so that each converts on its own task branch. A pack waits for the cases
# of the standard packs it imports (leaves first), for the compiler red tests of the rezono 1 lowering it needs, and,
# like the former whole-group test, for the live comparison of rule witnesses on Feldera. Converting a pack also
# regenerates its line of TABLE in compiler/rezono_compiler/standard_packs.py and re-pins its importers'
# `imports[].sha256` (decisions/language-rezono-1.md section 5.5, cross-pack consumers).


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-access (the rezono 0 rules pipe block of "
        "rezono/access.rezono) to a native rezono 1 module: no rules pipe block and no rezono 0 rule left "
        "in packs/std-access, and whole-pack equivalence via compare_publications of examples/subsidy (over "
        "examples/subsidy-scheme) on its legacy std-access snapshot against the converted one, for every "
        "role. Change only packs/std-access, its line of TABLE in "
        "compiler/rezono_compiler/standard_packs.py and the imports[].sha256 pins of its importers "
        "(packs/std-review, examples/subsidy, examples/platform, build, run/packs/probe-profiles; "
        "tests/fixtures/neutral and tests/fixtures/slip with the planner label per "
        "decisions/fixture-pin-update.md). Waits for "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, and "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_extend_option_lowers_as_the_datalog_extension_point."
    ),
)
def test_std_access_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-access", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-budget (rules/budget.dl) to native rezono 1 "
        "modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-budget, and whole-pack "
        "equivalence with its legacy snapshot via compare_publications on its synthetic exercise facts "
        "(kind: synthetic, STD_PACK_EXERCISES in this file), which derive rows on the legacy snapshot. "
        "Change only packs/std-budget, its line of TABLE in compiler/rezono_compiler/standard_packs.py and "
        "the imports[].sha256 pins of its importers (none today). Waits for "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, and "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_any_lowers_as_an_existential_join."
    ),
)
def test_std_budget_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-budget", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-decision (rules/decision.dl) to native "
        "rezono 1 modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-decision, and "
        "whole-pack equivalence with its legacy snapshot via compare_publications on its synthetic exercise "
        "facts (kind: synthetic, ISO dates only, STD_PACK_EXERCISES in this file). Change only "
        "packs/std-decision, its line of TABLE in compiler/rezono_compiler/standard_packs.py and the "
        "imports[].sha256 pins of its importers (examples/subsidy, examples/subsidy-scheme, "
        "examples/platform, build, run/packs/invoice-drift, run/packs/offer-selection, "
        "run/packs/probe-profiles). Waits for "
        "compiler/tests/test_std_decision_dates.py--test_std_decision_rules_read_dates (the legacy snapshot "
        "reads the exercise dates only after it and the archive refresh that follows), "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "--test_rezono_1_absence_and_outcome_options_lower_as_the_datalog_annotations, "
        "--test_rezono_1_any_lowers_as_an_existential_join, and "
        "--test_rezono_1_membership_in_a_multivalued_slot_lowers."
    ),
)
def test_std_decision_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-decision", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-identity (rules/identity.dl) to native "
        "rezono 1 modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-identity, and "
        "whole-pack equivalence with its legacy snapshot via compare_publications on its synthetic exercise "
        "facts (kind: synthetic, STD_PACK_EXERCISES in this file), which derive rows on the legacy "
        "snapshot. Change only packs/std-identity, its line of TABLE in "
        "compiler/rezono_compiler/standard_packs.py and the imports[].sha256 pins of its importers "
        "(examples/platform). Waits for "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "--test_rezono_1_explain_option_lowers_as_the_datalog_explain, "
        "--test_rezono_1_extend_option_lowers_as_the_datalog_extension_point, "
        "--test_rezono_1_any_lowers_as_an_existential_join, and "
        "--test_rezono_1_membership_in_a_multivalued_slot_lowers."
    ),
)
def test_std_identity_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-identity", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-loop (its 24 rules/*.dl files) to native "
        "rezono 1 modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-loop, and "
        "whole-pack equivalence with its legacy snapshot via compare_publications on its synthetic exercise "
        "facts (kind: synthetic, STD_PACK_EXERCISES in this file), which derive rows on the legacy "
        "snapshot. Change only packs/std-loop, its line of TABLE in "
        "compiler/rezono_compiler/standard_packs.py and the imports[].sha256 pins of its importers "
        "(examples/platform, build, epoch, run/packs/cleanup-deadline). Waits for "
        "examples/test_rezono_1_pack_conversion.py--test_std_order_converts_to_rezono_1 (it imports "
        "std-order), "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_a_rezono_1_derivation_reads_a_relation_of_an_imported_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "--test_rezono_1_extend_option_lowers_as_the_datalog_extension_point, "
        "--test_rezono_1_any_lowers_as_an_existential_join, "
        "--test_rezono_1_arithmetic_in_a_bool_derivation_lowers, and "
        "--test_rezono_1_count_in_a_bool_derivation_lowers."
    ),
)
def test_std_loop_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-loop", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-order (rules/order.dl) to native rezono 1 "
        "modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-order, and whole-pack "
        "equivalence with its legacy snapshot via compare_publications on its synthetic exercise facts "
        "(kind: synthetic, STD_PACK_EXERCISES in this file), which derive rows on the legacy snapshot. "
        "Change only packs/std-order, its line of TABLE in compiler/rezono_compiler/standard_packs.py and "
        "the imports[].sha256 pins of its importers (packs/std-loop, examples/platform). Waits for "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "--test_rezono_1_explain_option_lowers_as_the_datalog_explain, "
        "--test_rezono_1_extend_option_lowers_as_the_datalog_extension_point, "
        "--test_rezono_1_any_lowers_as_an_existential_join, and "
        "--test_rezono_1_membership_in_a_multivalued_slot_lowers."
    ),
)
def test_std_order_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-order", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-part (rules/part.dl) to native rezono 1 "
        "modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-part, and whole-pack "
        "equivalence with its legacy snapshot via compare_publications on its synthetic exercise facts "
        "(kind: synthetic, STD_PACK_EXERCISES in this file), which derive rows on the legacy snapshot. "
        "Change only packs/std-part, its line of TABLE in compiler/rezono_compiler/standard_packs.py and "
        "the imports[].sha256 pins of its importers (examples/platform, run/packs/probe-profiles). Waits "
        "for "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "and --test_rezono_1_any_lowers_as_an_existential_join."
    ),
)
def test_std_part_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-part", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-review (its 7 rules/*.dl files) to native "
        "rezono 1 modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-review, and "
        "whole-pack equivalence with its legacy snapshot via compare_publications on its synthetic exercise "
        "facts (kind: synthetic, ISO dates only, STD_PACK_EXERCISES in this file). Change only "
        "packs/std-review, its line of TABLE in compiler/rezono_compiler/standard_packs.py and the "
        "imports[].sha256 pins of its importers (none today). Waits for "
        "examples/test_rezono_1_pack_conversion.py--test_std_access_converts_to_rezono_1 (it imports "
        "std-access), "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_a_rezono_1_derivation_reads_a_relation_of_an_imported_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "--test_rezono_1_any_lowers_as_an_existential_join, and the packs/std-review native date migration "
        "of decisions/standard-packs-everywhere.md section 1.4 step 5 (Review.date and RoleGrant.valid_from "
        "in place of day numbers; the legacy snapshot reads the exercise dates only after it and the "
        "archive refresh that follows; no red test names it yet)."
    ),
)
def test_std_review_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-review", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert packs/std-time (rules/time.dl) to native rezono 1 "
        "modules: zero .dl files and zero rezono 0 rules pipe blocks in packs/std-time, and whole-pack "
        "equivalence with its legacy snapshot via compare_publications on its synthetic exercise facts "
        "(kind: synthetic, STD_PACK_EXERCISES in this file), which derive rows on the legacy snapshot. "
        "Change only packs/std-time, its line of TABLE in compiler/rezono_compiler/standard_packs.py and "
        "the imports[].sha256 pins of its importers (examples/subsidy, examples/platform, "
        "run/packs/invoice-drift). Waits for "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_an_importer_compiles_the_derivations_of_an_imported_rezono_1_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "--test_rezono_1_explain_option_lowers_as_the_datalog_explain, "
        "--test_rezono_1_absence_and_outcome_options_lower_as_the_datalog_annotations, "
        "--test_rezono_1_any_lowers_as_an_existential_join, "
        "--test_rezono_1_arithmetic_in_a_bool_derivation_lowers, and "
        "--test_rezono_1_membership_in_a_multivalued_slot_lowers."
    ),
)
def test_std_time_converts_to_rezono_1(tmp_path: Path):
    _assert_std_pack_converts("std-time", tmp_path)


def _assert_reader_example_converts(rel_path: str, tmp_path: Path) -> None:
    """`examples/library` or `examples/projects`: native `rezono 1` modules without rules, compare_publications on the
    valid dataset against the legacy snapshot (whose facts travel in the archive), and the expected violations of
    both datasets."""
    pack_dir = REPO / rel_path
    model, files, _, _ = _LEGACY.assert_pack_is_native_rezono_1(pack_dir, expect_rules=False)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_compiler import facts as fact_files
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack
    from support import expected, violations  # compiler/tests/support.py, as in examples/test_examples.py

    legacy_root = tmp_path / "legacy"
    _LEGACY.materialize_legacy_packs(legacy_root, (rel_path,))
    legacy_pack = legacy_root / rel_path
    epochs = {}
    for label, src_dir in (("legacy", legacy_pack), ("native", pack_dir)):
        valid_copy = tmp_path / f"{pack_dir.name}-{label}-valid"
        shutil.copytree(src_dir, valid_copy)
        for err_file in (
            list(valid_copy.rglob("errors.yaml"))
            + list(valid_copy.rglob("errors.rezono"))
            + list(valid_copy.rglob("errors.json"))
        ):
            err_file.unlink()
        meta_path = valid_copy / "pack.yaml"
        meta = yaml.safe_load(meta_path.read_bytes())
        if meta.get("rezono"):
            meta["rezono"] = [e for e in meta["rezono"] if Path(e["module"]).stem != "errors"]
            meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
        epochs[label] = publisher_batch.epoch(
            valid_copy, epoch=1, knowledge_time=TIME, sources=[("rules", f"{label}-{pack_dir.name}")]
        )
    convert_pack.compare_publications(epochs["legacy"], epochs["native"], {"reader": "complete"})

    datasets = fact_files.files(pack_dir)
    assert {path.stem for path in datasets} == {"valid", "errors"}, (rel_path, datasets)
    for path in datasets:
        rows = fact_files.load(model, path)
        want = expected(pack_dir / "expected" / "violations" / f"{path.stem}.json")
        assert violations(files, rows) == want, (rel_path, path.stem)


def _assert_subsidy_matches_legacy(tmp_path: Path) -> None:
    """Publish the live `examples/subsidy` over the live `examples/subsidy-scheme` and compare it with the legacy
    snapshot of both: every legacy rule relation, checked ground and per-role snapshot unchanged, role scoping kept,
    the relations of the independent `reference.py` oracle under their exact names, and the exact `<k>_<d>`
    calculation derivations (`application_<rule>`) that rezono 1 publishes beside them."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_compiler import pack
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    subsidy_dir = REPO / "examples" / "subsidy"
    legacy_root = tmp_path / "legacy"
    _LEGACY.materialize_legacy_packs(legacy_root, ("packs", "examples/subsidy", "examples/subsidy-scheme"))
    legacy_subsidy = legacy_root / "examples" / "subsidy"
    shutil.copytree(subsidy_dir / "facts", legacy_subsidy / "facts")

    with ExitStack() as stack:
        _LEGACY.admit_legacy_std_packs(stack, legacy_root)
        roles = _LEGACY.roles_for_pack(legacy_subsidy, pack.read(legacy_subsidy))
        assert {"checker", "case_officer", "policy_adviser", "propose", "public", "viewer"} <= set(roles), roles
        legacy_sub_epoch = publisher_batch.epoch(
            legacy_subsidy, epoch=1, knowledge_time=TIME, sources=[("rules", "legacy-subsidy")]
        )
        legacy_sub = convert_pack.read_publication(legacy_sub_epoch, tmp_path / "legacy-sub-store", roles)

    _, _, native_sub, _ = _publish_with_witnesses(subsidy_dir, tmp_path / "native-sub-store", roles)

    # Every legacy base and derived rule relation must match 1-for-1 on rows and checked grounds.
    for rel_name, legacy_rows in legacy_sub.rows.items():
        assert rel_name in native_sub.rows, f"examples/subsidy rezono 1 dropped relation {rel_name!r}"
        assert native_sub.rows[rel_name] == legacy_rows, (
            f"examples/subsidy rezono 1 changed rows for relation {rel_name!r}"
        )
    for key, legacy_ground in legacy_sub.grounds.items():
        if key[0] in legacy_sub.rows:
            assert native_sub.grounds.get(key) == legacy_ground, (
                f"examples/subsidy rezono 1 changed checked grounds for {key}"
            )

    # Per-role views: every role sees the exact same legacy snapshots for all legacy relations,
    # and role scoping holds (articles visible to all; applications visible to case_officer/propose, hidden from public).
    for role in ("case_officer", "policy_adviser", "propose", "public", "viewer"):
        legacy_snaps = legacy_sub.visible[role][0]
        native_snaps = native_sub.visible[role][0]
        for snap_name, legacy_bytes in legacy_snaps.items():
            assert native_snaps.get(snap_name) == legacy_bytes, (
                f"examples/subsidy role {role} snapshot {snap_name} diverged from legacy"
            )
        assert json.loads(native_snaps["relations/article.json"]), f"{role} must see scheme articles"
    for role in ("case_officer", "propose"):
        assert json.loads(native_sub.visible[role][0]["relations/application.json"]), f"{role} must see applications"
    assert json.loads(native_sub.visible["public"][0]["relations/application.json"]) == []

    # Independent reference.py oracle: pinned exact relation names (zero old-or-new fallback!).
    ref = _load_python_module(subsidy_dir / "reference.py", "subsidy_reference_oracle")
    # The facts state, read before the generator advances: the reference applies each scenario to the same state
    # in place, so the facts state is the first one yielded, as in examples/test_rules.py.
    label, base_state = next(ref.states())
    assert label == "0-applications", label
    for rel_name, want_rows in ref.rules(base_state).items():
        got_rows = sorted([str(cell) for cell in row] for row in native_sub.rows[rel_name])
        assert got_rows == want_rows, f"examples/subsidy relation {rel_name!r} diverged from reference.py"

    expected_calc = ref.calc(base_state)
    for rule_name in SUBSIDY_CALC_RELATIONS:
        rel_id = f"application_{rule_name}"
        assert rel_id in native_sub.rows, (
            f"examples/subsidy must publish rezono 1 functional property {rel_id!r} (decisions/language-rezono-1.md §2)"
        )
        observed = {
            str(row[0]): (str(row[3]) if str(row[1]) == "known" else str(row[1]))
            for row in native_sub.rows[rel_id]
        }
        assert observed == expected_calc[rule_name], f"examples/subsidy {rel_id!r} diverged from reference.py"


# One strict red case per front-door example (decisions/release-1-scope.md section 7), with examples/subsidy-scheme
# and examples/subsidy in one case: examples/library and examples/projects import nothing and carry no rules;
# examples/subsidy imports examples/subsidy-scheme, std-access, std-decision and std-time, and its calculation reads
# the scheme's award.


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert examples/library (its LinkML schema) to native rezono 1 "
        "modules: zero .dl files, its kinds declared under rezono: in pack.yaml with rezono.module/5 forms that "
        "compile with language_version 1, whole-pack equivalence of its valid dataset with the legacy snapshot via "
        "compare_publications, and the violations in expected/violations for both datasets. "
        "Change only examples/library, and scripts/convert_pack.py (the shared conversion helper) if it is to "
        "convert the schema: it refuses it today with \"Address: cannot introduce an implicit identifier\"."
    ),
)
def test_examples_library_converts_to_rezono_1(tmp_path: Path):
    _assert_reader_example_converts("examples/library", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert examples/projects (its LinkML schema) to native rezono 1 "
        "modules: zero .dl files, its kinds declared under rezono: in pack.yaml with rezono.module/5 forms that "
        "compile with language_version 1, whole-pack equivalence of its valid dataset with the legacy snapshot via "
        "compare_publications, and the violations in expected/violations for both datasets. "
        "Change only examples/projects."
    ),
)
def test_examples_projects_converts_to_rezono_1(tmp_path: Path):
    _assert_reader_example_converts("examples/projects", tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert examples/subsidy-scheme (its four rules/*.dl files and "
        "rezono/award.rezono) and examples/subsidy (its four rules/*.dl files and calc/*.yaml) together to "
        "native rezono 1 modules with derivations and zero .dl files: the published examples/subsidy keeps "
        "every legacy relation, checked ground and per-role snapshot of the legacy snapshot of both, role "
        "scoping, the relations of examples/subsidy/reference.py under their exact names, and gains the "
        "exact functional properties application_<rule> of section 2 for the scheme's six calculations and "
        "payment_difference. One case for both: examples/subsidy/calc/drift.yaml reads the scheme's award, "
        "and section 5.6 lowers award to rezono.rules/2, so converting the scheme alone would leave a "
        "rezono.calc/1 reading a rezono.rules/2 value, a state the decision does not ask for. Change only "
        "examples/subsidy and examples/subsidy-scheme. Waits for "
        "examples/test_rezono_1_pack_conversion.py--test_std_access_converts_to_rezono_1, "
        "--test_std_decision_converts_to_rezono_1, --test_std_time_converts_to_rezono_1 (their imports), "
        "compiler/tests/rezono/test_lower_rezono_1_imported_derived.py--test_a_rezono_1_derivation_reads_a_relation_of_an_imported_pack, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "compiler/tests/rezono/test_lower_rezono_1_rule_constructs.py--test_rezono_1_invariant_option_lowers_as_the_datalog_invariant, "
        "--test_rezono_1_absence_and_outcome_options_lower_as_the_datalog_annotations, "
        "--test_rezono_1_any_lowers_as_an_existential_join, "
        "--test_rezono_1_count_in_a_bool_derivation_lowers, and a planner red test for lowering a versioned "
        "calculation (version, definition, unit, output) to rezono.rules/2 as section 5.6 requires (none "
        "yet: it first restates "
        "compiler/tests/rezono/test_rezono_module_5_calc_facts_sources.py::test_rezono_module_5_calculation_lowers_to_calc_ir, "
        "a green test that pins today's routing of such a calculation to rezono.calc/1)."
    ),
)
def test_examples_subsidy_and_subsidy_scheme_convert_to_rezono_1(tmp_path: Path):
    scheme_dir = REPO / "examples" / "subsidy-scheme"
    assert not _LEGACY.dl_files_under(scheme_dir), (
        f"examples/subsidy-scheme still contains .dl files: {_LEGACY.dl_files_under(scheme_dir)}"
    )
    _LEGACY.assert_pack_is_native_rezono_1(scheme_dir, expect_rules=True)
    _LEGACY.assert_pack_is_native_rezono_1(REPO / "examples" / "subsidy", expect_rules=True)
    _assert_subsidy_matches_legacy(tmp_path)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/language-rezono-1.md: Convert examples/platform/rules/*.dl (including its safe steps "
        "and examples/platform/tenant-capacity/interface) to native rezono 1 modules with whole-pack equivalence "
        "across ALL platform relations against its legacy snapshot plus explicit verification of every section 7 "
        "intended semantic difference (invalid multiple_values with full candidate witnesses, unknown no_match, "
        "not_applicable no_match, and unknown no_value; retiring product_newest_day, flow_from_step, and "
        "needs_service per decisions/platform-facts-not-conclusions.md §§4-5). "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "examples/test_rezono_1_pack_conversion.py--test_std_access_converts_to_rezono_1, "
        "--test_std_decision_converts_to_rezono_1, --test_std_identity_converts_to_rezono_1, "
        "--test_std_loop_converts_to_rezono_1, --test_std_order_converts_to_rezono_1, "
        "--test_std_part_converts_to_rezono_1, --test_std_time_converts_to_rezono_1, "
        "examples/platform/test_platform_release_dates.py--test_runs_orders_releases_by_their_sourced_date, "
        "and examples/platform/test_platform_start_order.py--test_start_order_follows_from_needs_through_std_order."
    ),
)
def test_platform_pack_converts_to_rezono_1_with_intended_differences(tmp_path: Path):
    platform_dir = REPO / "examples" / "platform"
    iface_dir = platform_dir / "tenant-capacity" / "interface"

    dl_files = _LEGACY.dl_files_under(platform_dir)
    assert not dl_files, f"examples/platform still contains .dl files: {dl_files}"

    _LEGACY.assert_pack_is_native_rezono_1(iface_dir, expect_rules=True)
    platform_model, _, _, platform_ir = _LEGACY.assert_pack_is_native_rezono_1(platform_dir, expect_rules=True)

    by_name = {r["name"]: r for r in platform_ir.get("relations", []) if r.get("role") != "base"}

    # Safe-step / round relations remain compiled under rezono 1.
    assert PLATFORM_STEP_RELATIONS <= set(by_name), sorted(PLATFORM_STEP_RELATIONS - set(by_name))

    # Pinned section 7 + platform-facts-not-conclusions contract: retired/legacy names absent,
    # every functional & Bool relation asserted unconditionally.
    leftover_retired = sorted((PLATFORM_RETIRED_RELATIONS | PLATFORM_LEGACY_RENAMED_RELATIONS) & set(by_name))
    assert not leftover_retired, f"retired or renamed legacy core.dl relations still present: {leftover_retired}"

    for rel_name in sorted(PLATFORM_CORE_FUNCTIONAL):
        assert rel_name in by_name, f"missing rezono 1 functional derivation {rel_name!r}"
        assert by_name[rel_name].get("role") == "functional", (rel_name, by_name[rel_name])

    for rel_name in sorted(PLATFORM_RENAMED_BOOL | PLATFORM_UNCHANGED_BOOL):
        assert rel_name in by_name, f"missing rezono 1 Bool derivation {rel_name!r}"
        assert by_name[rel_name].get("role") == "derived", (rel_name, by_name[rel_name])
    assert len(by_name["service_behind_newest"].get("key", [])) == 1, (
        "service_behind_newest must have arity-1 key (s: Service) per section 7"
    )

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_compiler import batch as compiler_batch
    from rezono_compiler import facts as fact_files
    from rezono_compiler import rules as rules_ir
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    # Materialize legacy examples/platform (+ tenant-capacity/interface + legacy std-*) with the live facts.
    legacy_root = tmp_path / "legacy"
    _LEGACY.materialize_legacy_packs(legacy_root, ("packs", "examples/platform"))
    legacy_platform = legacy_root / "examples" / "platform"
    shutil.copytree(platform_dir / "facts", legacy_platform / "facts")
    shutil.copytree(iface_dir / "facts", legacy_platform / "tenant-capacity" / "interface" / "facts")

    roles = _LEGACY.roles_for_pack(platform_dir, platform_model)
    assert "checker" in roles and len(roles) > 1, roles

    with ExitStack() as stack:
        _LEGACY.admit_legacy_std_packs(stack, legacy_root)
        legacy_epoch = publisher_batch.epoch(
            legacy_platform, epoch=1, knowledge_time=TIME, sources=[("rules", "legacy-platform")]
        )
        legacy_pub = convert_pack.read_publication(legacy_epoch, tmp_path / "legacy-platform-store", roles)

    _, _, native_pub, _ = _publish_with_witnesses(platform_dir, tmp_path / "native-platform-store", roles)

    # Whole-pack equivalence across EVERY relation outside section 7 (rows, checked grounds, and per-role views).
    non_s7_legacy = set(legacy_pub.rows) - PLATFORM_SECTION_7_LEGACY
    non_s7_native = set(native_pub.rows) - PLATFORM_SECTION_7_NATIVE
    assert non_s7_native == non_s7_legacy, (
        f"unlisted relation set difference outside section 7: "
        f"missing={sorted(non_s7_legacy - non_s7_native)}, extra={sorted(non_s7_native - non_s7_legacy)}"
    )
    for rel_name in sorted(non_s7_legacy):
        assert native_pub.rows[rel_name] == legacy_pub.rows[rel_name], (
            f"examples/platform relation {rel_name!r} diverged from legacy snapshot (not listed in section 7)"
        )
    for key, legacy_ground in legacy_pub.grounds.items():
        if key[0] in non_s7_legacy:
            assert native_pub.grounds.get(key) == legacy_ground, (
                f"examples/platform checked grounds for {key} diverged from legacy snapshot"
            )
    for role in roles:
        if roles[role] != "may_read":
            continue
        legacy_snaps = legacy_pub.visible[role][0]
        native_snaps = native_pub.visible[role][0]
        for rel_name in sorted(non_s7_legacy):
            snap_key = f"relations/{rel_name}.json"
            if snap_key in legacy_snaps:
                assert native_snaps.get(snap_key) == legacy_snaps[snap_key], (
                    f"examples/platform role {role} snapshot {snap_key} diverged from legacy snapshot"
                )

    # Exact section 7 tuple mapping against the legacy publication on base facts.
    def _known_pairs(rel_name: str):
        return {(row[0], row[3]) for row in native_pub.rows[rel_name] if row[1] == "known"}

    assert _known_pairs("service_zone") == set(legacy_pub.rows["zone_of"])
    assert _known_pairs("service_cluster") == set(legacy_pub.rows["on_cluster"])
    assert {(row[0],) for row in native_pub.rows["service_pin"] if row[1] == "known"} == set(legacy_pub.rows["pinned"])
    assert _known_pairs("service_runs") == set(legacy_pub.rows["runs"])
    assert {(row[0], row[1]) for row in native_pub.rows["chosen"] if row[2] == "known"} == set(
        legacy_pub.rows["provider_chosen"]
    )
    assert {(row[0], row[4], row[1]) for row in native_pub.rows["needs"] if row[2] == "known"} == set(
        legacy_pub.rows["needs"]
    )
    assert {(row[0], row[1]) for row in native_pub.rows["needs"] if row[2] == "invalid"} == set(
        legacy_pub.rows["ambiguous_provider"]
    )
    assert {(row[0], row[1]) for row in native_pub.rows["needs"] if row[2] == "unknown"} == set(
        legacy_pub.rows["unmet_need"]
    )
    assert set(native_pub.rows["service_behind_newest"]) == {(row[0],) for row in legacy_pub.rows["behind_newest"]}
    assert set(native_pub.rows["service_authenticates"]) == set(legacy_pub.rows["authenticates"])
    assert set(native_pub.rows["service_verified"]) == set(legacy_pub.rows["verified"])
    assert set(native_pub.rows["service_unverified_supply"]) == set(legacy_pub.rows["unverified_supply"])

    # oracle-rows.json updated in lockstep with rezono 1 bundle names (section 5.5 + platform-facts-not-conclusions).
    oracle_rows = json.loads((platform_dir / "oracle-rows.json").read_text(encoding="utf-8"))
    for retired in (
        "ambiguous_provider",
        "unmet_need",
        "zone_of",
        "on_cluster",
        "runs",
        "newest_day",
        "product_newest_day",
        "flow_from_step",
        "needs_service",
        "behind_newest",
        "unverified_supply",
    ):
        assert retired not in oracle_rows, (
            f"examples/platform/oracle-rows.json must migrate off legacy key {retired!r} in lockstep (section 5.5)"
        )
    for rel_name, want in oracle_rows.items():
        got = sorted([str(cell) for cell in row] for row in native_pub.rows[rel_name])
        want_str = sorted([str(cell) for cell in row] for row in want)
        assert got == want_str, f"examples/platform published relation {rel_name!r} diverged from oracle-rows.json"

    # --- Explicit section 7 behavioral scenarios ---
    core_facts = yaml.safe_load((platform_dir / "facts" / "core.yaml").read_text(encoding="utf-8"))

    # Scenario 1: Conflicting Choice rows pointing at TWO REAL PROVIDERS of one function.
    # First prove the legacy pack emits BOTH flows; then prove rezono 1 emits invalid multiple_values
    # with both providers named in the conflict witness, and emits ZERO flows for (consumer, *, fn, *).
    providers_by_fn: dict[str, list[tuple[str, str]]] = {}
    for svc_id, fn_id, port in sorted(legacy_pub.rows["provides"]):
        providers_by_fn.setdefault(str(fn_id), []).append((str(svc_id), str(port)))
    multi_provider_choices = [
        (svc["id"], dem["function"], providers_by_fn[dem["function"]][0], providers_by_fn[dem["function"]][1])
        for dem in core_facts["demand"]
        if len(providers_by_fn.get(dem["function"], ())) >= 2
        for svc in core_facts["service"]
        if svc["product"] == dem["product"]
    ]
    assert multi_provider_choices, "examples/platform must have a demand whose function has >= 2 real providers"
    consumer_svc, multi_fn, (prov_a, port_a), (prov_b, port_b) = multi_provider_choices[0]
    assert prov_a != prov_b

    def _mutate_conflicting_choice(pack_copy: Path) -> None:
        c_path = pack_copy / "facts" / "core.yaml"
        doc = yaml.safe_load(c_path.read_text(encoding="utf-8"))
        doc["choice"] = [
            row for row in doc.get("choice", [])
            if not (row.get("service") == consumer_svc and row.get("function") == multi_fn)
        ] + [
            {"id": "conflict-choice-a", "service": consumer_svc, "function": multi_fn, "provider": prov_a},
            {"id": "conflict-choice-b", "service": consumer_svc, "function": multi_fn, "provider": prov_b},
        ]
        c_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8", newline="\n")

    legacy_choice_root = tmp_path / "legacy-choice-conflict"
    shutil.copytree(legacy_root, legacy_choice_root)
    legacy_choice_pack = legacy_choice_root / "examples" / "platform"
    _mutate_conflicting_choice(legacy_choice_pack)
    with ExitStack() as stack:
        _LEGACY.admit_legacy_std_packs(stack, legacy_choice_root)
        legacy_choice_epoch = publisher_batch.epoch(
            legacy_choice_pack, epoch=1, knowledge_time=TIME, sources=[("rules", "legacy-choice")]
        )
        legacy_choice_pub = convert_pack.read_publication(
            legacy_choice_epoch, tmp_path / "legacy-choice-store", {"checker": "complete"}
        )
    legacy_flows = {(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in legacy_choice_pub.rows["flow"]}
    assert (consumer_svc, prov_a, multi_fn, port_a) in legacy_flows and (
        consumer_svc, prov_b, multi_fn, port_b
    ) in legacy_flows, "legacy core.dl must emit flows for both conflicting real providers"

    native_choice_root = tmp_path / "native-choice-conflict"
    shutil.copytree(REPO / "packs", native_choice_root / "packs")
    shutil.copytree(platform_dir, native_choice_root / "examples" / "platform")
    native_choice_pack = native_choice_root / "examples" / "platform"
    _mutate_conflicting_choice(native_choice_pack)
    _, _, choice_pub, choice_witnesses = _publish_with_witnesses(
        native_choice_pack, tmp_path / "native-choice-store", {"checker": "complete"}
    )
    chosen_state = {(r[0], r[1]): (r[2], r[3]) for r in choice_pub.rows["chosen"]}
    needs_state = {(r[0], r[1]): (r[2], r[3]) for r in choice_pub.rows["needs"]}
    assert chosen_state[(consumer_svc, multi_fn)] == ("invalid", "multiple_values"), chosen_state
    assert needs_state[(consumer_svc, multi_fn)] == ("invalid", "multiple_values"), needs_state
    assert not [r for r in choice_pub.rows["flow"] if r[0] == consumer_svc and r[2] == multi_fn], (
        "section 7: conflicting Choice rows must suppress flow for (a, *, f, *)"
    )
    for rel_name in ("chosen", "needs"):
        candidates = _conflict_witness_candidates(choice_witnesses, rel_name, [consumer_svc, multi_fn])
        assert {prov_a, prov_b} <= candidates, (
            f"conflict witness for {rel_name}({consumer_svc}, {multi_fn}) must name both candidates "
            f"{prov_a!r} and {prov_b!r}, got {sorted(candidates)}"
        )

    # Scenario 2: Conflicting Pin rows (same product per Pin.same_product) -> invalid multiple_values
    # with both competing releases named in the conflict witness, and service_behind_newest suppressed.
    releases_by_product: dict[str, list[str]] = {}
    for row in core_facts["release"]:
        releases_by_product.setdefault(row["product"], []).append(row["id"])
    pinned_candidates = [
        (row["id"], row["product"], releases_by_product[row["product"]][:2])
        for row in core_facts["service"]
        if len(releases_by_product.get(row["product"], ())) >= 2
    ]
    assert pinned_candidates, "examples/platform must have a service whose product has >= 2 releases"
    sample_service, sample_product, (rel_a, rel_b) = pinned_candidates[0]

    pin_root = tmp_path / "native-pin-conflict"
    shutil.copytree(REPO / "packs", pin_root / "packs")
    shutil.copytree(platform_dir, pin_root / "examples" / "platform")
    p_pack = pin_root / "examples" / "platform"
    p_core_path = p_pack / "facts" / "core.yaml"
    p_core = yaml.safe_load(p_core_path.read_text(encoding="utf-8"))
    p_core["pin"] = [
        row for row in p_core.get("pin", []) if row.get("service") != sample_service
    ] + [
        {"id": "conflict-pin-a", "service": sample_service, "release": rel_a},
        {"id": "conflict-pin-b", "service": sample_service, "release": rel_b},
    ]
    p_core_path.write_text(yaml.safe_dump(p_core, sort_keys=False), encoding="utf-8", newline="\n")
    _, _, pin_pub, pin_witnesses = _publish_with_witnesses(
        p_pack, tmp_path / "native-pin-store", {"checker": "complete"}
    )
    pin_state = {r[0]: (r[1], r[2]) for r in pin_pub.rows["service_pin"]}
    runs_state = {r[0]: (r[1], r[2]) for r in pin_pub.rows["service_runs"]}
    assert pin_state[sample_service] == ("invalid", "multiple_values"), pin_state
    assert runs_state[sample_service] == ("invalid", "multiple_values"), runs_state
    assert not [r for r in pin_pub.rows["service_behind_newest"] if r[0] == sample_service], (
        "section 7: conflicting Pin rows must suppress service_behind_newest for that service"
    )
    for rel_name in ("service_pin", "service_runs"):
        candidates = _conflict_witness_candidates(pin_witnesses, rel_name, [sample_service])
        assert {rel_a, rel_b} <= candidates, (
            f"conflict witness for {rel_name}({sample_service}) must name both releases "
            f"{rel_a!r} and {rel_b!r}, got {sorted(candidates)}"
        )

    # Scenario 3: `unknown no_match` (unprovided function demand + unpinned service with no stable release)
    # and `not_applicable no_match` (optional `chosen` with no choice row).
    empty_root = tmp_path / "native-no-match"
    shutil.copytree(REPO / "packs", empty_root / "packs")
    shutil.copytree(platform_dir, empty_root / "examples" / "platform")
    e_pack = empty_root / "examples" / "platform"
    e_core_path = e_pack / "facts" / "core.yaml"
    e_core = yaml.safe_load(e_core_path.read_text(encoding="utf-8"))
    e_core["function"].append({"id": "unprovided-fn", "recovery_allowed": "no", "open_by_design": "no"})
    e_core["demand"].append({"id": "d-unprovided", "product": sample_product, "function": "unprovided-fn"})
    # Drop stable releases for sample_product and ensure sample_service is unpinned.
    for rel_row in e_core["release"]:
        if rel_row.get("product") == sample_product:
            rel_row["stable"] = "no"
    e_core["pin"] = [row for row in e_core.get("pin", []) if row.get("service") != sample_service]
    e_core_path.write_text(yaml.safe_dump(e_core, sort_keys=False), encoding="utf-8", newline="\n")
    _, _, empty_pub, _ = _publish_with_witnesses(
        e_pack, tmp_path / "native-empty-store", {"checker": "complete"}
    )
    empty_needs = {(r[0], r[1]): (r[2], r[3]) for r in empty_pub.rows["needs"]}
    empty_chosen = {(r[0], r[1]): (r[2], r[3]) for r in empty_pub.rows["chosen"]}
    empty_runs = {r[0]: (r[1], r[2]) for r in empty_pub.rows["service_runs"]}
    assert empty_needs[(sample_service, "unprovided-fn")] == ("unknown", "no_match"), empty_needs
    assert empty_chosen[(sample_service, "unprovided-fn")] == ("not_applicable", "no_match"), empty_chosen
    assert empty_runs[sample_service] == ("unknown", "no_match"), empty_runs

    # Scenario 4: `unknown no_value` (Service.zone and Service.cluster when a service is missing its required `role` slot).
    # Evaluated directly through the compiled rule engine so integrity checks on the omitted required slot do not short-circuit.
    prog = rules_ir.load(platform_model.rules)
    base_rows: dict[str, list[tuple]] = {}
    for fact_path in fact_files.files(platform_dir):
        for table, table_rows in fact_files.load(platform_model, fact_path).items():
            base_rows.setdefault(table, []).extend(table_rows)
    base_rows["service__role"] = [row for row in base_rows.get("service__role", ()) if row[0] != sample_service]
    with compiler_batch.connect(prog, base_rows) as con:
        compiler_batch.compute(con, prog)
        derived = compiler_batch.read(con, prog)
    zone_state = {r[0]: (r[1], r[2]) for r in derived["service_zone"]}
    cluster_state = {r[0]: (r[1], r[2]) for r in derived["service_cluster"]}
    assert zone_state[sample_service] == ("unknown", "no_value"), zone_state
    assert cluster_state[sample_service] == ("unknown", "no_value"), cluster_state
