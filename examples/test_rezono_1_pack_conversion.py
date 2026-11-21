"""Per-group strict red tests for single-pass pack rule conversion to native `rezono 1` modules
for standard packs (`packs/std-*`), front-door examples (`examples/subsidy`, `examples/subsidy-scheme`,
`examples/library`, `examples/projects`), and `examples/platform`
(decisions/language-rezono-1.md, sections 1, 2, 5.5, 5.8, 5.10, 6, 7 and 8).

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
import tarfile

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
LEGACY_ARCHIVE = Path(__file__).resolve().parent / "fixtures" / "rezono-1-legacy" / "legacy-packs.tar.gz"
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

# Synthetic exercise facts (with `kind: synthetic` origins per decisions/fact-origin-required.md §3)
# used to compare every ruled standard pack non-vacuously via `scripts.convert_pack.compare_publications`.
# Theory packs with abstract kinds (`std-identity`, `std-order`, `std-part`, `std-time`) are exercised
# through a minimal consumer schema declaring a concrete child kind (`is_a: ...`).
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
                {"id": "d-1", "title": "Sample", "state": "in_force", "decider": "board", "valid_from": "2026-01-01"},
            ],
            "reference_date": [
                {"id": "now", "title": "Now", "day": 20260601, "date": "2026-06-01"},
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
                    "day": 10,
                    "content_sha256": "a" * 64,
                    "support_sha256": "b" * 64,
                },
            ],
            "role_grant": [
                {"id": "rg-1", "subject": "bob", "role": "reviewer", "from_day": 1},
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

FRONT_DOOR_EXAMPLES = (
    ("examples/subsidy", True),
    ("examples/subsidy-scheme", True),
    ("examples/library", False),
    ("examples/projects", False),
)

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
    "product_newest_day",
    "flow_from_step",
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
# All legacy relation names covered by section 7's explicit intended-difference mapping.
PLATFORM_SECTION_7_LEGACY = (
    PLATFORM_RETIRED_RELATIONS
    | PLATFORM_LEGACY_RENAMED_RELATIONS
    | {"needs", "flow_from_step"}
)
PLATFORM_SECTION_7_NATIVE = (
    PLATFORM_CORE_FUNCTIONAL
    | PLATFORM_RENAMED_BOOL
    | {"needs_service"}
)


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _dl_files_under(directory: Path) -> list[str]:
    return sorted(_rel(path) for path in directory.rglob("*.dl"))


def _synthetic_sidecar(position: str) -> str:
    return yaml.safe_dump(
        {
            "default": {
                "kind": "synthetic",
                "name": "examples/test_rezono_1_pack_conversion.py",
                "position": position,
            }
        },
        sort_keys=False,
    )


def _pack_is_legacy(pack_dir: Path) -> bool:
    """Whether `pack_dir` still holds legacy `.dl` rules or pre-rezono-1 modules."""
    if any(pack_dir.rglob("*.dl")):
        return True
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
    entries = meta.get("rezono") or []
    if not entries:
        return True
    for entry in entries:
        form_path = pack_dir / entry["form"]
        if not form_path.is_file():
            return True
        form = json.loads(form_path.read_bytes())
        if form.get("format") != "rezono.module/5" or (form.get("module") or {}).get("rezono") != "1":
            return True
    return False


def _read_legacy_archive() -> dict[str, dict[str, bytes]]:
    """Read `legacy-packs.tar.gz` into `{pack_rel: {file_rel: bytes}}`."""
    raw: dict[str, bytes] = {}
    with tarfile.open(LEGACY_ARCHIVE, "r:gz") as tf:
        for member in tf.getmembers():
            assert member.isfile() and not member.name.startswith("/") and ".." not in member.name.split("/"), member.name
            handle = tf.extractfile(member)
            assert handle is not None
            raw[member.name] = handle.read()
    pack_roots = sorted(
        (name[: -len("/pack.yaml")] for name in raw if name.endswith("/pack.yaml")),
        key=len,
        reverse=True,
    )
    by_pack: dict[str, dict[str, bytes]] = {root: {} for root in pack_roots}
    for name, data in raw.items():
        owner = next(root for root in pack_roots if name.startswith(root + "/"))
        by_pack[owner][name[len(owner) + 1 :]] = data
    return by_pack


def _live_definition_files(pack_dir: Path, *, include_yaml_facts: bool = False) -> dict[str, bytes]:
    from rezono_compiler import modules

    files: dict[str, bytes] = {}
    for pattern in modules.DEFINITION:
        for path in sorted(pack_dir.glob(pattern)):
            if path.is_file() and "candidate" not in path.relative_to(pack_dir).parts:
                files[path.relative_to(pack_dir).as_posix()] = path.read_bytes().replace(b"\r\n", b"\n")
    if include_yaml_facts and (pack_dir / "facts").is_dir():
        for path in sorted((pack_dir / "facts").glob("*.yaml")):
            files[path.relative_to(pack_dir).as_posix()] = path.read_bytes().replace(b"\r\n", b"\n")
    return files


def _materialize_legacy_packs(dest_root: Path, pack_prefixes: tuple[str, ...]) -> None:
    """Extract legacy packs matching `pack_prefixes` from `legacy-packs.tar.gz` into `dest_root`."""
    by_pack = _read_legacy_archive()
    for pack_rel, files in by_pack.items():
        if not any(pack_rel == prefix or pack_rel.startswith(prefix + "/") for prefix in pack_prefixes):
            continue
        pack_dir = dest_root / pack_rel
        if pack_dir.exists():
            shutil.rmtree(pack_dir)
        for rel_file, data in files.items():
            target = pack_dir / rel_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def _admit_legacy_std_packs(stack: ExitStack, root: Path) -> None:
    """Register every legacy `packs/std-*` materialized under `root` via `standard_packs.trial`."""
    from rezono_compiler import modules, standard_packs

    packs_dir = root / "packs"
    if not packs_dir.is_dir():
        return
    for pack_yaml in sorted(packs_dir.glob("std-*/pack.yaml")):
        std_dir = pack_yaml.parent
        stack.enter_context(standard_packs.trial(std_dir.name, modules.pack_hash(std_dir)))


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
    """Verify a pack has zero `.dl` rules, native `rezono.module/5` (`rezono 1`) forms, and compiles cleanly."""
    dl_files = _dl_files_under(pack_dir)
    assert not dl_files, f"{_rel(pack_dir)} still contains .dl rule files: {dl_files}"

    meta_path = pack_dir / "pack.yaml"
    assert meta_path.is_file(), f"missing {_rel(meta_path)}"
    meta = yaml.safe_load(meta_path.read_bytes()) or {}
    entries = meta.get("rezono") or []
    assert entries, f"{_rel(pack_dir)}/pack.yaml must declare native rezono 1 modules under `rezono:`"

    has_derivation = False
    for entry in entries:
        module_path = pack_dir / entry["module"]
        form_path = pack_dir / entry["form"]
        assert module_path.is_file(), f"missing module {_rel(module_path)}"
        assert form_path.is_file(), f"missing module form {_rel(form_path)}"

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
    assert info.get("language_version") == "1", (
        f"{_rel(pack_dir)} bundle/schema-bundle.json must record language_version == '1': {info!r}"
    )

    ir = json.loads(files["ir/rules.json"]) if "ir/rules.json" in files else {}
    if expect_rules:
        non_base = [r for r in ir.get("relations", []) if r.get("role") != "base"]
        assert non_base, f"{_rel(pack_dir)} compiled ir/rules.json has no derived or functional relations"
    return model, files, bundle, ir


def _roles_for_pack(pack_dir: Path, model) -> dict[str, str]:
    """Discover declared `Role` ids in a pack for per-role publication."""
    roles: dict[str, str] = {"checker": "complete"}
    from rezono_compiler import facts as fact_files

    for path in fact_files.files(pack_dir):
        loaded = fact_files.load(model, path)
        for row in loaded.get("role", ()):
            roles[str(row[0])] = "may_read"
    return roles


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
        "imports": [{"name": std_name, "path": f"packs/{std_name}", "sha256": modules.pack_hash(std_dir)}],
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
        _synthetic_sidecar(f"std-pack-exercise:{std_name}"), encoding="utf-8", newline="\n"
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


def _load_python_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _conflict_witness_candidates(witnesses: dict, relation: str, key: list[str]) -> set[str]:
    """Extract all candidate values/identifiers referenced by conflict witnesses for `(relation, key)`."""
    target_key = json.dumps(key, separators=(",", ":"))
    found: set[str] = set()
    for witness in witnesses.get("witnesses", ()):
        conclusion = witness.get("conclusion") or {}
        if conclusion.get("relation") != relation:
            continue
        concl_key = conclusion.get("key", "")
        if concl_key != target_key and not concl_key.startswith(target_key[:-1] + ","):
            continue
        for candidate in witness.get("candidates", ()):
            if isinstance(candidate, dict):
                if "value" in candidate:
                    found.add(str(candidate["value"]))
                for binding in candidate.get("bindings", ()):
                    found.add(str(binding.get("value", "")))
                for premise in candidate.get("premises", ()):
                    for cell in json.loads(premise["row"]["key"]):
                        found.add(str(cell))
            else:
                found.add(str(candidate))
        for binding in witness.get("bindings", ()):
            found.add(str(binding.get("value", "")))
        for premise in witness.get("premises", ()):
            for cell in json.loads(premise["row"]["key"]):
                found.add(str(cell))
    return found


def test_legacy_snapshots_match_live_example_and_std_packs():
    """While a pack still carries legacy `.dl` rules or pre-rezono-1 modules, its frozen legacy snapshot
    matches the live repository pack byte-for-byte."""
    by_pack = _read_legacy_archive()
    assert by_pack, "legacy-packs.tar.gz must hold the legacy pack snapshots"
    for pack_rel, expected_files in by_pack.items():
        pack_dir = REPO / pack_rel
        if not _pack_is_legacy(pack_dir):
            continue
        want_facts = pack_rel in {"examples/library", "examples/projects"}
        assert _live_definition_files(pack_dir, include_yaml_facts=want_facts) == expected_files, (
            f"legacy snapshot drifted from live legacy pack {pack_rel}"
        )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert every standard pack under packs/std-* to native rezono 1 "
        "modules (zero .dl files and zero rezono 0 rules pipe blocks remaining in packs/std-*) with whole-pack "
        "equivalence via compare_publications across every derived relation, checked grounds, and per-role views. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "and examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch."
    ),
)
def test_standard_packs_convert_to_rezono_1(tmp_path: Path):
    std_packs = sorted(p.parent for p in (REPO / "packs").glob("std-*/pack.yaml"))
    assert std_packs, "expected standard packs under packs/std-*"

    dl_files = sorted(_rel(path) for pack_dir in std_packs for path in pack_dir.rglob("*.dl"))
    assert not dl_files, f"packs/std-* still contains .dl files: {dl_files}"

    by_name = {pack_dir.name: pack_dir for pack_dir in std_packs}
    for name in RULED_STD_PACKS:
        assert name in by_name, f"missing expected standard pack packs/{name}"
        _assert_pack_is_native_rezono_1(by_name[name], expect_rules=True)

    for pack_dir in std_packs:
        if pack_dir.name in RULED_STD_PACKS:
            continue
        meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
        if meta.get("rezono") or (pack_dir / "schema").is_dir():
            _assert_pack_is_native_rezono_1(pack_dir, expect_rules=False)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_compiler import modules, pack
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack, language_usage

    packs_inv = language_usage.inventory(REPO)
    legacy_std = [
        _rel(folder)
        for folder in std_packs
        if "relational-rule" in {
            f
            for vals in packs_inv.get(folder.resolve(), language_usage.PackUsage({}, (), False)).files.values()
            for f in vals
        }
    ]
    assert not legacy_std, f"language_usage.py still reports legacy relational-rule in packs/std-*: {legacy_std}"

    # Materialize the legacy std-* snapshot tree once alongside a clean native std-* tree.
    legacy_root = tmp_path / "legacy-root"
    _materialize_legacy_packs(legacy_root, ("packs",))
    native_root = tmp_path / "native-root"
    shutil.copytree(REPO / "packs", native_root / "packs")

    # 1. packs/std-access: compare whole-pack publications through examples/subsidy across every role.
    def _subsidy_over_std_access(root: Path, *, legacy: bool):
        for example in ("examples/subsidy", "examples/subsidy-scheme"):
            dst = root / example
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(REPO / example, dst)
        consumer = root / "examples" / "subsidy"
        meta = yaml.safe_load((consumer / "pack.yaml").read_bytes())
        for entry in meta["imports"]:
            if entry["name"].startswith("std-"):
                entry["sha256"] = modules.pack_hash(root / "packs" / entry["name"])
        (consumer / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")
        with ExitStack() as stack:
            if legacy:
                _admit_legacy_std_packs(stack, root)
            model = pack.read(consumer)
            roles = _roles_for_pack(consumer, model)
            epoch = publisher_batch.epoch(consumer, epoch=1, knowledge_time=TIME, sources=[("rules", "std-access")])
        return epoch, roles

    legacy_access_epoch, access_roles = _subsidy_over_std_access(legacy_root, legacy=True)
    native_access_epoch, _ = _subsidy_over_std_access(native_root, legacy=False)
    convert_pack.compare_publications(legacy_access_epoch, native_access_epoch, access_roles)

    # 2. Every other ruled standard pack: compare every derived relation and checked ground via compare_publications.
    for std_name, spec in STD_PACK_EXERCISES.items():
        legacy_consumer = _build_consumer_for_std_pack(legacy_root, std_name, spec, "legacy")
        native_consumer = _build_consumer_for_std_pack(native_root, std_name, spec, "native")
        with ExitStack() as stack:
            _admit_legacy_std_packs(stack, legacy_root)
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: Convert the front-door, README, and language-guide examples "
        "(examples/subsidy, examples/subsidy-scheme, examples/library, examples/projects) to native rezono 1 "
        "modules with zero .dl files and whole-pack equivalence against their frozen legacy snapshots, "
        "compare_publications, and independent reference/expected oracles. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and examples/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
    ),
)
def test_front_door_examples_convert_to_rezono_1(tmp_path: Path):
    compiled = {}
    for rel_path, expect_rules in FRONT_DOOR_EXAMPLES:
        compiled[rel_path] = _assert_pack_is_native_rezono_1(REPO / rel_path, expect_rules=expect_rules)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_compiler import facts as fact_files
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    legacy_root = tmp_path / "legacy"
    _materialize_legacy_packs(
        legacy_root,
        ("packs", "examples/library", "examples/projects", "examples/subsidy", "examples/subsidy-scheme"),
    )

    # 1. examples/subsidy (importing examples/subsidy-scheme): compare every legacy rule relation,
    # checked grounds, per-role views, and exact `<k>_<d>` calculation derivations (`application_<rule>`).
    subsidy_dir = REPO / "examples" / "subsidy"
    legacy_subsidy = legacy_root / "examples" / "subsidy"
    shutil.copytree(subsidy_dir / "facts", legacy_subsidy / "facts")

    subsidy_model, _, _, _ = compiled["examples/subsidy"]
    roles = _roles_for_pack(subsidy_dir, subsidy_model)
    assert {"checker", "case_officer", "policy_adviser", "propose", "public", "viewer"} <= set(roles), roles

    with ExitStack() as stack:
        _admit_legacy_std_packs(stack, legacy_root)
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
    (_, base_state), *_ = list(ref.states())
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

    # 2. examples/library and examples/projects: compare_publications on valid dataset + violation parity on valid/errors.
    for rel_path in ("examples/library", "examples/projects"):
        pack_dir = REPO / rel_path
        legacy_pack = legacy_root / rel_path
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
            if label == "legacy":
                legacy_valid_epoch = publisher_batch.epoch(
                    valid_copy, epoch=1, knowledge_time=TIME, sources=[("rules", f"legacy-{pack_dir.name}")]
                )
            else:
                native_valid_epoch = publisher_batch.epoch(
                    valid_copy, epoch=1, knowledge_time=TIME, sources=[("rules", f"native-{pack_dir.name}")]
                )
        convert_pack.compare_publications(legacy_valid_epoch, native_valid_epoch, {"reader": "complete"})

        model, files, _, _ = compiled[rel_path]
        datasets = fact_files.files(pack_dir)
        assert {path.stem for path in datasets} == {"valid", "errors"}, (rel_path, datasets)
        from rezono_compiler import batch as compiler_batch

        for path in datasets:
            rows = fact_files.load(model, path)
            got = compiler_batch.violations(files, rows)
            want = json.loads((pack_dir / "expected" / "violations" / f"{path.stem}.json").read_text(encoding="utf-8"))
            assert {k: {tuple(str(c) for c in r) for r in v} for k, v in got.items()} == {
                k: {tuple(str(c) for c in r) for r in v} for k, v in want.items()
            }, (rel_path, path.stem)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/language-rezono-1.md: Convert examples/platform/rules/*.dl (including its safe steps "
        "and examples/platform/tenant-capacity/interface) to native rezono 1 modules with whole-pack equivalence "
        "across ALL platform relations against its legacy snapshot plus explicit verification of every section 7 "
        "intended semantic difference (invalid multiple_values with full candidate witnesses, unknown no_match, "
        "unknown no_value, and not_applicable empty). "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and examples/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
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

    # Pinned section 7 contract: retired/legacy names absent, every functional & Bool relation asserted unconditionally.
    leftover_retired = sorted((PLATFORM_RETIRED_RELATIONS | PLATFORM_LEGACY_RENAMED_RELATIONS) & set(by_name))
    assert not leftover_retired, f"retired or renamed legacy core.dl relations still present: {leftover_retired}"

    for rel_name in sorted(PLATFORM_CORE_FUNCTIONAL):
        assert rel_name in by_name, f"missing rezono 1 functional derivation {rel_name!r}"
        assert by_name[rel_name].get("role") == "functional", (rel_name, by_name[rel_name])
    assert by_name.get("needs_service", {}).get("role") == "derived", by_name.get("needs_service")

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
    _materialize_legacy_packs(legacy_root, ("packs", "examples/platform"))
    legacy_platform = legacy_root / "examples" / "platform"
    shutil.copytree(platform_dir / "facts", legacy_platform / "facts")
    shutil.copytree(iface_dir / "facts", legacy_platform / "tenant-capacity" / "interface" / "facts")

    roles = _roles_for_pack(platform_dir, platform_model)
    assert "checker" in roles and len(roles) > 1, roles

    with ExitStack() as stack:
        _admit_legacy_std_packs(stack, legacy_root)
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
    assert _known_pairs("product_newest_day") == set(legacy_pub.rows["newest_day"])
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
    assert {(row[0], row[1], row[4]) for row in native_pub.rows["flow_from_step"] if row[2] == "known"} == set(
        legacy_pub.rows["flow_from_step"]
    )
    assert set(native_pub.rows["service_behind_newest"]) == {(row[0],) for row in legacy_pub.rows["behind_newest"]}
    assert set(native_pub.rows["service_authenticates"]) == set(legacy_pub.rows["authenticates"])
    assert set(native_pub.rows["service_verified"]) == set(legacy_pub.rows["verified"])
    assert set(native_pub.rows["service_unverified_supply"]) == set(legacy_pub.rows["unverified_supply"])

    # oracle-rows.json updated in lockstep with rezono 1 bundle names (section 5.5).
    oracle_rows = json.loads((platform_dir / "oracle-rows.json").read_text(encoding="utf-8"))
    for retired in ("ambiguous_provider", "unmet_need", "zone_of", "on_cluster", "runs", "behind_newest", "unverified_supply"):
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
    for offer in core_facts["offer"]:
        for svc in core_facts["service"]:
            if svc["product"] == offer["product"]:
                providers_by_fn.setdefault(offer["function"], []).append((svc["id"], str(offer["port"])))
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
        _admit_legacy_std_packs(stack, legacy_choice_root)
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
    # and `not_applicable empty` (Product.newest_day when a product has zero stable releases).
    empty_root = tmp_path / "native-no-match-and-empty"
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
    empty_newest = {r[0]: (r[1], r[2]) for r in empty_pub.rows["product_newest_day"]}
    empty_runs = {r[0]: (r[1], r[2]) for r in empty_pub.rows["service_runs"]}
    assert empty_needs[(sample_service, "unprovided-fn")] == ("unknown", "no_match"), empty_needs
    assert empty_chosen[(sample_service, "unprovided-fn")] == ("not_applicable", "no_match"), empty_chosen
    assert empty_newest[sample_product] == ("not_applicable", "empty"), empty_newest
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
