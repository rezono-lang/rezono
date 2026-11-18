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


def check_keys(value, expected, label):
    assert isinstance(value, dict), f"{label}: expected a mapping"
    assert value.keys() == expected, f"{label}: expected keys {', '.join(sorted(expected))}"


def check(config, files):
    check_keys(config, {"version", "updates"}, "Dependabot configuration")
    assert type(config["version"]) is int and config["version"] == 2, "version must be the integer 2"
    updates = config["updates"]
    assert isinstance(updates, list) and updates, "updates must be a nonempty list"
    configured = {}
    for update in updates:
        assert isinstance(update, dict), "each update must be a mapping"
        location = "directory" if "directory" in update else "directories"
        check_keys(update, {"package-ecosystem", location, "schedule", "groups"}, "update entry")
        ecosystem = update["package-ecosystem"]
        assert isinstance(ecosystem, str) and ecosystem in {*MANIFESTS.values(), "docker"}, "unknown ecosystem"
        assert ecosystem not in configured, f"{ecosystem}: expected one update entry"
        locations = [update["directory"]] if location == "directory" else update["directories"]
        assert isinstance(locations, list) and locations, f"{ecosystem}: expected locations"
        assert all(isinstance(path, str) and path.startswith("/") for path in locations), f"{ecosystem}: invalid location"
        assert len(set(locations)) == len(locations), f"{ecosystem}: duplicate locations"
        check_keys(update["schedule"], {"interval"}, f"{ecosystem} schedule")
        assert update["schedule"]["interval"] == "weekly", f"{ecosystem}: version updates must run weekly"
        groups = update["groups"]
        assert isinstance(groups, dict) and len(groups) == 1, f"{ecosystem}: expected one version group"
        name, group = next(iter(groups.items()))
        assert isinstance(name, str) and re.fullmatch(r"[a-zA-Z](?:[a-zA-Z_|-]*[a-zA-Z])?", name), "invalid group name"
        check_keys(group, {"patterns", "applies-to"}, f"{ecosystem} group {name}")
        assert group["patterns"] == ["*"], f"{ecosystem}: expected one catch-all version group"
        assert group["applies-to"] == "version-updates", f"{ecosystem}: keep security updates separate"
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


def test_misspelled_group_is_rejected():
    config = {
        "version": 2,
        "updates": [{
            "package-ecosystem": "npm",
            "directory": "/",
            "schedule": {"interval": "weekly"},
            "groups": {"javascript": {"patterns": ["*"], "aplies-to": "version-updates"}},
        }],
    }
    try:
        check(config, ())
    except AssertionError as error:
        assert str(error).splitlines()[0] == "npm group javascript: expected keys applies-to, patterns"
    else:
        raise AssertionError("accepted a misspelled group key")


if __name__ == "__main__":
    test_misspelled_group_is_rejected()
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\x00")
    check(json.load(sys.stdin), filter(None, tracked))
