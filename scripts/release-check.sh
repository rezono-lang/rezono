#!/usr/bin/env bash
set -euo pipefail
repo=$PWD
work=$(mktemp -d)
out=$1
mkdir -p "$out" "$work/build" "$work/consumer"
export SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)
python -m venv "$work/tool"
"$work/tool/bin/python" -m pip install --quiet --no-deps --require-hashes -r requirements/run.txt
npm ci --prefix rezono --omit=dev --ignore-scripts --no-audit --no-fund
node scripts/release-language.mjs "$work/language" "$work/module-reader"
"$work/tool/bin/python" scripts/release-wheel.py "$out" "$work/build" "$work/module-reader"
(cd "$work/language" && npm pack --ignore-scripts --pack-destination "$out")

cd "$work/consumer"
python -m venv venv
venv/bin/python -m pip install --quiet --no-deps --require-hashes -r "$repo/requirements/run.txt"
venv/bin/python -m pip install --quiet --no-deps "$out"/*.whl
venv/bin/python -m pip check
cp -R "$repo/examples/library" library
rm library/facts/errors.yaml
REZONO_NODE="$work/unavailable-node" venv/bin/rezono compile library "$work/yaml-build"
mkdir -p authored/rezono
cp -R "$repo/compiler/tests/fixtures/minimal/messages" authored/
printf 'kinds:\n  - {kind: item, shape: rect}\n' > authored/channels.yaml
cat > authored/pack.yaml <<'YAML'
name: authored
version: "0.1.0"
default_language: nl
rezono:
  - {module: rezono/items.rezono, form: rezono/items.json, layer: facts}
YAML
cat > authored/rezono/items.rezono <<'REZONO'
rezono 0
pack authored
kind Item world closed
  since: Date?
REZONO
node "$work/module-reader/src/write-form.js" authored/rezono/items.rezono authored/rezono/items.json
sed -i 's/since: Date?/since: Text?/' authored/rezono/items.rezono
venv/bin/rezono compile authored "$work/authored-build"
jq -e 'any(.attributes[]; .id == "item.since" and .type == "text" and .required == false)' \
  "$work/authored-build/bundle/schema-bundle.json"
manifest=$(venv/bin/rezono-publish library --store "file://$work/store" --role reader=complete --epoch 1 --knowledge-time 2026-01-01T00:00:00Z)
jq -e '.checks[] | select(.name == "rezono:proofs" and .status == "green" and .violations == 0)' "$work/store/library/manifests/$manifest.json"
npm install --ignore-scripts --no-audit --no-fund "$out"/*.tgz
node --input-type=module -e "import { parse, print } from 'rezono'; const q = 'ask Book where unknown title'; if (print(parse(q).tree) !== q) throw Error('Language round trip failed')"

cd "$repo"
python scripts/leak_check.py
python scripts/release-audit.py "$out" | tee -a "$GITHUB_STEP_SUMMARY"
