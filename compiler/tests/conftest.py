import os
import shutil
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings

if os.environ.get("GITHUB_ACTIONS") == "true" and shutil.which("souffle") is None:
    raise RuntimeError("The CI oracle requires Souffle; check the pinned installer.")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
# Bounded per pull request (docs/ci.md); the nightly run sets REZONO_HYPOTHESIS_PROFILE=nightly.
settings.register_profile("ci", max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("pr", max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
# Explicitly random: Hypothesis derandomizes by default on CI, which would hide the fresh seed.
settings.register_profile(
    "nightly", max_examples=150, deadline=None, derandomize=False, database=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("REZONO_HYPOTHESIS_PROFILE", "pr"))


def _blocked_under(base: Path) -> list[str]:
    blocked_dir = ROOT / "blocked"
    if not blocked_dir.is_dir():
        return []
    prefix = base.relative_to(ROOT).as_posix() + "/"
    out = []
    for entry in sorted(blocked_dir.iterdir()):
        if entry.is_file():
            target = entry.read_text(encoding="utf-8").split(":", 1)[0].strip()
            if target.startswith(prefix):
                out.append(target[len(prefix):])
    return out


collect_ignore = _blocked_under(HERE)
collect_ignore_glob = collect_ignore


