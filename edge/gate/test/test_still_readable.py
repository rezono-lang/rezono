"""Historical manifest readability in the local gate (decisions/central-read-access.md, section 5)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

PROBE = Path(__file__).with_name("still-readable-probe.mts")


class EarlierManifestNotRefused(AssertionError):
    """The local gate served an earlier manifest that is no longer readable under current authority."""


@pytest.mark.xfail(
    strict=True,
    raises=EarlierManifestNotRefused,
    reason=(
        "extra: decisions/central-read-access.md: Tighten stillReadable in edge/gate/src/local.ts (section 5): "
        "refuse an earlier complete manifest when the current manifest is not complete (even when present.full "
        "is true), and require matching definition_sha256 before present.full bypasses row-by-row checks."
    ),
)
def test_still_readable_refuses_downgraded_and_redefined_earlier_manifests():
    result = subprocess.run(
        ["node", str(PROBE)],
        cwd=PROBE.parent.parent,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    got = json.loads(result.stdout)

    # Counter-cases that already hold: same-definition full coverage keeps earlier partial readable,
    # while losing full coverage revokes earlier full snapshots.
    assert got["retained_full"] == 200, got
    assert got["lost_full"] == 404, got

    # New requirements from decisions/central-read-access.md section 5:
    if got["downgraded_complete"] != 404 or got["redefined_full"] != 404:
        raise EarlierManifestNotRefused(json.dumps(got, sort_keys=True))
