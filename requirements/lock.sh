#!/usr/bin/env bash
# Resolve requirements/*.in into locks with exact versions and the SHA-256 of every distribution, for
# the one runtime CI uses (docs/ci.md#8-pinned-versions). Run from anywhere after changing an .in file or
# a pyproject.toml; needs uv. run.txt is resolved within dev.txt, so both agree on every version.
set -euo pipefail
cd "$(dirname "$0")/.."
own=(--no-emit-package rede-admission --no-emit-package rede-canon --no-emit-package rede-compiler --no-emit-package rede-checker
     --no-emit-package rede-publisher --no-emit-package rede-githost)
opts=(--python-version 3.13 --python-platform x86_64-manylinux_2_28 --generate-hashes "${own[@]}")
uv pip compile requirements/dev.in -o requirements/dev.txt "${opts[@]}"
uv pip compile requirements/run.in -o requirements/run.txt -c requirements/dev.txt "${opts[@]}"
