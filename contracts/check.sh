#!/usr/bin/env bash
# Lint the contracts (contracts/yaml_keys.py, then LinkML) and validate every fixture (contracts/check.py, one
# Python process for all of them).
# Layout: fixtures/<schema>/<Class>/{valid,invalid}/*.yaml. Valid files must pass, invalid files must fail.
set -euo pipefail
exec python "$(dirname "$0")/check.py"
