#!/usr/bin/env bash
# Resolve requirements/*.in into locks with exact versions and the SHA-256 of every distribution, for
# the one runtime CI uses (docs/ci.md#8-pinned-versions). Run from anywhere after changing an .in file or
# a pyproject.toml; needs uv. run.txt is resolved within dev.txt, so both agree on every version.
set -euo pipefail
cd "$(dirname "$0")/.."
own=(--no-emit-package rezono-admission --no-emit-package rezono-canon --no-emit-package rezono-compiler --no-emit-package rezono-checker
     --no-emit-package rezono-publisher)
opts=(--python-version 3.13 --python-platform x86_64-manylinux_2_28 --generate-hashes "${own[@]}")
uv pip compile requirements/dev.in -o requirements/dev.txt "${opts[@]}"
uv pip compile requirements/run.in -o requirements/run.txt -c requirements/dev.txt "${opts[@]}"
