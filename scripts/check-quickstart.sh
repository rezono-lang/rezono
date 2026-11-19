#!/usr/bin/env bash
set -euo pipefail
# The quickstart is every bash block of README.md, in order. Each block runs on its own, but all of them in one
# shell: a later block uses the working directory and the variables of an earlier one. A block in another
# language, such as sh, is not run. When a text block follows a bash block with only blank lines between them,
# the standard output of the bash block must equal that text block byte for byte; standard error is not compared.
# A bash block without a text block below it is run and not compared (decisions/front-door.md).
quickstart_dir="$(cd "$RUNNER_TEMP" && pwd)/quickstart"
readonly quickstart_dir
rm -rf "$quickstart_dir"
mkdir -p "$quickstart_dir"
python3 - "$quickstart_dir" <<'PY'
import pathlib, sys

work = pathlib.Path(sys.argv[1])
lines = pathlib.Path("README.md").read_text(encoding="utf-8").splitlines(keepends=True)
fences = []  # (language, body, index of the opening line, index of the closing line)
i = 0
while i < len(lines):
    line = lines[i].rstrip("\n")
    if line.startswith("```"):
        end = i + 1
        while end < len(lines) and lines[end].rstrip("\n") != "```":
            end += 1
        if end == len(lines):
            raise SystemExit(f"README.md line {i + 1}: a fence that is never closed")
        fences.append((line[3:].strip(), "".join(lines[i + 1:end]), i, end))
        i = end + 1
    else:
        i += 1
driver = ["#!/usr/bin/env bash"]
count = 0
for n, (language, body, start, end) in enumerate(fences):
    if language != "bash":
        continue
    count += 1
    block = f'"$quickstart_dir/block-{count}.sh"'
    (work / f"block-{count}.sh").write_bytes(body.encode("utf-8"))
    after = fences[n + 1] if n + 1 < len(fences) else None
    shown = (after is not None and after[0] == "text"
             and all(not text.strip() for text in lines[end + 1:after[2]]))
    if not shown:
        driver.append(f"source {block}")
        continue
    (work / f"expected-{count}.txt").write_bytes(after[1].encode("utf-8"))
    actual = f'"$quickstart_dir/actual-{count}.txt"'
    driver.append(f"source {block} > {actual}")
    driver.append(f"cat {actual}")
    driver.append(f'quickstart_compare {count} {start + 1} "$quickstart_dir/expected-{count}.txt" {actual}')
if not count:
    raise SystemExit("Expected at least one bash block in README.md")
(work / "quickstart.sh").write_bytes(("\n".join(driver) + "\n").encode("utf-8"))
PY
quickstart_compare() {
  if ! python3 -c 'import sys; sys.exit(open(sys.argv[1], "rb").read() != open(sys.argv[2], "rb").read())' "$3" "$4"; then
    {
      echo "README.md bash block $1 (line $2): the text block below it differs from what it prints."
      echo "--- expected"
      cat "$3"
      echo "--- actual"
      cat "$4"
      echo "---"
    } >&2
    exit 1
  fi
}
source "$quickstart_dir/quickstart.sh"
