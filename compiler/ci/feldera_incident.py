"""Report confirmed main-branch oracle disagreements, including their last green revision."""

import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from verify_feldera_run import LIVE_COMPILER_TESTS, PLATFORM_TEST, check_cases


WORKFLOW = ".github/workflows/feldera-oracle.yml"
COMPARISONS = LIVE_COMPILER_TESTS | {
    PLATFORM_TEST,
    "examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors",
    "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch",
}
SQL_ERROR = re.compile(r'RuntimeError:\s*\{\s*"sql_compilation":\s*\{\s*"exit_code":\s*[1-9]\d*,\s*"messages":\s*\[')


def sql_disagreement(failure):
    # Older pytest artifacts truncate the message attribute. The exception line in
    # the traceback still contains the first complete diagnostic from the SQL compiler.
    for line in [failure.get("message", ""), *(failure.text or "").splitlines()]:
        match = SQL_ERROR.match(re.sub(r"^E\s+", "", line).lstrip())
        if not match:
            continue
        entries = match.string[match.end():].lstrip()
        while entries.startswith("{"):
            try:
                diagnostic, end = json.JSONDecoder().raw_decode(entries)
            except ValueError:
                break
            if (isinstance(diagnostic, dict) and diagnostic.get("warning") is False
                    and isinstance(diagnostic.get("start_line_number"), int)
                    and diagnostic["start_line_number"] > 0 and diagnostic.get("error_type")):
                return True
            entries = entries[end:].lstrip()
            if not entries.startswith(","):
                break
            entries = entries[1:].lstrip()
    return False


def disagreements(selected, xml):
    nodes = selected.splitlines()
    if not COMPARISONS.issubset(node.partition("[")[0] for node in nodes):
        return []
    root = ET.fromstring(xml)
    try:
        problems = check_cases(nodes, root)
    except ValueError:
        return []
    if any(not p.startswith("failure: ") for p in problems):
        return []
    differences = []
    for case in root.iter("testcase"):
        failure = case.find("failure")
        if failure is None:
            continue
        if (failure.get("message", "").startswith("feldera.OracleMismatch: ")
                or sql_disagreement(failure)):
            differences.append(case.attrib["name"])
    return sorted(differences)


def project_author(item):
    return (item["user"]["login"] == "github-actions[bot]"
            or item["author_association"] in {"OWNER", "MEMBER", "COLLABORATOR"})


class GitHub:
    """Read workflow evidence and update the project's oracle issue using the Actions token."""

    def __init__(self, repo):
        self.path = f"repos/{repo}/"
        self.url = f"https://github.com/{repo}"

    def api(self, path, *, method="GET", body=None, pages=False):
        args = ["gh", "api", "--method", method, self.path + path]
        if pages:
            args += ["--paginate", "--slurp"]
        if body is not None:
            args += ["--input", "-"]
        data = subprocess.check_output(args, input=None if body is None else json.dumps(body).encode())
        return json.loads(data)

    def runs(self):
        pages = self.api("actions/workflows/feldera-oracle.yml/runs?branch=main&event=push&per_page=100", pages=True)
        return [run for page in pages for run in page["workflow_runs"]]

    def cases(self, run):
        items = self.api(f"actions/runs/{run['id']}/artifacts?name=feldera-oracle")["artifacts"]
        artifact = next((a for a in items if a["name"] == "feldera-oracle" and not a["expired"]), None)
        if not artifact:
            return []
        data = subprocess.check_output(["gh", "api", "--allow-escape-sequences",
                                        self.path + f"actions/artifacts/{artifact['id']}/zip"])
        with ZipFile(io.BytesIO(data)) as archive:
            if not {"collected.txt", "results.xml"} <= set(archive.namelist()):
                return []
            return disagreements(archive.read("collected.txt").decode(), archive.read("results.xml"))

    def open_issue(self, marker):
        for page in self.api("issues?state=open&per_page=100", pages=True):
            for issue in page:
                if ("pull_request" not in issue and marker in (issue["body"] or "").splitlines()
                        and project_author(issue)):
                    return issue
        return None

    def create(self, body):
        return self.api("issues", method="POST", body={"title": "Feldera oracle disagrees on main", "body": body})

    def record(self, number, marker, detail):
        endpoint = f"issues/{number}/comments"
        for page in self.api(endpoint + "?per_page=100", pages=True):
            if any(project_author(comment) and marker in comment["body"].splitlines() for comment in page):
                return
        self.api(endpoint, method="POST", body={"body": detail + "\n" + marker})



def report(hub, current, ancestry):
    """Use first-parent main order. The workflow concurrency group serializes issue updates."""
    if current["event"] != "push" or current["head_branch"] != "main" or current["path"] != WORKFLOW:
        return
    sha = current["head_sha"]
    if not ancestry or ancestry[0] != sha or current["conclusion"] not in {None, "failure"}:
        return
    failures = hub.cases(current)
    if not failures:
        return
    rank = {commit: i for i, commit in enumerate(ancestry)}
    history = [r for r in hub.runs() if r["event"] == "push" and r["head_branch"] == "main"
               and r["path"] == WORKFLOW and r["head_sha"] in rank and r["status"] == "completed"
               and r["id"] < current["id"]]
    history.sort(key=lambda r: (rank[r["head_sha"]], -r["id"]))
    green = next((r["head_sha"] for r in history if r["conclusion"] == "success" and r["head_sha"] != sha), None)
    marker = f"<!-- rezono-feldera-main: {green or 'no-green'} -->"
    issue = hub.open_issue(marker)
    run_marker = f"<!-- feldera-run: {current['id']} -->"
    detail = f"- [Run {current['id']}]({hub.url}/actions/runs/{current['id']}) at `{sha}`"
    if issue:
        if run_marker not in issue["body"].splitlines():
            hub.record(issue["number"], run_marker, detail)
        return
    first = current
    for run in reversed(history):
        if green and rank[run["head_sha"]] >= rank[green]:
            continue
        if run["conclusion"] == "failure" and hub.cases(run):
            first = run
            break
    rollback = f"The last green main revision and rollback target is `{green}`." if green else (
        "No green Feldera run on main precedes this disagreement. There is no verified rollback target.")
    body = (f"{marker}\nFirst confirmed red main revision: `{first['head_sha']}` "
            f"([run {first['id']}]({hub.url}/actions/runs/{first['id']})).\n\n{rollback}\n\n"
            "Treat the discrepancy as a Rezono defect unless checking the rule establishes an oracle error.\n\n"
            f"{detail}\n{run_marker}\n")
    hub.create(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    classify = commands.add_parser("classify")
    classify.add_argument("directory", type=Path)
    publish = commands.add_parser("report")
    publish.add_argument("--run", type=int, default=os.environ.get("GITHUB_RUN_ID"))
    args = parser.parse_args()
    if args.command == "classify":
        selected, xml = args.directory / "collected.txt", args.directory / "results.xml"
        try:
            found = disagreements(selected.read_text(encoding="utf-8"), xml.read_bytes())
        except (FileNotFoundError, ET.ParseError):
            found = []
        print("confirmed=" + ("true" if found else "false"))
    else:
        hub = GitHub(os.environ["GITHUB_REPOSITORY"])
        current = hub.api(f"actions/runs/{args.run}")
        sha = current["head_sha"]
        ancestry = subprocess.check_output(["git", "rev-list", "--first-parent", sha], text=True).splitlines()
        report(hub, current, ancestry)


if __name__ == "__main__":
    main()
