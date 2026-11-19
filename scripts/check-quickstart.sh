#!/usr/bin/env bash
set -euo pipefail
# The quickstart is every bash block of README.md, in order, run in one shell: a later block uses the
# working directory and the variables of an earlier one. A block in another language, such as sh, is not run.
python3 - <<'PY' > "$RUNNER_TEMP/quickstart.sh"
import pathlib, re
blocks = re.findall(r"^\x60{3}bash\n(.*?)^\x60{3}$", pathlib.Path("README.md").read_text(encoding="utf-8"), re.M | re.S)
if not blocks:
    raise SystemExit("Expected at least one bash block in README.md")
print("".join(blocks), end="")
PY
bash -euo pipefail "$RUNNER_TEMP/quickstart.sh"
