"""Check tracked dependency manifests against Dependabot configuration read as JSON."""

from collections import defaultdict
from fnmatch import fnmatchcase
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = {
    "pyproject.toml": "pip",
    "requirements.txt": "pip",
    "package.json": "npm",
    "go.mod": "gomod",
    "Project.toml": "julia",
    "JuliaProject.toml": "julia",
    "action.yml": "github-actions",
    "action.yaml": "github-actions",
}


def required_directories(files):
    required = defaultdict(set)
    for file in files:
        path = PurePosixPath(file)
        if "fixtures" in path.parts:
            continue

        ecosystem = MANIFESTS.get(path.name)
        if path.parts[0] == "requirements" and path.suffix in {".in", ".txt"}:
            ecosystem = "pip"
        if path.parent == PurePosixPath(".github/workflows") and path.suffix in {".yml", ".yaml"}:
            required["github-actions"].add("/")
        if "dockerfile" in path.name.lower() or "containerfile" in path.name.lower():
            source = (ROOT / file).read_text(encoding="utf-8")
            if re.search(r"^FROM\s", source, re.IGNORECASE | re.MULTILINE):
                ecosystem = "docker"
        if ecosystem:
            required[ecosystem].add("/" + "/".join(path.parts[:-1]))
    return required


def matches(directory, pattern):
    parts = directory.split("/")
    pattern_parts = pattern.split("/")
    return len(parts) == len(pattern_parts) and all(
        fnmatchcase(part, rule) for part, rule in zip(parts, pattern_parts)
    )


def check(config, files):
    assert config["version"] == 2
    configured = {}
    for update in config["updates"]:
        ecosystem = update["package-ecosystem"]
        assert ecosystem not in configured, f"{ecosystem}: expected one update entry"
        assert ("directory" in update) != ("directories" in update), f"{ecosystem}: supply one location key"
        locations = [update["directory"]] if "directory" in update else update["directories"]
        assert locations and len(set(locations)) == len(locations), f"{ecosystem}: missing or duplicate locations"
        assert "target-branch" not in update, f"{ecosystem}: update the default branch"
        assert update["schedule"]["interval"] == "weekly", f"{ecosystem}: version updates must run weekly"
        groups = list(update["groups"].values())
        assert len(groups) == 1 and groups[0]["patterns"] == ["*"], f"{ecosystem}: expected one version group"
        assert groups[0]["applies-to"] == "version-updates", f"{ecosystem}: keep security updates separate"
        configured[ecosystem] = set(locations)

    required = required_directories(files)
    missing = [
        f"{ecosystem} {directory}"
        for ecosystem, directories in sorted(required.items())
        for directory in sorted(directories)
        if not any(matches(directory, pattern) for pattern in configured.get(ecosystem, ()))
    ]
    assert not missing, "Dependabot is missing manifest directories: " + ", ".join(missing)
    print("Dependabot manifest coverage: " + ", ".join(
        f"{ecosystem} {len(directories)}" for ecosystem, directories in sorted(required.items())
    ))


if __name__ == "__main__":
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\x00")
    check(json.load(sys.stdin), filter(None, tracked))
