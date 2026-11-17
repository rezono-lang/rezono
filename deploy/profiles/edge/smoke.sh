#!/bin/sh
# Smoke test of the profile on one machine, without Cloudflare: a local S3 API (moto) instead of R2 and
# one fixed role instead of Access. Publish a green pack, refuse a red one, read through the gate.
# The two packs are made here from the compiler's neutral test pack, so the test does not depend on the
# state of a pilot pack. Its S3 API and gate listen on free ports and log into the work directory, so jobs on
# several runners of one host do not meet. Needs python (moto, compiler[batch], publisher[s3]) and node 24 with edge/gate
# installed (npm ci), and viewer/ installed for the views (npm ci --ignore-scripts).
set -eu
root=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
green=$work/green red=$work/red
for p in "$green" "$red"; do cp -R "$root/compiler/tests/fixtures/minimal" "$p" && mkdir "$p/facts"; done
printf 'alpha:\n  - {id: a1, title: t, size: 1}\n' > "$green/facts/a.yaml"
printf 'alpha:\n  - {id: a1, title: t, size: 1}\n  - {id: a1, title: u, size: 2}\n' > "$red/facts/a.yaml"  # a duplicate id
free_port() { python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
s3_port=$(free_port) gate_port=$(free_port)
export AWS_ACCESS_KEY_ID=smoke AWS_SECRET_ACCESS_KEY=smoke-secret REDE_S3_ENDPOINT=http://127.0.0.1:$s3_port
moto_server -H 127.0.0.1 -p "$s3_port" > "$work/s3.log" 2>&1 &
s3=$!
# The gate serves the one pack this test publishes, by name (REDE_PACKS), as a deployment names its packs.
name=$(python -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["name"])' "$green/pack.yaml")
REDE_STORE=s3://rede REDE_PACKS=$name REDE_AUTH=fixed REDE_ROLE=viewer REDE_LISTEN_HOST=127.0.0.1 PORT=$gate_port node "$root/edge/gate/src/node.ts" > "$work/gate.log" 2>&1 &
gate=$!
trap 'kill $s3 $gate 2>/dev/null; tail -20 "$work/gate.log"' EXIT
for i in $(seq 30); do curl -s -o /dev/null "$REDE_S3_ENDPOINT" && break; sleep 1; done
curl -sf -X PUT "$REDE_S3_ENDPOINT/rede" >/dev/null

"$root/deploy/profiles/edge/publish.sh" "$green"
status=0; "$root/deploy/profiles/edge/publish.sh" "$red" || status=$?
[ "$status" = 2 ] || { echo "expected exit 2 (red check) for $red, got $status"; exit 1; }

for i in $(seq 30); do curl -s -o /dev/null http://127.0.0.1:$gate_port/whoami && break; sleep 1; done
get() { curl -sf "http://127.0.0.1:$gate_port$1"; }
check() { python -c "import json,sys; d=json.load(sys.stdin); assert $1, d"; }
get /whoami | check 'd == {"role": "viewer"}'
get /packs | check "d == ['$name']"
pack=$name
get "/$pack/manifests" | check 'len(d) == 1 and "counts" not in d[0] and {s["role"] for s in d[0]["snapshots"]} == {"viewer"}'
set -- $(get "/$pack/manifests" | python -c 'import json,sys; d=json.load(sys.stdin)[0]; print(d["id"], d["snapshots"][0]["relation"])')
get "/$pack/$1/snapshots/$2" | check 'isinstance(d, list)'
get "/$pack/bundle" | check 'd["format"] == "rede.schema-bundle/1"'
# The views made at publication: level 0 of the overview's islands, read down from the role's view index
# (this pack gives the role no element to draw, so no island opens a Map, and there is no sheet `map`).
get "/$pack/$1/islands/root" | check 'd["format"] == "rede.islands/1" and d["key"] == "root" and d["islands"] == []'
[ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$gate_port/$pack/$1/views/map")" = 404 ]
[ "$(curl -s -o /dev/null -w '%{http_code}' -X TRACE http://127.0.0.1:$gate_port/whoami)" = 405 ]
[ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$gate_port/$pack/$1/snapshots/no-such-relation")" = 404 ]
kill -0 $gate
echo "smoke ok"
