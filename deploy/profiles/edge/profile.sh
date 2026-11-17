#!/bin/sh
# Profile the viewer Worker of profile edge on one machine, without Cloudflare: its deployed bundle in workerd
# through the Miniflare API (harness.mjs), the binding GATE answered by the Node gate on a local S3 API (moto)
# with the pilot packs published by publish.sh, one fixed role instead of Access. Every subrequest is logged.
# Takes a CPU profile and a sampling heap profile of GET <path> on the viewer through the DevTools protocol
# (profile.mjs).
#   deploy/profiles/edge/profile.sh [path ...]    (default: /)
# Writes $REZONO_PROFILE_OUT (default ./profile-out): <name>.cpuprofile, <name>.heapprofile, summary.md and
# results.json. Fails when a path answers 5xx or never reaches the gate through GATE.
# The scaling check (docs/gui.md, O(page)): with REZONO_SCALE="<pack dir> <k> [--keep kind ...]" a copy of that
# pack with its facts multiplied k times (multiply.py) is published too, a row page of the pack is added to the
# paths, every path of the pack is profiled on the copy as well, and scale.py fails when a page of the copy
# costs more: GATE calls and bytes, and the gate's own store reads (REZONO_STORE_LOG).
# Needs: python (moto, compiler[batch], publisher[s3], checker), node 24, `npm ci` in edge/gate, viewer and
# deploy/profiles/edge/tools, and the viewer built for the profile (REZONO_PROFILE=edge npm run build).
set -eu
root=$(git rev-parse --show-toplevel)
out=${REZONO_PROFILE_OUT:-$PWD/profile-out}
work=$(mktemp -d)
mkdir -p "$out"
[ "$#" -gt 0 ] || set -- /
AWS_ACCESS_KEY_ID=$(python -c 'import secrets; print(secrets.token_hex(10))')
AWS_SECRET_ACCESS_KEY=$(python -c 'import secrets; print(secrets.token_hex(20))')
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY REZONO_S3_ENDPOINT=http://127.0.0.1:9000
moto_server -H 127.0.0.1 -p 9000 > "$work/s3.log" 2>&1 &
s3=$!
trap 'kill $s3 2>/dev/null' EXIT
for i in $(seq 30); do curl -s -o /dev/null http://127.0.0.1:9000 && break; sleep 1; done
curl -sf -X PUT http://127.0.0.1:9000/rezono >/dev/null
packs=$(python -c 'import sys, yaml; print(" ".join(yaml.safe_load(open(sys.argv[1]))["publish"]["packs"]))' "${REZONO_PROFILE_FILE:-$root/deploy/profiles/edge.yaml}")
copy=""
if [ -n "${REZONO_SCALE:-}" ]; then
  # shellcheck disable=SC2086
  copy=$(python "$root/deploy/profiles/edge/multiply.py" $REZONO_SCALE)
  trap 'kill $s3 2>/dev/null; rm -rf "$copy"' EXIT
fi
# shellcheck disable=SC2086
REZONO_STORE=s3://rezono "$root/deploy/profiles/edge/publish.sh" $packs ${copy:+"$copy"}

# The gate as a Node service on the local store (as smoke.sh): the viewer's binding GATE answers from it.
# The store is this run's own (the profile's packs, and the multiplied copy), so the gate serves every pack in it.
: > "$work/store.log"
REZONO_STORE=s3://rezono REZONO_PACKS='*' REZONO_AUTH=fixed REZONO_ROLE=viewer REZONO_LISTEN_HOST=127.0.0.1 REZONO_GATE_BASE=/gate PORT=8788 REZONO_STORE_LOG="$work/store.log" \
  node "$root/edge/gate/src/node.ts" > "$work/gate.log" 2>&1 &
gate=$!
for i in $(seq 30); do curl -sf -o /dev/null http://127.0.0.1:8788/gate/whoami && break; sleep 1; done
curl -sf http://127.0.0.1:8788/gate/whoami && echo
curl -sf http://127.0.0.1:8788/gate/packs && echo
if [ -n "$copy" ]; then
  name=$(python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["name"])' "$(echo "$REZONO_SCALE" | cut -d' ' -f1)/pack.yaml")
  big=$(python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["name"])' "$copy/pack.yaml")
  # A row page of the pack: the first row of the first kind with a page, from the page index and the bundle.
  curl -sf "http://127.0.0.1:8788/gate/$name/page" > "$work/page.json"
  curl -sf "http://127.0.0.1:8788/gate/$name/bundle" > "$work/bundle.json"
  row=$(python - "$work/page.json" "$work/bundle.json" <<'PY'
import json, sys
page = json.load(open(sys.argv[1]))["page"]
pages = {p["kind"] for p in json.load(open(sys.argv[2])).get("pages", [])}
for k in page["kinds"]:
    if k["kind"] in pages and k.get("first"):
        first = k["first"][0]
        print(f"/{k['kind']}/{first['id'] if isinstance(first, dict) else first}")
        break
PY
)
  [ -n "$row" ] && set -- "$@" "/$name$row"
  # The same two reads on the copy: the gate caches what they read (its head, manifest and bundle), so
  # without them the pack would be profiled warm and its copy cold, and that difference is no growth.
  curl -sf -o /dev/null "http://127.0.0.1:8788/gate/$big/page"
  curl -sf -o /dev/null "http://127.0.0.1:8788/gate/$big/bundle"
  # The same paths of the pack on its copy, after all others.
  for p in "$@"; do
    case "$p" in "/$name" | "/$name/"* | "/$name?"*) set -- "$@" "/$big${p#/"$name"}" ;; esac
  done
