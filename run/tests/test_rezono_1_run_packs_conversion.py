"""Strict red test for single-pass rule conversion of every `run/packs/*` pack (`.dl` rules and
embedded `rezono 0` `rules` pipe blocks) to native `rezono 1` modules with whole-pack equivalence
against their frozen legacy snapshots and `run/fixtures/exact-quote-linkml` via `compare_publications`
(decisions/language-rezono-1.md, sections 5.8, 5.10, 6 and 8).
"""

from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
import tarfile

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
RUN_PACKS = REPO / "run" / "packs"
LEGACY_ARCHIVE = REPO / "run" / "fixtures" / "rezono-1-legacy" / "legacy-packs.tar.gz"
EXACT_QUOTE_LINKML = REPO / "run" / "fixtures" / "exact-quote-linkml"
TIME = "2026-11-10T00:00:00Z"

# Synthetic exercise facts (with `kind: synthetic` origins per decisions/fact-origin-required.md §3)
# for every fact-free pack under run/packs/*, plus exact-quote (2 * (3 * 4 + 5) = 34).
RUN_PACK_EXERCISES: dict[str, dict] = {
    "cleanup": {
        "sweep": [{"id": "s-1", "plan_hash": "p1", "coverage": "complete", "run": "r1", "scope": "all"}],
        "page": [{"id": "pg-1", "sweep": "s-1", "token": "t0", "next_token": "", "item_count": 1}],
        "resource": [{"id": "res-1", "sweep": "s-1", "plan_hash": "p1", "page": "pg-1", "provider_id": "vm-1"}],
    },
    "cleanup-deadline": {
        "attempt": [{"id": "att-1", "state": "applied", "deadline_us": 100, "watermark_us": 200}],
    },
    "cluster-shape": {
        "cluster": [{"id": "cl-1", "plan_hash": "p1"}],
        "line": [{"id": "ln-1", "cluster": "cl-1", "sku": "m1", "role": "worker", "quantity": 2}],
        "machine": [
            {
                "id": "mc-1",
                "plan_hash": "p1",
                "sku": "m1",
                "address": "10.0.0.1",
                "boot_disk": "nvme0",
                "data_disk": "nvme1",
            },
        ],
    },
    "dispatch": {
        "candidate": [{"id": "c-1"}],
        "plan": [{"id": "p-1", "candidate": "c-1", "plan_hash": "h1", "currency": "EUR"}],
        "quote": [{"id": "q-1", "candidate": "c-1", "plan_hash": "h1", "currency": "EUR", "cost_micros": 1000}],
        "approval": [
            {
                "id": "a-1",
                "candidate": "c-1",
                "plan_hash": "h1",
                "currency": "EUR",
                "decision": "approve",
                "cap_micros": 2000,
                "expires_us": 500,
            },
        ],
        "observation": [{"id": "o-1", "candidate": "c-1", "event_us": 100}],
    },
    "exact-quote": {
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
    },
    "invoice-drift": {
        "expected_line": [
            {
                "id": "el-1",
                "plan_hash": "h1",
                "item": "cpu",
                "currency": "EUR",
                "sign": "nonnegative",
                "floor_minor": 100,
                "rounding_sha256": "a" * 64,
            },
        ],
        "invoice_line": [{"id": "il-1", "plan_hash": "h1", "item": "cpu", "currency": "EUR", "minor": 100}],
    },
    "probe-profiles": {
        "probe_profile": [{"id": "prof-1"}],
        "probe_phase": [{"id": "ph-1", "precedes": ["ph-2"]}, {"id": "ph-2"}],
    },
}


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _synthetic_sidecar(position: str) -> str:
    return yaml.safe_dump(
        {
            "default": {
                "kind": "synthetic",
                "name": "run/tests/test_rezono_1_run_packs_conversion.py",
                "position": position,
            }
        },
        sort_keys=False,
    )


def _read_legacy_archive() -> dict[str, dict[str, bytes]]:
    raw: dict[str, bytes] = {}
    with tarfile.open(LEGACY_ARCHIVE, "r:gz") as tf:
        for member in tf.getmembers():
            assert (
                member.isfile()
                and not member.issym()
                and not member.islnk()
                and not member.name.startswith("/")
                and "\\" not in member.name
                and ".." not in member.name.split("/")
            ), member.name
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


def _materialize_legacy_packs(dest_root: Path) -> None:
    for pack_rel, files in _read_legacy_archive().items():
        pack_dir = dest_root / pack_rel
        if pack_dir.exists():
            shutil.rmtree(pack_dir)
        for rel_file, data in files.items():
            target = pack_dir / rel_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def _admit_legacy_std_packs(stack: ExitStack, root: Path) -> None:
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


