import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# The example tests reuse the compiler's test helpers (compile, DuckDB, Feldera client).
sys.path.insert(0, str(ROOT / "compiler" / "tests"))

collect_ignore = []
if (ROOT / "blocked").is_dir():
    for _entry in sorted((ROOT / "blocked").iterdir()):
        if _entry.is_file():
            _target = _entry.read_text(encoding="utf-8").split(":", 1)[0].strip()
            if _target.startswith("examples/"):
                collect_ignore.append(_target[len("examples/"):])
collect_ignore_glob = list(collect_ignore)



