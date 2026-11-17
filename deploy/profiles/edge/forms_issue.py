"""The issues of job `forms` of promote.yml (RV-K16 revised; decision A11): per pack one issue while its forms are
red, refused, in error or stopped (a timeout), and one for a run that failed before it named any pack.

  python deploy/profiles/edge/forms_issue.py

Reads the job's outcome from the environment: RESULT (`success` or `failure`), RESULTS (the job's output
`results`: pack -> {outcome, manifest}), RUN (the run's URL), SHA (the commit). An issue is opened once and
commented on after that, as the nightly alarm does (scripts/ci-tier.py nightly-issue, whose API calls this uses);
a pack's issue is closed with a comment once a run has its forms (`made`, `present`), and the general one once a
run names its packs again. Any other outcome (`off`, `none`, `overtaken`, `foreign`, `inexpressible`) leaves the
issue as it is: no run has the forms then. The standard library only.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path

BAD = frozenset({"red", "refused", "error", "running"})
GOOD = frozenset({"made", "present"})
GENERAL = "promote: forms failed"


def title(pack: str | None) -> str:
    return f"promote: forms of {pack} failed" if pack else GENERAL


def actions(result: str, results: dict) -> list[tuple[str, str | None, dict]]:
    """What to do: [(open|close, pack or None for the general issue, the pack's outcome)]. Pure."""
    if not results:
        return [("open", None, {"outcome": "error"})] if result == "failure" else []
    out = [("close", None, {"outcome": "named"})]
    for pack, r in sorted(results.items()):
        if r.get("outcome") in BAD:
            out.append(("open", pack, r))
        elif r.get("outcome") in GOOD:
            out.append(("close", pack, r))
    return out


def tier():
    path = Path(__file__).resolve().parents[3] / "scripts" / "ci-tier.py"
    spec = importlib.util.spec_from_file_location("ci_tier", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ci = tier()
    repo, run, sha = os.environ["GITHUB_REPOSITORY"], os.environ["RUN"], os.environ["SHA"]
    results = json.loads(os.environ.get("RESULTS") or "{}")
    todo = actions(os.environ.get("RESULT", ""), results)
    if not todo:
        return 0
    issues = ci.api(f"/repos/{repo}/issues?state=open&creator=github-actions%5Bbot%5D&per_page=100") or []
    for what, pack, r in todo:
        issue = next((i for i in issues if i["title"] == title(pack) and "pull_request" not in i), None)
        if what == "open":
            body = (f"The Reckon Data forms of {pack or 'the packs'} ({r.get('manifest', 'no manifest')}, commit {sha}) "
                    f"ended `{r['outcome']}` in {run}. The publication stands; the gate answers \"no Reckon Data form "
                    "yet\" for the roles without an index, and seal and lake passed the pack over.")
            if issue:
                ci.api(f"/repos/{repo}/issues/{issue['number']}/comments", {"body": body})
                ci.note(f"{pack or 'forms'}: commented on {issue['html_url']}.")
            else:
                issue = ci.api(f"/repos/{repo}/issues", {"title": title(pack), "body": body})
                ci.note(f"{pack or 'forms'}: opened {issue['html_url']}.")
        elif issue:
            ci.api(f"/repos/{repo}/issues/{issue['number']}/comments",
                   {"body": f"`{r['outcome']}` in {run} (commit {sha}): closed."})
            request = ci.request(f"/repos/{repo}/issues/{issue['number']}", {"state": "closed"})
            request.method = "PATCH"
            with urllib.request.urlopen(request, timeout=30):
                pass
            ci.note(f"{pack or 'forms'}: closed {issue['html_url']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