def _assert_pack_is_native_rezono_1(pack_dir: Path) -> object:
    dl_files = sorted(_rel(path) for path in pack_dir.rglob("*.dl"))
    assert not dl_files, f"{_rel(pack_dir)} still contains .dl rule files: {dl_files}"

    meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes()) or {}
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

    assert has_derivation, f"{_rel(pack_dir)} must define native rezono 1 `derived` (or `step`) declarations"

    from rezono_compiler import pack

    return pack.read(pack_dir)


def _assert_epoch_is_rezono_1(pack_label: str, epoch) -> None:
    bundle = json.loads(epoch.bundle)
    info = bundle.get("pack") or {}
    assert info.get("language_version") == "1", (
        f"{pack_label} bundle/schema-bundle.json must record language_version == '1': {info!r}"
    )
    ir = json.loads(epoch.rules)
    assert any(r.get("role") != "base" for r in ir.get("relations", ())), (
        f"{pack_label} compiled ir/rules.json has no derived or functional relations"
    )


def _roles_for_pack(pack_dir: Path, model) -> dict[str, str]:
    roles: dict[str, str] = {"checker": "complete"}
    from rezono_compiler import facts as fact_files

    for path in fact_files.files(pack_dir):
        for row in fact_files.load(model, path).get("role", ()):
            roles[str(row[0])] = "may_read"
    return roles