fi

# The viewer as deployed: the bundle of `wrangler deploy --dry-run`, run alone under Miniflare (harness.mjs).
wrangler="$root/deploy/profiles/edge/tools/node_modules/.bin/wrangler"
(cd "$root/viewer" && "$wrangler" deploy --config wrangler.jsonc --dry-run --outdir "$work/viewer" > "$work/bundle.log" 2>&1) \
  || { cat "$work/bundle.log"; exit 1; }
grep 'Total Upload' "$work/bundle.log" || true
: > "$work/subrequests.log"
node "$root/deploy/profiles/edge/harness.mjs" "$work/viewer/_worker.js" "$root/viewer/wrangler.jsonc" "$work/subrequests.log" \
  > "$work/viewer.log" 2>&1 &
viewer=$!
trap 'kill $s3 $gate $viewer 2>/dev/null; [ -z "$copy" ] || rm -rf "$copy"' EXIT
for i in $(seq 60); do grep -q 'harness ready' "$work/viewer.log" && break; sleep 1; done
grep -q 'harness ready' "$work/viewer.log" || { cat "$work/viewer.log"; exit 1; }
# Every path must reach the gate through GATE and must not fail; profile.mjs fails otherwise, after writing
# the summary, so the logs below are kept either way.
status=0
REZONO_INSPECTORS="viewer=9229" REZONO_SUBREQUESTS="$work/subrequests.log" REZONO_STORE_LOG="$work/store.log" \
  node "$root/deploy/profiles/edge/profile.mjs" "$out" "$@" || status=$?
if [ -n "$copy" ]; then
  # The control: a deliberate whole-snapshot read (the largest kind, straight from the gate) on the pack and
  # on its copy. scale.py requires it to grow; a check that cannot see it would pass anything.
  for p in "$name" "$big"; do
    curl -sf "http://127.0.0.1:8788/gate/$p/page" > "$work/control-page.json"
    m=$(python -c 'import json, sys; print(json.load(open(sys.argv[1]))["manifest"])' "$work/control-page.json")
    rel=$(python -c 'import json, sys; print(max(json.load(open(sys.argv[1]))["page"]["kinds"], key=lambda k: (k["count"], k["kind"]))["kind"])' "$work/control-page.json")
    off=$(wc -c < "$work/store.log")
    code=$(curl -s -o "$work/control.json" -w '%{http_code}' "http://127.0.0.1:8788/gate/$p/$m/snapshots/$rel")
    python - "$out/results.json" "$work/store.log" "$off" "control:$p" "$code" "$work/control.json" <<'PY'
import json, sys
results, log, off, path, code, body = sys.argv[1:7]
lines = open(log, "rb").read()[int(off):].decode().splitlines()
gets = [line.split(" ", 2) for line in lines if line.startswith("get ")]
lists = [line.split(" ", 2) for line in lines if line.startswith("list ")]
rs = json.load(open(results))
rs.append({"path": path, "status": int(code), "gate_calls": 1, "gate_bytes": len(open(body, "rb").read()),
           "store_gets": len(gets), "store_bytes": sum(int(g[1]) for g in gets),
           "store_listed": sum(int(x[1]) for x in lists), "store_reads": [[g[2], int(g[1])] for g in gets]})
json.dump(rs, open(results, "w"), indent=1)
PY
  done
  python "$root/deploy/profiles/edge/scale.py" "$out/results.json" "$name" "$big" > "$work/scale.md" || status=1
  cat "$work/scale.md"; { echo; cat "$work/scale.md"; } >> "$out/summary.md"
fi
{ echo; echo '## Subrequests through GATE, in order'; echo; echo '```'; cat "$work/subrequests.log"; echo '```'; } >> "$out/summary.md"
for f in subrequests viewer gate store; do echo "== $f"; tail -60 "$work/$f.log"; cp "$work/$f.log" "$out/"; done
exit $status
