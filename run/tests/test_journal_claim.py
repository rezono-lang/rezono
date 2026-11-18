from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from offline_cases import implementation, PLAN_HASH


@pytest.mark.xfail(strict=True, reason="Read decisions/run-offline-acceptance.md. Implement run/journal_claim.py.")
def test_journal_claim(tmp_path):
    claim = implementation("journal_claim.py", "claim_once")
    db = tmp_path / "journal.sqlite"
    start = Barrier(8)
    def attempt(_):
        start.wait(timeout=10)
        return claim(db, PLAN_HASH)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count(True) == 1 and results.count(False) == 7
    fresh = implementation("journal_claim.py", "claim_once")
    assert fresh(db, PLAN_HASH) is False
    assert fresh(db, "b" * 64) is True
    with pytest.raises(ValueError):
        fresh(db, "bad-digest")