def test_legacy_run_packs_archive_integrity():
    """Verify `run/fixtures/rezono-1-legacy/legacy-packs.tar.gz` is well-formed (regular files only,
    no symlinks or path traversal) and contains every `run/packs/*` root, its imported standard packs,
    and its legacy `.dl`/rule definitions."""
    assert LEGACY_ARCHIVE.is_file(), f"missing {_rel(LEGACY_ARCHIVE)}"
    by_pack = _read_legacy_archive()
    expected_run_packs = {
        "run/packs/cleanup",
        "run/packs/cleanup-deadline",
        "run/packs/cluster-shape",
        "run/packs/dispatch",
        "run/packs/exact-quote",
        "run/packs/invoice-drift",
        "run/packs/offer-selection",
        "run/packs/probe-profiles",
        "run/packs/provider-terms",
    }
    expected_std_packs = {
        "packs/std-access",
        "packs/std-decision",
        "packs/std-explain",
        "packs/std-loop",
        "packs/std-order",
        "packs/std-part",
        "packs/std-time",
    }
    expected_packs = expected_run_packs | expected_std_packs
    assert expected_packs <= set(by_pack), f"missing packs in archive: {sorted(expected_packs - set(by_pack))}"
    for pack_rel in sorted(expected_packs):
        meta = yaml.safe_load(by_pack[pack_rel]["pack.yaml"])
        assert isinstance(meta, dict) and meta.get("name"), f"invalid pack.yaml in archive for {pack_rel}"

    for pack_rel in sorted(expected_run_packs - {"run/packs/exact-quote"}):
        dl_files = [rel for rel in by_pack[pack_rel] if rel.endswith(".dl")]
        assert dl_files, f"archive pack {pack_rel} is missing legacy .dl definitions"

    assert {"rezono/effective_amount.rezono", "rezono/quote.rezono"} <= set(by_pack["run/packs/exact-quote"]), (
        "archive run/packs/exact-quote is missing its legacy rezono modules"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/language-rezono-1.md: Convert every run/packs/* pack (.dl rules and embedded rezono 0 "
        "rules pipe blocks) to native rezono 1 modules with zero .dl files remaining under run/packs/ and "
        "whole-pack equivalence against their frozen legacy snapshots and run/fixtures/exact-quote-linkml "
        "via compare_publications (grounds included). "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "examples/test_calculation_engine_parity.py--test_feldera_calculations_match_duckdb_and_checker, "
        "examples/test_rule_witness_engine_parity.py--test_feldera_rule_witnesses_match_batch, "
        "and examples/test_rezono_1_pack_conversion.py--test_standard_packs_convert_to_rezono_1."
    ),
)
def test_run_packs_convert_to_rezono_1(tmp_path: Path):
    run_packs = sorted(p.parent for p in RUN_PACKS.glob("*/pack.yaml"))
    assert run_packs, "expected packs under run/packs/*"

    dl_files = sorted(_rel(path) for path in RUN_PACKS.rglob("*.dl"))
    assert not dl_files, f"run/packs/ still contains .dl files: {dl_files}"

    models = {}
    for pack_dir in run_packs:
        models[pack_dir.name] = _assert_pack_is_native_rezono_1(pack_dir)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    legacy_root = tmp_path / "legacy"
    _materialize_legacy_packs(legacy_root)
    native_root = tmp_path / "native"
    shutil.copytree(REPO / "packs", native_root / "packs")
    shutil.copytree(RUN_PACKS, native_root / "run" / "packs")

    # 1. Compare every run/packs/* pack against its frozen legacy snapshot via compare_publications.
    for pack_dir in run_packs:
        name = pack_dir.name
        legacy_pack = legacy_root / "run" / "packs" / name
        native_pack = native_root / "run" / "packs" / name

        # Share existing committed facts (offer-selection, provider-terms, exact-quote/currencies)
        # and add synthetic exercise facts (`kind: synthetic`) where needed so comparison is non-vacuous.
        if (pack_dir / "facts").is_dir():
            shutil.copytree(pack_dir / "facts", legacy_pack / "facts", dirs_exist_ok=True)
        if name in RUN_PACK_EXERCISES:
            exercise = RUN_PACK_EXERCISES[name]
            for target_pack in (legacy_pack, native_pack):
                (target_pack / "facts").mkdir(exist_ok=True)
                (target_pack / "facts" / "exercise.yaml").write_text(
                    yaml.safe_dump(exercise, sort_keys=False), encoding="utf-8", newline="\n"
                )
                (target_pack / "facts" / "exercise.sources.yaml").write_text(
                    _synthetic_sidecar(f"run-pack-exercise:{name}"), encoding="utf-8", newline="\n"
                )

        roles = _roles_for_pack(native_pack, models[name])
        with ExitStack() as stack:
            _admit_legacy_std_packs(stack, legacy_root)
            legacy_epoch = publisher_batch.epoch(
                legacy_pack, epoch=1, knowledge_time=TIME, sources=[("rules", f"legacy-{name}")]
            )
            legacy_pub = convert_pack.read_publication(legacy_epoch, tmp_path / f"legacy-check-{name}", roles)
        base_tables = set(RUN_PACK_EXERCISES.get(name, ()))
        non_empty_derived = [
            rel for rel, rows in legacy_pub.rows.items()
            if rows and rel not in base_tables and "__" not in rel
        ]
        assert non_empty_derived, f"run/packs/{name} comparison derived zero rows (vacuous comparison)"
        native_epoch = publisher_batch.epoch(
            native_pack, epoch=1, knowledge_time=TIME, sources=[("rules", f"native-{name}")]
        )
        _assert_epoch_is_rezono_1(f"run/packs/{name}", native_epoch)
        convert_pack.compare_publications(legacy_epoch, native_epoch, roles)

    # 2. Independent LinkML+Datalog oracle check for run/packs/exact-quote against run/fixtures/exact-quote-linkml
    # (exact amount_digit rows + checked grounds via compare_publications).
    assert EXACT_QUOTE_LINKML.is_dir(), f"missing {_rel(EXACT_QUOTE_LINKML)}"
    from test_exact_quote_language import legacy as build_legacy_quote_oracle
    from test_exact_quote_language import quote_only as build_native_quote_only

    eq_legacy = build_legacy_quote_oracle(tmp_path / "eq-linkml-oracle")
    eq_native = build_native_quote_only(tmp_path / "eq-native-quote")
    for target in (eq_legacy, eq_native):
        (target / "facts").mkdir(exist_ok=True)
        (target / "facts" / "exercise.yaml").write_text(
            yaml.safe_dump(RUN_PACK_EXERCISES["exact-quote"], sort_keys=False), encoding="utf-8", newline="\n"
        )
        (target / "facts" / "exercise.sources.yaml").write_text(
            _synthetic_sidecar("exact-quote-linkml-parity"), encoding="utf-8", newline="\n"
        )
    eq_legacy_epoch = publisher_batch.epoch(eq_legacy, epoch=1, knowledge_time=TIME, sources=[("rules", "linkml")])
    eq_native_epoch = publisher_batch.epoch(eq_native, epoch=1, knowledge_time=TIME, sources=[("rules", "rezono-1")])
    convert_pack.compare_publications(eq_legacy_epoch, eq_native_epoch, {"checker": "complete"})

    eq_pub = convert_pack.read_publication(eq_native_epoch, tmp_path / "eq-digits-store", {"checker": "complete"})
    expected_digits = {
        ("l-1", "0", "4"),
        ("l-1", "1", "3"),
        ("q-1", "0", "4"),
        ("q-1", "1", "3"),
    }
    got_digits = {tuple(str(cell) for cell in row) for row in eq_pub.rows["amount_digit"]}
    assert got_digits == expected_digits, f"exact-quote amount_digit diverged: {got_digits!r}"
