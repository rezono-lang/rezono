"""Select and verify the shared role-publication proof."""

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from xml.etree import ElementTree

from components import ROOT, component_owner, discover_components, git_output, shared_readers


READ_TREES = (
    "admission/", "canon/", "checker/", "compiler/", "contracts/", "edge/gate/", "edge/publisher/",
    "examples/platform/", "publication/", "rezono/", "tools/mcp/", "tools/repl/",
    "packs/std-access/", "packs/std-decision/", "packs/std-explain/", "packs/std-identity/",
    "packs/std-order/", "packs/std-part/", "packs/std-time/",
    ".github/workflows/python-environment/",
)
READ_FILES = {
    ".node-version", ".github/workflows/ci.yml", "requirements/.python-version", "requirements/dev.txt",
    "scripts/components.py", "scripts/role_publication_ci.py", "scripts/test_role_publication_ci.py",
    "viewer/src/lib/canon.ts",
}
PLATFORM_TEST = "examples/platform/proof_cases/test_role_publication_fixture.py::test_role_publication_fixture"
REPL_TEST = "tools/repl/test/publication.accept.ts"
MCP_TEST = "tools/mcp/test/publication.accept.ts"
MCP_REPLAY = "tools/mcp/src/replay.ts"
PACK, MANIFEST = "platform-core", "m-1"
ROLES = ("elm", "reed")
NODE_CASES = {f"published {role} session replays bytewise and sees only its own rows and grounds" for role in ROLES}
NODE_CASES.update(f"{role} sees only its published rows and replays the shared answers" for role in ROLES)


def affected(paths: list[str], folders: set[str]) -> bool:
    for path in paths:
        if path in READ_FILES or path.startswith(READ_TREES):
            return True
        if component_owner(path, folders) is None and shared_readers(path) is None:
            return True
    return False


