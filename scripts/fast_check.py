"""Run the assigned test and a deterministic sample of canonical test vectors."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import tempfile
import xml.etree.ElementTree as ET

from components import discover_python_packages
from red_list import ROOT, extract_red_tests_from_source


def resolve(task: str, base_revision: str = "origin/main") -> str:
    relpath = task.split("--", 1)[0]
    path = (ROOT / relpath).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError("unknown test file")
    base = subprocess.run(["git", "show", f"{base_revision}:{relpath}"], cwd=ROOT,
                          capture_output=True, encoding="utf-8")
    for source in (path.read_text(encoding="utf-8"), base.stdout):
        for red in extract_red_tests_from_source(source, relpath, []):
            if red.id == task:
                return red.nodeid
    raise ValueError("unknown task; fetch origin/main before starting")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task")
    parser.add_argument("--base", default="origin/main", help="Git revision before the task changed")
    args = parser.parse_args()
    log = ROOT / ".fast-check.log"
    start = time.monotonic()
    try:
        node = resolve(args.task, args.base)
        vectors = json.loads((ROOT / "contracts/fixtures/canon/vectors.json").read_text(encoding="utf-8"))
        pool = [f"canon/tests/test_vectors.py::test_{kind}[{v['name']}]"
                for kind in ("valid", "invalid") for v in vectors[kind]
                if v.get("only", "python") == "python"]
        sample = sorted(pool, key=lambda case: hashlib.sha256(
            (args.task + "\0" + case).encode()).digest())[:3]
        paths = [str(ROOT / folder) for folder in discover_python_packages()]
        env = os.environ.copy()
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(paths)
        print(f"Task: {node}", flush=True)
        with tempfile.TemporaryDirectory() as directory, log.open("w", encoding="utf-8") as output:
            report = f"{directory}/results.xml"
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--runxfail", f"--junitxml={report}",
                                     node, *sample], cwd=ROOT, stdout=output,
                                    stderr=subprocess.STDOUT, env=env, timeout=115)
            if result.returncode:
                raise ValueError(f"pytest exited with {result.returncode}")
            tests = ET.parse(report).findall(".//testcase")
            if len(tests) <= len(sample) or any(test.find("skipped") is not None for test in tests):
                raise ValueError("an assigned or sampled test did not run")
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        message = f"ERROR {exc}"
        with log.open("a", encoding="utf-8") as output:
            print(message, file=output)
        print(message)
        return 1
    print(f"Passed task and {len(sample)} sampled tests in {time.monotonic() - start:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
