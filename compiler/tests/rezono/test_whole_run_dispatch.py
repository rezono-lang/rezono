"""Staged candidate acceptance for run/packs/dispatch (decisions/language-standard-pack-candidates.md)."""

import pytest

from staged_candidate import MissingStagedCandidate, assert_legacy_oracle, assert_staged_candidate_matches_legacy


PACK = "run/packs/dispatch"


def test_run_dispatch_legacy_oracle_compiles(tmp_path):
    assert_legacy_oracle(tmp_path, PACK)


def test_whole_run_dispatch_candidate_has_the_same_meaning(tmp_path):
    assert_staged_candidate_matches_legacy(tmp_path, PACK)
