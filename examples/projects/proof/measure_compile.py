"""Measure how long Feldera takes to compile a pipeline (docs/ci.md). Not a test; run by hand:

    FELDERA_URL=http://localhost:8080 python examples/projects/proof/measure_compile.py

Cases: the projects pack; the same SQL under another name (cache?); the same SQL plus one view
(incremental?); and a pack with ten times as many kinds (ten renamed copies of projects).
"""

import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "compiler" / "tests"))
from feldera import call, deploy  # noqa: E402
from support import compile_dir  # noqa: E402


def program(pack_dir: Path, tmp: Path) -> str:
    files = compile_dir(pack_dir, tmp)
    return files["engine/tables.sql"] + files["engine/integrity.sql"]


def tenfold(tmp: Path) -> Path:
    src, dst = REPO / "examples" / "projects", tmp / "tenfold"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("expected", "facts", "labels"))
    text = (src / "schema" / "projects.yaml").read_text()
    head, classes = text.split("\nenums:\n")[0], "\nenums:\n" + text.split("\nenums:\n")[1]
    names = ["TaskStatus", "Project", "BudgetLine", "Milestone", "Task", "Dependency"]
    body = []
    for i in range(10):
        part = classes
        for n in names:
            part = re.sub(rf"\b{n}\b", f"{n}{i}", part)
        body.append(part.replace("\nenums:\n", "\n").replace("\nclasses:\n", "\n"))
    enums = "".join(b.split("\n  Project")[0] for b in body)
    rest = "".join("\n  Project" + b.split("\n  Project", 1)[1] for b in body)
    (dst / "schema" / "projects.yaml").write_text(head + "\nenums:" + enums + "\nclasses:" + rest)
    (dst / "channels.yaml").write_text("kinds: {}\n")
    return dst


def compile_time(name: str, sql: str) -> float:
    secs = deploy(name, sql)
    call("POST", f"/v0/pipelines/{name}/stop?force=true")
    return secs


def main():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        small = program(REPO / "examples" / "projects", tmp / "small")
        large = program(tenfold(tmp), tmp / "large")
        stamp = str(int(time.time()))
        extra = "\nCREATE MATERIALIZED VIEW extra_view AS SELECT id FROM task WHERE id <> 'x';\n"
        cases = [("small", small), ("small-same-sql-new-name", small), ("small-plus-one-view", small + extra),
                 ("large-10x", large), ("large-10x-same-sql-new-name", large)]
        for label, sql in cases:
            views = sql.count("CREATE MATERIALIZED VIEW")
            secs = compile_time(f"measure-{label}-{stamp}", sql)
            print(f"{label}: {views} views, {len(sql.splitlines())} lines SQL, {secs:.0f} s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
