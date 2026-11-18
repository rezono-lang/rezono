"""Export compiled dependencies from Feldera's stock empty-program build."""

import argparse
import json
import re
import sys
import tarfile
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath

FELDERA_CRATES = PurePosixPath("/home/ubuntu/feldera/crates")
CARGO_HOME = PurePosixPath("/home/ubuntu/.cargo")
SAFE_NAME = re.compile(r"[A-Za-z0-9_-]+")
HASHED_UNIT = re.compile(r"(?P<name>[A-Za-z0-9_-]+)-[0-9a-f]{16}")
DEP_OUTPUT = re.compile(r"(?P<name>[A-Za-z0-9_]+)-[0-9a-f]{16}\.(?:d|rmeta|rlib|a|so)")


def locked_packages(lock: Path, metadata: Path) -> dict[str, str]:
    packages = {}
    for package in tomllib.loads(lock.read_text(encoding="utf-8"))["package"]:
        identity = package["name"], package["version"], package.get("source")
        packages[identity] = package

    trusted = {}
    for package in json.loads(metadata.read_bytes())["packages"]:
        name, version, source = package["name"], package["version"], package["source"]
        manifest = PurePosixPath(package["manifest_path"])
        if not SAFE_NAME.fullmatch(name) or name.startswith("feldera_pipe_"):
            continue
        entry = packages.get((name, version, source))
        if entry is None or not manifest.is_absolute() or ".." in manifest.parts:
            continue
        if source is None:
            approved = manifest.is_relative_to(FELDERA_CRATES)
        elif source.startswith("registry+"):
            checksum = entry.get("checksum", "")
            approved = (manifest.is_relative_to(CARGO_HOME / "registry" / "src")
                        and re.fullmatch(r"[0-9a-f]{64}", checksum))
        elif source.startswith("git+"):
            approved = (manifest.is_relative_to(CARGO_HOME / "git" / "checkouts")
                        and re.fullmatch(r"[0-9a-f]{40}", source.rsplit("#", 1)[-1]))
        else:
            approved = False
        if approved:
            trusted[package["id"]] = name
    return trusted


def compiled_packages(messages: Path, trusted: dict[str, str]) -> tuple[set[str], set[str]]:
    packages = set()
    libraries = set()
    completed = False
    for line in messages.read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        message = json.loads(line)
        if message["reason"] == "build-finished":
            completed = message["success"] is True
        if message["reason"] != "compiler-artifact" or message["package_id"] not in trusted:
            continue
        packages.add(trusted[message["package_id"]])
        target = message["target"]
        if set(target["kind"]) & {"lib", "rlib", "staticlib", "dylib", "cdylib", "proc-macro"}:
            libraries.add(target["name"])
    if not completed or not packages or not libraries:
        raise ValueError("successful Cargo dependency artifacts are required")
    return packages, libraries


def allowed_member(
    member: tarfile.TarInfo, packages: set[str] | None, libraries: set[str] | None,
) -> bool:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or "\\" in member.name:
        raise ValueError(f"Unexpected archive path: {member.name}")
    if not (member.isfile() or member.isdir()):
        return False
    if not path.parts or any(part.startswith(("feldera_pipe_", "libfeldera_pipe_")) for part in path.parts):
        return False
    category = path.parts[0]
    if category == "deps" and len(path.parts) == 2 and member.isfile():
        without_prefix = path.name.removeprefix("lib")
        for name in (path.name, without_prefix):
            matched = DEP_OUTPUT.fullmatch(name)
            if matched is not None and (libraries is None or matched["name"] in libraries):
                return True
        return False
    if category in {"build", ".fingerprint"} and len(path.parts) >= 2:
        matched = HASHED_UNIT.fullmatch(path.parts[1])
        return matched is not None and (packages is None or matched["name"] in packages)
    return False


def transfer(packages: set[str] | None = None, libraries: set[str] | None = None) -> None:
    seen = set()
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as original:
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as archive:
            for member in original:
                if not allowed_member(member, packages, libraries):
                    if packages is None:
                        raise ValueError(f"Unexpected dependency artifact: {member.name}")
                    continue
                member.name = str(PurePosixPath(member.name))
                member.mode &= 0o755
                member.pax_headers = {}
                if member.name in seen:
                    raise ValueError(f"Duplicate dependency artifact: {member.name}")
                seen.add(member.name)
                data = original.extractfile(member) if member.isfile() else None
                archive.addfile(member, data)
            if not any(name.startswith("deps/libdbsp-") and name.endswith(".rlib") for name in seen):
                raise ValueError("The stock Feldera build produced no cacheable DBSP library")
    print(f"Verified {len(seen)} Feldera dependency entries", file=sys.stderr)


def summarize_activity() -> None:
    counts = Counter()
    for line in sys.stdin:
        if not line.startswith("{"):
            continue
        message = json.loads(line)
        if message["reason"] != "compiler-artifact":
            continue
        target = message["target"]["name"]
        manifest = PurePosixPath(message["manifest_path"])
        if re.fullmatch(r"feldera_pipe_operator_[0-9a-f]{16}", target):
            kind = "generated_operators"
        elif target == "dbsp" and manifest.is_relative_to(FELDERA_CRATES):
            kind = "dbsp"
        elif manifest.is_relative_to(FELDERA_CRATES) or manifest.is_relative_to(CARGO_HOME):
            kind = "other_dependencies"
        else:
            continue
        counts[f"{kind}_{'fresh' if message['fresh'] else 'compiled'}"] += 1
    if not counts:
        raise ValueError("The comparison emitted no Cargo activity")
    print(json.dumps(dict(sorted(counts.items()))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="operation", required=True)
    produce = subcommands.add_parser("export")
    produce.add_argument("lock", type=Path)
    produce.add_argument("metadata", type=Path)
    produce.add_argument("messages", type=Path)
    subcommands.add_parser("verify")
    subcommands.add_parser("activity")
    options = parser.parse_args()
    if options.operation == "export":
        transfer(*compiled_packages(options.messages, locked_packages(options.lock, options.metadata)))
    elif options.operation == "verify":
        transfer()
    else:
        summarize_activity()
