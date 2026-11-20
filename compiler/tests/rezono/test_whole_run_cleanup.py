"""Staged candidate acceptance for run/packs/cleanup (decisions/language-standard-pack-candidates.md)."""

import pytest

from staged_candidate import MissingStagedCandidate, assert_legacy_oracle, assert_staged_candidate_matches_legacy


PACK = "run/packs/cleanup"


def test_run_cleanup_legacy_oracle_compiles(tmp_path):
    assert_legacy_oracle(tmp_path, PACK)


@pytest.mark.xfail(
    strict=True,
    raises=MissingStagedCandidate,
    reason="M3: decisions/language-standard-pack-candidates.md: Stage Rezono modules and generated JSON forms for "
           "run/packs/cleanup under run/packs/cleanup/candidate/ (leaving schema/, rules/, and pack.yaml intact "
           "as the live oracle), starting from scripts/convert_pack.py, so the isolated candidate build matches "
           "the legacy schema model, semantic schema bundle, and compiled rule IR.",
)
def test_whole_run_cleanup_candidate_has_the_same_meaning(tmp_path):
    assert_staged_candidate_matches_legacy(tmp_path, PACK)
