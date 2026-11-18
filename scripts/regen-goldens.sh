#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export LC_ALL=C
python_bin=${PYTHON:-python}
shopt -s nullglob

for definition in examples/*/pack.yaml; do
    pack=${definition%/pack.yaml}
    if [[ -d "$pack/expected/published" ]]; then
        "$python_bin" -m rezono_publisher.kept "$pack" --make
    fi
    if [[ -d "$pack/expected" ]]; then
        "$python_bin" -m rezono_compiler compile "$pack" "$pack/expected/compiled"
    fi
done