def required(event: str, base: str) -> bool:
    """Select this proof from both candidate trees without changing the component matrix."""
    if event not in {"pull_request", "merge_group"}:
        return False
    try:
        start = git_output(ROOT, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").decode().strip()
        git_output(ROOT, "merge-base", "--is-ancestor", start, "HEAD")
        raw = git_output(ROOT, "diff", "--no-renames", "--name-only", "-z", start, "HEAD", "--")
    except (OSError, subprocess.CalledProcessError):
        print("Candidate range unavailable. Require the role-publication proof.", file=sys.stderr)
        return True
    paths = [os.fsdecode(path) for path in raw.split(b"\0") if path]
    folders = {component.folder for component in discover_components(ROOT, keep_invalid_node=True)}
    return affected(paths, folders)


def passing_cases(report: Path, expected: set[str]) -> None:
    root = ElementTree.parse(report).getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError(f"Invalid JUnit report {report.name}")
    cases = list(root.iter("testcase"))
    actual = Counter(case.get("name", "") for case in cases)
    if actual != Counter(expected):
        raise ValueError(f"{report.name} case identities differ: expected {sorted(expected)}, found {sorted(actual.items())}")
    for case in cases:
        for verdict in ("error", "failure", "skipped"):
            item = case.find(verdict)
            if item is not None:
                raise ValueError(f"{report.name} {case.get('name')}: {verdict} {item.get('message', '')}")


def platform_stores(work: Path) -> tuple[Path, Path]:
    import pytest
    from rezono_publisher import batch, publish, store

    sys.path.insert(0, str(ROOT))

    class RequiredCase:
        def pytest_collection_finish(self, session):
            if [item.nodeid for item in session.items] != [PLATFORM_TEST]:
                pytest.exit("The exact platform publication fixture must be collected once")
            if session.items[0].get_closest_marker("xfail") is not None:
                pytest.exit("The required platform publication fixture is marked xfail")

    report = work / "platform.xml"
    runs = work / "pytest"
    result = pytest.main(["--rootdir", str(ROOT), "--basetemp", str(runs), "--junitxml", str(report),
                          "-q", "-o", "addopts=", "-o", "junit_family=xunit2", PLATFORM_TEST],
                         plugins=[RequiredCase()])
    if result != pytest.ExitCode.OK:
        raise ValueError(f"The platform publication fixture failed with pytest status {result}")
    passing_cases(report, {"test_role_publication_fixture"})
    publications = [case / "publication" for case in runs.iterdir() if case.is_dir()
                    and not case.is_symlink() and (case / "publication").is_dir()]
    if len(publications) != 1:
        raise ValueError(f"Expected one FileStore from the platform fixture, got {len(publications)}")
    initial_path, = publications
    retained_path = initial_path.with_name("second-publication")
    if not retained_path.is_dir():
        raise ValueError("The platform fixture did not produce its replica FileStore")
    initial, retained = store.FileStore(initial_path), store.FileStore(retained_path)
    manifest_key = f"{PACK}/manifests/{MANIFEST}.json"
    original = initial.get(manifest_key)
    if not original or retained.get(manifest_key) != original:
        raise ValueError("The two publisher FileStores do not start at the same pinned publication")
    pack = initial_path.parent / "inputs/examples/platform"
    epoch = batch.epoch(pack, epoch=2, knowledge_time="2026-01-02T00:00:00Z",
                        sources=[("rules", "retained-role-publication-fixture")])
    newer = publish.publish(epoch, retained, {role: "may_read" for role in ROLES})
    if (newer["id"] != "m-2" or publish.newest_main(retained, PACK) != newer
            or publish.newest_main(initial, PACK)["id"] != MANIFEST or retained.get(manifest_key) != original):
        raise ValueError("The publisher did not preserve m-1 under the newer retained-store head")
    return initial_path, retained_path


def node_proof(work: Path, store: Path, retained: Path) -> None:
    report = work / "node.xml"
    env = {**os.environ, "REZONO_REPL_TEST_STORE": str(store), "REZONO_REPL_RETAINED_STORE": str(retained)}
    subprocess.run(["node", "--test", "--test-reporter=junit", f"--test-reporter-destination={report}",
                    REPL_TEST, MCP_TEST], cwd=ROOT, check=True, timeout=100, env=env)
    passing_cases(report, NODE_CASES)


def stdio_proof(work: Path, store: Path, retained: Path, role: str, peer: str) -> None:
    plan_file, recording = work / f"{role}-calls.json", work / f"{role}-recording.json"
    calls = [
        {"tool": "ask", "args": {"pack": PACK, "text": "ask Request where request.cores > 0 show request.cores"}},
        *({"tool": "search", "args": {"pack": PACK, "kind": "request", "prefix": prefix}}
          for prefix in (role, peer, "unused")),
        *({"tool": "grounds", "args": {"pack": PACK, "target": ["tenant_capacity_fits", actor, key, f"{actor}-quota"]}}
          for actor, key in ((role, f"{role}-request"), (peer, f"{peer}-request"), (role, "unused-request"))),
    ]
    plan_file.write_text(json.dumps({"pack": PACK, "calls": calls}), encoding="utf-8")
    process = ["node", MCP_REPLAY]
    subprocess.run([*process, "record", str(plan_file), str(recording), "--store", store.as_uri(), "--role", role],
                   cwd=ROOT, check=True, timeout=45)
    value = json.loads(recording.read_text(encoding="utf-8"))
    results = value["calls"]
    if (value["format"], value["pack"], value["manifest"], value["role"]) != ("rezono-mcp.recording/1", PACK, MANIFEST, role):
        raise ValueError(f"Wrong recorded publication or role for {role}")
    if [{field: call[field] for field in ("tool", "args")} for call in results] != calls:
        raise ValueError(f"Missing or changed stdio calls for {role}")
    ask, search, foreign_search, empty_search, grounds, foreign_grounds, missing_grounds = results
    if [item["error"] for item in results] != [False, False, False, False, False, True, True]:
        raise ValueError(f"Wrong stdio result polarity for {role}")
    own = {f"{role}-request", f"{role}-second-request"}
    if not all(item in ask["text"] for item in own) or f"{peer}-" in ask["text"]:
        raise ValueError(f"Unexpected ask visibility for {role}")
    if sorted(search["text"].splitlines()) != sorted(own) or foreign_search["text"] != "" or empty_search["text"] != "":
        raise ValueError(f"Unexpected search visibility for {role}")
    refusal = "error: not found (or outside your view)"
    if "tenant_capacity_fits" not in grounds["text"] or foreign_grounds["text"] != refusal or missing_grounds["text"] != refusal:
        raise ValueError(f"Unexpected grounds visibility for {role}")
    for publication in (store, retained):
        subprocess.run([*process, "replay", str(recording), "--store", publication.as_uri()],
                       cwd=ROOT, check=True, timeout=45)


def run() -> None:
    os.environ.pop("PYTEST_ADDOPTS", None)
    for name in ("bundle", "explain", "manifest", "proof"):
        contract = ROOT / "contracts/typescript/generated" / f"{name}.ts"
        if not contract.is_file() or contract.stat().st_size == 0:
            raise ValueError(f"The pinned setup did not generate the {name} contract types")
    with tempfile.TemporaryDirectory(prefix="rezono-role-publication-") as directory:
        work = Path(directory).resolve()
        store, retained = platform_stores(work)
        node_proof(work, store, retained)
        for role, peer in ((ROLES[0], ROLES[1]), (ROLES[1], ROLES[0])):
            stdio_proof(work, store, retained, role, peer)
    print("Verified one platform fixture, four current/retained Node cases and two current/retained stdio replays.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    select.add_argument("--base", required=True)
    commands.add_parser("run")
    args = parser.parse_args()
    if args.command == "select":
        print("required=" + ("true" if required(os.environ.get("GITHUB_EVENT_NAME", ""), args.base) else "false"))
    else:
        run()


if __name__ == "__main__":
    main()
