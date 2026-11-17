"""The time budget of the published profile (RV-Z11; docs/ci.md, section 6).

`publish.budget_minutes` of the profile is the time deploy/profiles/edge/publish.sh may take over every pack of
`publish.packs`, none skipped, in promote's job `publish`. It has three readers and no other copy: publish.sh
(`compare`, after it ran the whole list), the job `profile` of publisher.yml (`minutes`), and
edge/githost/tests/test_workflows.py, which holds that job's `timeout-minutes` at twice it.

  python deploy/profiles/edge/budget.py minutes PROFILE
  python deploy/profiles/edge/budget.py compare PROFILE SECONDS TIMES [PACK ...]

`compare` writes one line to the log and to the step summary (`$GITHUB_STEP_SUMMARY`, if set). Over the budget
the line is a warning that names the slowest pack and that pack's largest phase, read from TIMES: the
`time <pack> <phase> <seconds>s <share>` lines of rede_publisher.timing. It never fails on time: the
publication is true whatever it took. A run with skipped packs that is over the budget is over it a fortiori.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml


def minutes(profile: dict) -> int | None:
    """The profile's `publish.budget_minutes`: a whole number of minutes, at least one; None when it has none."""
    value = ((profile or {}).get("publish") or {}).get("budget_minutes")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"publish.budget_minutes must be a whole number of minutes, at least 1, not {value!r}")
    return value


def phases(lines: list[str]) -> dict[str, dict[str, float]]:
    """Seconds per phase per pack, from rede_publisher.timing's log lines; other lines and totals are left out."""
    out: dict[str, dict[str, float]] = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[0] == "time" and parts[2] != "total" and parts[3].endswith("s"):
            try:
                seconds = float(parts[3][:-1])
            except ValueError:
                continue
            out.setdefault(parts[1], {})[parts[2]] = seconds
    return out


def clock(seconds: int) -> str:
    return f"{seconds // 60} min {seconds % 60} s"


def verdict(budget: int, seconds: int, lines: list[str]) -> tuple[bool, str]:
    """Whether the run is over the budget, and the line that says so; the slowest pack and its largest phase
    when it is over."""
    said = f"the profile took {clock(seconds)}; its budget is {budget} minutes (publish.budget_minutes)"
    if seconds <= budget * 60:
        return False, said
    per_pack = phases(lines)
    if not per_pack:
        return True, f"{said}: over it, and no pack reported its phases"
    slowest = max(sorted(per_pack), key=lambda p: sum(per_pack[p].values()))
    largest = max(sorted(per_pack[slowest]), key=per_pack[slowest].get)
    return True, (f"{said}: over it by {clock(seconds - budget * 60)}. The slowest pack is {slowest} "
                  f"({sum(per_pack[slowest].values()):.0f} s), its largest phase {largest} "
                  f"({per_pack[slowest][largest]:.0f} s)")


def compare(profile_path: str, seconds: int, times: str, packs: list[str]) -> int:
    profile = yaml.safe_load(Path(profile_path).read_text(encoding="utf-8")) or {}
    budget = minutes(profile)
    if budget is None or sorted(packs) != sorted((profile.get("publish") or {}).get("packs") or []):
        return 0  # no budget, or not the whole list: nothing to compare
    lines = Path(times).read_text(encoding="utf-8").splitlines() if times and Path(times).is_file() else []
    over, line = verdict(budget, seconds, lines)
    print(f"::warning::{line}" if over else line, flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"\n**Over the time budget:** {line}.\n" if over else f"\nTime budget: {line}.\n")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "minutes":
        budget = minutes(yaml.safe_load(Path(argv[1]).read_text(encoding="utf-8")))
        if budget is None:
            print(f"::error::{argv[1]} has no publish.budget_minutes")
            return 1
        print(budget)
        return 0
    if len(argv) >= 4 and argv[0] == "compare":
        return compare(argv[1], int(argv[2]), argv[3], argv[4:])
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
