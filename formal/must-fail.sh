#!/usr/bin/env bash
# TLC must find the named invariant or action property, with no other violation.
set -euo pipefail

cfg=$1
module=$2
expected=$(sed -nE 's/^\\\* must-fail:[[:space:]]+([A-Za-z][A-Za-z0-9_]*)[[:space:]]*$/\1/p' "$cfg")
if [[ ! "$expected" =~ ^[A-Za-z][A-Za-z0-9_]*$ ]]; then
  echo "$cfg must name exactly one expected invariant" >&2
  exit 2
fi

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
status=0
java -XX:+UseParallelGC -cp "${TLA_JAR:?Set TLA_JAR to the verified TLC jar}" tlc2.TLC \
  -workers 2 -metadir "$work/states" -config "$cfg" "$module" > "$work/tlc.log" 2>&1 || status=$?
tail -60 "$work/tlc.log"
violated=$(sed -nE 's/^Error: (Invariant|Action property) ([A-Za-z][A-Za-z0-9_]*) is violated\.?$/\2/p' "$work/tlc.log" | sort -u)
if [[ "$status" == 0 || "$violated" != "$expected" ]]; then
  printf '%s expected violation of %s. TLC exited %s, violations: %s\n' \
    "$cfg" "$expected" "$status" "${violated:-none}" >&2
  exit 1
fi
printf '%s violated %s as expected.\n' "$cfg" "$expected"
