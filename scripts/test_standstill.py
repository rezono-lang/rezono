"""Cases for the standstill alert with fixed times and an in-memory GitHub."""
import datetime as dt
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import standstill
from standstill import count_red, parse_time, run

NOW = parse_time("2026-11-19T08:00:00Z")


def at(hours_ago: float) -> str:
    return standstill.format_time(NOW - dt.timedelta(hours=hours_ago))


def pull(ref: str, opened: str, merged: str | None = None) -> dict:
    return {"head": {"ref": ref}, "created_at": opened, "merged_at": merged,
            "closed_at": merged, "updated_at": merged or opened}


class FakeGitHub:
    def __init__(self, pulls: list[dict]):
        self.all_pulls = pulls
        self.issues: list[dict] = []
        self.labels: set[str] = set()
        self.clock = NOW

    def pulls(self, state, sort, page):
        chosen = [p for p in self.all_pulls if state == "all" or p["closed_at"]]
        key = "created_at" if sort == "created" else "updated_at"
        chosen.sort(key=lambda p: parse_time(p[key]), reverse=True)
        start = (page - 1) * standstill.PER_PAGE
        return chosen[start:start + standstill.PER_PAGE]

    def open_issues(self):
        return [i for i in self.issues if i["state"] == "open" and standstill.LABEL in i["labels"]]

    def ensure_label(self):
        self.labels.add(standstill.LABEL)

    def create_issue(self, title, body):
        assert standstill.LABEL in self.labels, "label must exist before the issue"
        number = len(self.issues) + 1
        self.issues.append({"number": number, "title": title, "body": body, "state": "open",
                            "labels": [standstill.LABEL],
                            "created_at": standstill.format_time(self.clock)})
        return number

    def close_issue(self, number):
        self.issues[number - 1]["state"] = "closed"


def check(name, condition, detail=""):
    if not condition:
        raise AssertionError(f"{name}: {detail}")
    print(f"PASS {name}")


def main():
    # Three hours quiet with red tests opens one issue, and a second run adds none.
    github = FakeGitHub([pull("fix/a", at(5), at(3)), pull("fix/b", at(3.5))])
    first = run(github, NOW, 4)
    second = run(github, NOW + dt.timedelta(hours=1), 4)
    issue = github.issues[0] if github.issues else {}
    check("three hours quiet with red tests opens one issue",
          first == ["opened #1"] and second == [] and len(github.open_issues()) == 1,
          f"{first} {second} {github.issues}")
    check("the issue names only the two moments and the count",
          issue.get("body") == (f"Last pull request opened: {at(3.5)}\n"
                                f"Last pull request merged: {at(3)}\n"
                                "Red tests not marked later: 4\n"), issue.get("body"))

    # A new pull request after the issue closes it.
    github.all_pulls.append(pull("fix/c", standstill.format_time(NOW + dt.timedelta(minutes=30))))
    closed = run(github, NOW + dt.timedelta(hours=1), 4)
    check("a new pull request after the issue closes it",
          closed == ["closed #1"] and not github.open_issues(), f"{closed} {github.issues}")

    # A merge after the issue closes it as well.
    github = FakeGitHub([pull("fix/a", at(5), at(3))])
    run(github, NOW, 4)
    github.all_pulls[0] = pull("fix/a", at(5), standstill.format_time(NOW + dt.timedelta(minutes=5)))
    closed = run(github, NOW + dt.timedelta(minutes=10), 4)
    check("a merge after the issue closes it", closed == ["closed #1"], f"{closed}")

    github = FakeGitHub([pull("fix/a", at(5), at(3))])
    actions = run(github, NOW, 0)
    check("three hours quiet without red tests does nothing",
          actions == [] and not github.issues and not github.labels, f"{actions} {github.issues}")

    github = FakeGitHub([pull("fix/a", at(4), at(1))])
    actions = run(github, NOW, 4)
    check("one hour quiet does nothing", actions == [] and not github.issues, f"{actions}")

    # Dependabot neither keeps work alive nor closes the issue.
    github = FakeGitHub([pull("fix/a", at(5), at(3)),
                         pull("dependabot/pip/requests-2.33.0", at(0.5), at(0.25))])
    opened = run(github, NOW, 4)
    github.all_pulls.append(pull("dependabot/github_actions/checkout",
                                 standstill.format_time(NOW + dt.timedelta(minutes=20))))
    kept = run(github, NOW + dt.timedelta(hours=1), 4)
    check("a Dependabot pull request does not count",
          opened == ["opened #1"] and kept == [] and len(github.open_issues()) == 1,
          f"{opened} {kept}")

    # Enough Dependabot pull requests to fill the first page still leave the older one found.
    bots = [pull(f"dependabot/npm_and_yarn/update-{n}", at(0.5), at(0.25))
            for n in range(standstill.PER_PAGE + 5)]
    github = FakeGitHub([pull("fix/a", at(5), at(3)), *bots])
    opened = run(github, NOW, 4)
    check("Dependabot pull requests on the first page are skipped",
          opened == ["opened #1"] and f"opened: {at(5)}" in github.issues[0]["body"]
          and f"merged: {at(3)}" in github.issues[0]["body"], f"{opened}")

    check("the limit is two hours", standstill.STANDSTILL_HOURS == 2)

    # The red count follows red_list: a reason that starts with the later mark is later.
    with tempfile.TemporaryDirectory() as tmp:
        tests = Path(tmp, "demo", "tests")
        tests.mkdir(parents=True)
        Path(tmp, "demo", "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
        tests.joinpath("test_demo.py").write_text(
            "import pytest\n\n"
            "@pytest.mark.xfail(strict=True, reason='later: waits for a future feature')\n"
            "def test_later():\n    pass\n\n"
            "@pytest.mark.xfail(strict=True, reason='missing rule')\n"
            "def test_red():\n    pass\n\n"
            "@pytest.mark.xfail(reason='not later: still red')\n"
            "def test_named_later():\n    pass\n",
            encoding="utf-8")
        red = count_red(Path(tmp))
        check("red tests not marked later are counted as red_list counts them", red == 2, f"{red}")


if __name__ == "__main__":
    main()
