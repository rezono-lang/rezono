#!/usr/bin/env python3
"""Open an issue when no pull request was opened or merged for a while and red tests wait.

The script reads two moments through the GitHub API: when the most recent pull request was
opened and when the most recent one was merged, ignoring branches that start with
``dependabot/``. From the checkout it counts the red tests that are not marked ``later: ``,
the same way ``scripts/red_list.py`` lists them. It depends on neither the engine nor a pack,
so the alert still works when the build itself is red.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Hours without an opened or merged pull request before red tests count as a standstill.
# The choice is recorded in decisions/standstill-alert.md.
STANDSTILL_HOURS = 2

LABEL = "standstill"
LATER_MARK = "later: "
IGNORED_BRANCH_PREFIX = "dependabot/"
PER_PAGE = 50
MAX_PAGES = 10
TITLE = "No pull request opened or merged while red tests wait"


def parse_time(value: str) -> dt.datetime:
    moment = dt.datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError(f"time without a zone: {value}")
    return moment.astimezone(dt.UTC)


def format_time(moment: dt.datetime | None) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") if moment else "none"


def counts(pull: dict) -> bool:
    return not pull["head"]["ref"].startswith(IGNORED_BRANCH_PREFIX)


def count_red(root: Path = ROOT) -> int:
    """Count the expected-red tests whose reason does not start with the later mark."""
    from red_list import collect_red_tests

    return sum(1 for item in collect_red_tests(root) if not item.reason.startswith(LATER_MARK))


def last_opened(github) -> dt.datetime | None:
    for page in range(1, MAX_PAGES + 1):
        pulls = github.pulls("all", "created", page)
        for pull in pulls:
            if counts(pull):
                return parse_time(pull["created_at"])
        if len(pulls) < PER_PAGE:
            break
    return None


def last_merged(github) -> dt.datetime | None:
    # A pull request is updated when it merges, so once a page reaches updates older than
    # the best merge seen, no later page can hold a more recent merge.
    best: dt.datetime | None = None
    for page in range(1, MAX_PAGES + 1):
        pulls = github.pulls("closed", "updated", page)
        for pull in pulls:
            if pull.get("merged_at") and counts(pull):
                merged = parse_time(pull["merged_at"])
                best = merged if best is None or merged > best else best
        if len(pulls) < PER_PAGE or (best and parse_time(pulls[-1]["updated_at"]) < best):
            break
    return best


def issue_body(opened: dt.datetime | None, merged: dt.datetime | None, red: int) -> str:
    return (
        f"Last pull request opened: {format_time(opened)}\n"
        f"Last pull request merged: {format_time(merged)}\n"
        f"Red tests not marked later: {red}\n"
    )


def run(github, now: dt.datetime, red: int) -> list[str]:
    """Open or close the standstill issue and return what was done."""
    opened = last_opened(github)
    merged = last_merged(github)
    moments = [moment for moment in (opened, merged) if moment]
    last = max(moments) if moments else None
    print(f"Last opened {format_time(opened)}, last merged {format_time(merged)}, red {red}")
    issues = github.open_issues()
    actions: list[str] = []
    if issues:
        for issue in issues:
            if last and last > parse_time(issue["created_at"]):
                github.close_issue(issue["number"])
                actions.append(f"closed #{issue['number']}")
        return actions
    if red > 0 and (last is None or now - last > dt.timedelta(hours=STANDSTILL_HOURS)):
        github.ensure_label()
        number = github.create_issue(TITLE, issue_body(opened, merged, red))
        actions.append(f"opened #{number}")
    return actions


class GitHub:
    """The GitHub REST calls the alert needs, through the gh command line client."""

    def __init__(self, repo: str):
        self.root = f"repos/{repo}"

    def _api(self, *args: str, check: bool = True):
        result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=False)
        if check and result.returncode != 0:
            raise RuntimeError(f"gh api {' '.join(args)} failed: {result.stderr.strip()}")
        if result.returncode != 0:
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None

    def pulls(self, state: str, sort: str, page: int) -> list[dict]:
        return self._api(
            f"{self.root}/pulls?state={state}&sort={sort}&direction=desc"
            f"&per_page={PER_PAGE}&page={page}"
        )

    def open_issues(self) -> list[dict]:
        issues = self._api(f"{self.root}/issues?state=open&labels={LABEL}&per_page=100")
        return [issue for issue in issues if "pull_request" not in issue]

    def ensure_label(self) -> None:
        if self._api(f"{self.root}/labels/{LABEL}", check=False) is None:
            self._api("-X", "POST", f"{self.root}/labels", "-f", f"name={LABEL}",
                      "-f", "color=d93f0b",
                      "-f", "description=No pull request opened or merged while red tests wait")

    def create_issue(self, title: str, body: str) -> int:
        issue = self._api("-X", "POST", f"{self.root}/issues", "-f", f"title={title}",
                          "-f", f"body={body}", "-f", f"labels[]={LABEL}")
        return issue["number"]

    def close_issue(self, number: int) -> None:
        self._api("-X", "PATCH", f"{self.root}/issues/{number}", "-f", "state=closed",
                  "-f", "state_reason=completed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--now", required=True, type=parse_time,
                        help="The current moment as an ISO 8601 time with a zone.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                        help="owner/name, by default GITHUB_REPOSITORY.")
    args = parser.parse_args()
    if not args.repo:
        parser.error("--repo or GITHUB_REPOSITORY is required")
    actions = run(GitHub(args.repo), args.now, count_red())
    print("; ".join(actions) or "no change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
