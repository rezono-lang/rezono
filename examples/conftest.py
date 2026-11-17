import sys
from pathlib import Path

# The example tests reuse the compiler's test helpers (compile, DuckDB, Feldera client).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compiler" / "tests"))
