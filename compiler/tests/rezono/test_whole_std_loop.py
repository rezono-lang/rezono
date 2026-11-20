"""Staged candidate acceptance for packs/std-loop (decisions/language-standard-pack-candidates.md)."""

import pytest

from staged_candidate import MissingStagedCandidate, assert_legacy_oracle, assert_staged_candidate_matches_legacy


PACK = "packs/std-loop"


def test_std_loop_legacy_oracle_compiles(tmp_path):
    assert_legacy_oracle(tmp_path, PACK)


def test_whole_std_loop_candidate_has_the_same_meaning(tmp_path):
    assert_staged_candidate_matches_legacy(tmp_path, PACK)
