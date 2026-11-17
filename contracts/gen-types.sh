#!/usr/bin/env bash
# Generate TypeScript and Python types from the contracts (docs/contracts.md#types-from-the-contracts).
# Never edit the output; change the contract and run this again. CI runs it with the pinned LinkML
# and fails when the result differs from what is checked in.
set -euo pipefail
cd "$(dirname "$0")"
# One contract at a time; a contract that imports another (bundle imports view) carries its types.
SCHEMAS="bundle proof explain plugin port proposal output-index diagnostic"
ts=../viewer/src/lib/contract/generated
py=python/rezono_contracts
mkdir -p "$py"
if [ -f ../viewer/package.json ]; then
  mkdir -p "$ts"
fi
for s in $SCHEMAS; do
  if [ -f ../viewer/package.json ]; then
    gen-typescript "$s.yaml" > "$ts/$s.ts"
  fi
  gen-pydantic "$s.yaml" > "$py/${s//-/_}.py"  # a Python module name has no hyphen
done
# A contract that code holds at run time also gets its JSON Schema, the schema LinkML's own validator checks
# against: rezono_ports validates a port declaration with it (jsonschema), so no LinkML is needed where a port runs.
# The root is named: port.yaml imports connector.yaml for Loss (PC7), whose LossList is a tree root too.
for s in port:Port; do
  gen-json-schema --top-class "${s#*:}" "${s%%:*}.yaml" > "$py/${s%%:*}.schema.json"
done
