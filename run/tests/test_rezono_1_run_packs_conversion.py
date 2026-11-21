"""Strict red test for single-pass rule conversion of every `run/packs/*` pack (`.dl` rules and
embedded `rezono 0` `rules` pipe blocks) to native `rezono 1` modules with whole-pack equivalence
against their frozen legacy snapshots and `run/fixtures/exact-quote-linkml` via `compare_publications`
(decisions/language-rezono-1.md, sections 5.8, 5.10, 6 and 8).
"""

from __future__ import annotations

from contextlib import ExitStack
import importlib.util
from pathlib import Path
import shutil
import sys

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
RUN_PACKS = REPO / "run" / "packs"
EXACT_QUOTE_LINKML = REPO / "run" / "fixtures" / "exact-quote-linkml"
LEGACY_HELPERS_PATH = REPO / "examples" / "fixtures" / "rezono-1-legacy" / "helpers.py"


def _load_legacy_helpers():
    spec = importlib.util.spec_from_file_location("rezono_1_legacy_helpers", LEGACY_HELPERS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LEGACY = _load_legacy_helpers()
TIME = _LEGACY.TIME

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


def test_legacy_run_packs_archive_integrity():
    """Verify the shared legacy archive holds every `run/packs/*` root and its imported standard packs,
    and matches live definition files byte-for-byte (LF-normalized) for every pack that is still legacy."""
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
    _LEGACY.assert_legacy_archive_integrity(
        expected_packs,
        expected_dl_packs=expected_run_packs - {"run/packs/exact-quote"},
        expected_files={
            "run/packs/exact-quote": {"rezono/effective_amount.rezono", "rezono/quote.rezono"},
        },
    )
    _LEGACY.assert_legacy_packs_match_archive(expected_packs)


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
        "examples/test_rezono_1_pack_conversion.py--test_std_access_converts_to_rezono_1, "
        "--test_std_decision_converts_to_rezono_1, --test_std_loop_converts_to_rezono_1, "
        "--test_std_part_converts_to_rezono_1, "
        "and --test_std_time_converts_to_rezono_1 (the standard packs run/packs/* import)."
    ),
)
def test_run_packs_convert_to_rezono_1(tmp_path: Path):
    run_packs = sorted(p.parent for p in RUN_PACKS.glob("*/pack.yaml"))
    assert run_packs, "expected packs under run/packs/*"

    dl_files = _LEGACY.dl_files_under(RUN_PACKS)
    assert not dl_files, f"run/packs/ still contains .dl files: {dl_files}"

    models = {}
    for pack_dir in run_packs:
        models[pack_dir.name] = _LEGACY.assert_pack_is_native_rezono_1(pack_dir, compile_output=False)

    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from rezono_publisher import batch as publisher_batch
    from scripts import convert_pack

    legacy_root = tmp_path / "legacy"
    _LEGACY.materialize_legacy_packs(legacy_root, ("packs", "run/packs"))
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
                    _LEGACY.synthetic_sidecar(
                        "run/tests/test_rezono_1_run_packs_conversion.py", f"run-pack-exercise:{name}"
                    ),
                    encoding="utf-8",
                    newline="\n",
                )

        roles = _LEGACY.roles_for_pack(native_pack, models[name])
        with ExitStack() as stack:
            _LEGACY.admit_legacy_std_packs(stack, legacy_root)
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
        _LEGACY.assert_epoch_is_rezono_1(f"run/packs/{name}", native_epoch)
        convert_pack.compare_publications(legacy_epoch, native_epoch, roles)

    # 2. Independent LinkML+Datalog oracle check for run/packs/exact-quote against run/fixtures/exact-quote-linkml
    # (exact amount_digit rows + checked grounds via compare_publications).
    assert EXACT_QUOTE_LINKML.is_dir(), f"missing {_LEGACY.rel(EXACT_QUOTE_LINKML)}"
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
            _LEGACY.synthetic_sidecar("run/tests/test_rezono_1_run_packs_conversion.py", "exact-quote-linkml-parity"),
            encoding="utf-8",
            newline="\n",
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
