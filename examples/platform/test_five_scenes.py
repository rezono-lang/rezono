"""Five-scene organization, standard loop and decision integration, README counts, and offline scene replay.

Contract source: decisions/platform-five-scenes.md.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parent
REPO = PLATFORM.parents[1]
SCENES_FILE = PLATFORM / "scenes.yaml"
QUESTIONS_FILE = PLATFORM / "questions.yaml"
PACK_FILE = PLATFORM / "pack.yaml"
README_FILE = PLATFORM / "README.md"
RECORDINGS_DIR = PLATFORM / "recordings"

VALID_SCENES = {1, 2, 3, 4, 5}
OUTSIDE = "outside_scenes"

STD_LOOP_CORE_RELATIONS = frozenset({
    "declared",
    "needed",
    "known",
    "waiting",
    "ready",
    "done",
    "stuck",
    "drift",
    "fixed_point",
    "plan",
    "round_outcome",
    "unblocked",
    "loop_certified_batch",
    "loop_selected_batch",
})

REQUIRED_AREAS_BY_SCENE = {
    1: frozenset({"placement", "zone_matrix"}),
    2: frozenset({"capacity", "shared_cost", "review"}),
    3: frozenset({"product_stance"}),
    4: frozenset({"backup_policy"}),
    5: frozenset({"exclusion", "access_policy"}),
}

PRODUCED_OBJECT_RELATIONS = (
    "cluster_service_placement",
    "cluster_control_host",
    "cluster_fleet_member",
    "cluster_worker_host",
    "cluster_worker_interface",
    "cluster_machine_stack",
    "cluster_network_stack",
    "cluster_firewall_rule",
    "cluster_in_zone_policy",
    "managed_cluster_right",
    "tenant_delivery_item",
)

REAL_REQUIRED_SCENES = frozenset({1, 4})
ALLOWED_ORIGINS = frozenset({"real", "hand-written"})

_DECL_PATTERN = re.compile(r"^\s*\.decl\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SUMMARY_COUNTS = re.compile(r"\b(\d+)\s+decisions\s+produce\s+(\d+)\s+produced\s+objects\b", re.I)


def _load_yaml_unique(path: Path) -> object:
    class UniqueLoader(yaml.SafeLoader):
        pass

    def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
        mapping: dict = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in mapping:
                raise AssertionError(f"Duplicate YAML key {key!r} in {path.name}")
            mapping[key] = loader.construct_object(value_node, deep=deep)
        return mapping

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)


def _load_platform_facts() -> dict[str, list[dict]]:
    combined: dict[str, list[dict]] = {}
    for path in sorted((PLATFORM / "facts").glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        for kind, rows in data.items():
            if isinstance(rows, list):
                combined.setdefault(kind, []).extend(rows)
    return combined


def _iso_day(value: object, label: str) -> str:
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, str) and _ISO_DATE.fullmatch(value):
        datetime.date.fromisoformat(value)
        return value
    raise AssertionError(f"{label} must be a YYYY-MM-DD date, got {value!r}")


def _publish_checker_relations(tmp_path: Path) -> dict[str, list[dict]]:
    from rezono_publisher import batch, publish, store

    bucket = store.FileStore(tmp_path / "published")
    epoch = batch.epoch(
        PLATFORM,
        epoch=1,
        knowledge_time="2026-11-20T00:00:00Z",
        sources=[("rules", "five-scenes-check")],
    )
    manifest = publish.publish(epoch, bucket, {"checker": "complete"})
    objects = publish.role_objects(bucket, epoch.pack, manifest["id"], "checker")
    return {
        name.removeprefix("relations/").removesuffix(".json"): json.loads(bucket.get(key))
        for name, key in objects.items()
        if name.startswith("relations/")
    }


def test_every_question_belongs_to_one_scene_or_outside_with_reason():
    assert SCENES_FILE.is_file(), "examples/platform/scenes.yaml must exist"
    questions_doc = _load_yaml_unique(QUESTIONS_FILE)
    assert isinstance(questions_doc, dict) and isinstance(questions_doc.get("acceptance"), list)
    question_ids = [entry["id"] for entry in questions_doc["acceptance"]]
    assert len(question_ids) == len(set(question_ids)), "Duplicate acceptance question IDs in questions.yaml"
    expected_ids = set(question_ids)

    scenes_doc = _load_yaml_unique(SCENES_FILE)
    assert isinstance(scenes_doc, dict)
    assert scenes_doc.get("format") == "rezono.platform.scenes/1"
    assert set(scenes_doc) == {"format", "scenes", "questions"}

    scenes = scenes_doc["scenes"]
    assert isinstance(scenes, dict) and set(scenes) == VALID_SCENES
    slugs: set[str] = set()
    for number, meta in scenes.items():
        assert type(number) is int and isinstance(meta, dict)
        assert set(meta) == {"slug", "title", "summary"}
        for field in ("slug", "title", "summary"):
            assert isinstance(meta[field], str) and meta[field].strip(), f"scene {number} missing {field}"
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", meta["slug"]), f"scene {number} slug must be a slug"
        slugs.add(meta["slug"])
    assert len(slugs) == len(VALID_SCENES), "Scene slugs must be distinct"

    assignments = scenes_doc["questions"]
    assert isinstance(assignments, dict)
    actual_ids = set(assignments)
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    assert not missing, f"Questions missing from scenes.yaml: {missing}"
    assert not extra, f"Stale or unknown questions in scenes.yaml: {extra}"

    covered_scenes: set[int] = set()
    for qid, entry in assignments.items():
        assert isinstance(entry, dict), f"{qid} must map to a YAML mapping"
        scene = entry.get("scene")
        if scene == OUTSIDE:
            assert set(entry) == {"scene", "reason"}, f"{qid} outside_scenes entry needs scene and reason only"
            reason = entry.get("reason")
            assert isinstance(reason, str) and reason.strip(), f"{qid} outside_scenes entry requires a non-empty reason"
        else:
            assert type(scene) is int and scene in VALID_SCENES, (
                f"{qid} must assign an integer scene in 1..5 or {OUTSIDE!r}, got {scene!r}"
            )
            assert set(entry) == {"scene"}, f"{qid} numbered scene entry should only contain 'scene'"
            covered_scenes.add(scene)

    assert covered_scenes == VALID_SCENES, f"Every scene 1..5 must contain at least one question; got {sorted(covered_scenes)}"


def test_platform_imports_std_loop():
    pack_doc = yaml.safe_load(PACK_FILE.read_text(encoding="utf-8"))
    imports = pack_doc.get("imports", [])
    by_name = {entry["name"]: entry for entry in imports}
    assert "std-loop" in by_name, "examples/platform/pack.yaml must import std-loop"

    entry = by_name["std-loop"]
    assert re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))), "std-loop import must pin a 64-hex sha256"
    target = (PLATFORM / entry["path"]).resolve()
    assert target == (REPO / "packs" / "std-loop").resolve(), "std-loop import must point to packs/std-loop"

    from rezono_compiler import modules, pack, rules

    assert entry["sha256"] == modules.pack_hash(target), "std-loop pin in pack.yaml does not match packs/std-loop hash"

    redeclared: list[str] = []
    for dl_path in sorted((PLATFORM / "rules").glob("*.dl")):
        text = dl_path.read_text(encoding="utf-8")
        for relation in _DECL_PATTERN.findall(text):
            if relation in STD_LOOP_CORE_RELATIONS:
                redeclared.append(f"{dl_path.name}:{relation}")
    assert not redeclared, f"Platform rules must not rebuild std-loop core relations: {redeclared}"

    model = pack.read(PLATFORM)
    program = rules.load(model.rules)
    derived = set(program.derived())
    required = {"declared", "needed", "known", "waiting", "ready", "done", "stuck", "drift", "round_outcome"}
    assert required <= derived, f"Compiled platform pack missing std-loop relations: {sorted(required - derived)}"


def test_scene_decisions_are_std_decision_facts(tmp_path):
    fact_rows = _load_platform_facts()
    decisions = fact_rows.get("decision", [])
    subjects = fact_rows.get("subject", [])
    reference_dates = fact_rows.get("reference_date", [])
    bindings = fact_rows.get("platform_decision_binding", [])

    assert decisions, "examples/platform/facts/ must declare std-decision 'decision' rows for the five scenes"
    assert subjects, "examples/platform/facts/ must declare std-decision 'subject' rows"
    assert reference_dates, "examples/platform/facts/ must declare a std-decision 'reference_date' row"
    for row in reference_dates:
        ref_date = _iso_day(row.get("date"), f"reference_date {row.get('id')!r} date")
        expected_day = int(ref_date.replace("-", ""))
        assert row.get("day") == expected_day, (
            f"Reference date {row.get('id')!r} day must equal {expected_day}"
        )
    assert bindings, "examples/platform/facts/ must declare 'platform_decision_binding' rows for the five scenes"

    subject_ids = {row["id"] for row in subjects}
    by_id: dict[str, dict] = {}
    for row in decisions:
        did = row["id"]
        assert did not in by_id, f"Duplicate decision id {did!r}"
        by_id[did] = row
        assert isinstance(row.get("title"), str) and row["title"].strip(), f"Decision {did!r} needs a title"
        assert row.get("subject") in subject_ids, f"Decision {did!r} references unknown subject {row.get('subject')!r}"
        if row.get("state") != "proposed":
            deciders = row.get("decider")
            assert isinstance(deciders, list) and deciders and all(isinstance(d, str) and d.strip() for d in deciders), (
                f"Decision {did!r} must record at least one decider"
            )
            _iso_day(row.get("decided_on"), f"decision {did!r} decided_on")
            valid_from = _iso_day(row.get("valid_from"), f"decision {did!r} valid_from")
            expected_day = int(valid_from.replace("-", ""))
            assert row.get("valid_from_day") == expected_day, (
                f"Decision {did!r} valid_from_day must equal {expected_day}"
            )

    in_force_areas: dict[str, set[str]] = {}
    for binding in bindings:
        did = binding.get("decision")
        area = binding.get("area")
        assert did in by_id, f"Binding {binding.get('id')!r} references unknown decision {did!r}"
        if by_id[did].get("state") == "in_force":
            in_force_areas.setdefault(area, set()).add(did)

    for scene, required_areas in REQUIRED_AREAS_BY_SCENE.items():
        missing_areas = sorted(area for area in required_areas if not in_force_areas.get(area))
        assert not missing_areas, f"Scene {scene} lacks in-force bound decisions for areas: {missing_areas}"

    published = _publish_checker_relations(tmp_path)
    in_force_decisions = {row["key"][0] for row in published.get("in_force_on", ())}
    effective_decisions = {row["key"][0] for row in published.get("effective_platform_decision", ())}
    missing_deciders = published.get("in_force_without_decider", [])
    assert not missing_deciders, f"In-force decisions without decider: {missing_deciders}"

    bound_in_force = {did for dids in in_force_areas.values() for did in dids}
    assert bound_in_force <= in_force_decisions, (
        f"Bound scene decisions not in force on reference date: {sorted(bound_in_force - in_force_decisions)}"
    )
    assert bound_in_force <= effective_decisions, (
        f"Bound scene decisions missing from effective_platform_decision: {sorted(bound_in_force - effective_decisions)}"
    )


def test_platform_readme_names_five_scenes_and_matches_publication_counts(tmp_path):
    assert README_FILE.is_file(), "examples/platform/README.md must exist"
    text = README_FILE.read_text(encoding="utf-8")

    scenes = _load_yaml_unique(SCENES_FILE)["scenes"]
    for number in sorted(VALID_SCENES):
        title = scenes[number]["title"]
        assert title in text, f"examples/platform/README.md must name scene {number}: {title!r}"

    matches = _SUMMARY_COUNTS.findall(text)
    assert len(matches) == 1, (
        "examples/platform/README.md must state exactly one summary count matching "
        "'<D> decisions produce <O> produced objects'"
    )
    readme_decisions, readme_objects = (int(matches[0][0]), int(matches[0][1]))

    published = _publish_checker_relations(tmp_path)
    live_decisions = len({row["key"][0] for row in published.get("in_force_on", ())})
    live_objects = sum(len(published.get(relation, ())) for relation in PRODUCED_OBJECT_RELATIONS)
    assert live_decisions > 0, "Live publication must have at least one in-force decision"
    assert live_objects > 0, "Live publication must produce at least one operational object"
    assert readme_decisions == live_decisions, (
        f"README decision count ({readme_decisions}) differs from live publication ({live_decisions})"
    )
    assert readme_objects == live_objects, (
        f"README produced-object count ({readme_objects}) differs from live publication ({live_objects})"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/platform-five-scenes.md: Add one offline-replayable std-loop recording and manifest per "
        "scene under examples/platform/recordings/scene-<n>-<slug>/; scenes 1 and 4 require real recordings "
        "from the loop apply/readback executor, while scenes 2, 3 and 5 may start hand-written. "
        "Although loop/executor.py, test_startup_safe_rounds_live, test_management_dataset_restored_offline, "
        "and test_platform_safe_rounds_recorded are now on main, loop/startup_rounds.py and "
        "loop/cluster/record_management_backup.py do not run through loop.executor.execute or persist "
        "TypedRecording (recording.json) artifacts from the disposable cluster, so honest origin='real' "
        "recordings for scenes 1 and 4 cannot be produced until those cluster runs export typed recordings."
    ),
)
def test_each_scene_has_an_offline_replayable_recorded_run():
    assert RECORDINGS_DIR.is_dir(), "examples/platform/recordings/ must exist with one recorded run per scene"
    scenes = _load_yaml_unique(SCENES_FILE)["scenes"]

    from loop.recording_input import load_recording
    from loop.replay import replay_report
    from loop.typed_recording import TypedRecording

    for number in sorted(VALID_SCENES):
        slug = scenes[number]["slug"]
        scene_dir = RECORDINGS_DIR / f"scene-{number}-{slug}"
        manifest_path = scene_dir / "manifest.json"
        recording_path = scene_dir / "recording.json"
        assert manifest_path.is_file(), f"Missing scene {number} manifest: {manifest_path.relative_to(REPO)}"
        assert recording_path.is_file(), f"Missing scene {number} recording: {recording_path.relative_to(REPO)}"

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert isinstance(manifest, dict)
        assert manifest.get("scene") == number
        origin = manifest.get("origin")
        assert origin in ALLOWED_ORIGINS, f"Scene {number} origin must be in {sorted(ALLOWED_ORIGINS)}, got {origin!r}"
        if number in REAL_REQUIRED_SCENES:
            assert origin == "real", f"Scene {number} requires a real cluster recording, got {origin!r}"
        if origin == "real":
            _iso_day(manifest.get("captured_on"), f"scene {number} manifest captured_on")
            evidence = manifest.get("capture_evidence")
            assert isinstance(evidence, str) and evidence.strip(), (
                f"Scene {number} real recording must declare non-empty capture_evidence"
            )

        expected_plans = manifest.get("expected_plans")
        expected_outcome = manifest.get("expected_outcome")
        assert isinstance(expected_plans, list) and expected_plans and all(
            isinstance(round_plans, list) for round_plans in expected_plans
        ), f"Scene {number} manifest must declare non-empty expected_plans"
        assert expected_outcome in {"success", "failure"}, (
            f"Scene {number} manifest expected_outcome must be 'success' or 'failure', got {expected_outcome!r}"
        )

        loaded = load_recording(recording_path)
        assert isinstance(loaded, TypedRecording), f"Scene {number} recording must be a typed std-loop recording"
        actual_plans, actual_outcome, _ = replay_report(
            loaded.run, loaded.limit, loaded.snapshots(), report_limit=True
        )
        assert actual_plans == expected_plans, f"Scene {number} offline replay plans diverged from manifest"
        assert actual_outcome == expected_outcome, (
            f"Scene {number} offline replay outcome {actual_outcome!r} != {expected_outcome!r}"
        )
