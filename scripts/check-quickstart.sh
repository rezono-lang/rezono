#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY' > "$RUNNER_TEMP/quickstart.sh"
import pathlib, re
blocks = re.findall(r"^\x60{3}bash\n(.+?)^\x60{3}$", pathlib.Path("README.md").read_text(), re.M | re.S)
if len(blocks) != 1:
    raise SystemExit("Expected one Bash quickstart in README.md")
print(blocks[0])
PY
bash -euo pipefail "$RUNNER_TEMP/quickstart.sh"
