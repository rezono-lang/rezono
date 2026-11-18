#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
reports="${RUNNER_TEMP:?}/feldera-oracle"
mkdir -p "$reports"
# Official v0.383.0 Linux amd64 image. The release includes the SQL compiler and Rust build cache.
image=images.feldera.com/feldera/pipeline-manager@sha256:7e1580efd340af0f6267386bd5da57aa10ef5b46572855245108209baf24bb5f
container="feldera-oracle-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
cleanup() {
  status=$?
  trap - EXIT
  if docker container inspect "$container" >/dev/null 2>&1; then
    if (( status != 0 )); then
      docker logs --tail 250 "$container" > "$reports/engine.log" 2>&1 || true
    fi
    docker rm --force --volumes "$container" >/dev/null || exit 1
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker run --detach --name "$container" --network none --env CARGO_NET_OFFLINE=true "$image"
pid=$(docker inspect --format '{{.State.Pid}}' "$container")
# Only loopback exists here. Enter the service network, then drop back to the runner user.
export FELDERA_URL=http://127.0.0.1:8080
inside=(sudo nsenter --target "$pid" --net -- sudo -H -u "$(id -un)" --
        env "PATH=$PATH" "FELDERA_URL=$FELDERA_URL" FELDERA_PROFILE=unoptimized GITHUB_ACTIONS=true)
"${inside[@]}" curl --fail --silent --show-error --retry 45 --retry-connrefused \
  --retry-delay 2 --retry-max-time 95 --max-time 5 "$FELDERA_URL/healthz"

selectors=(
  compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives
  compiler/tests/test_bound.py::test_the_check_view_on_feldera_holds_the_rows_past_the_bound
  compiler/tests/test_boolean_rule_inputs.py::test_native_boolean_rule_inputs
  compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does
  examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors
  examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch
  examples/test_platform_incremental_proof.py::test_platform_incremental_delta_and_witnesses_match_batch
)
suite=(python -m pytest --rootdir="$PWD" -q -o empty_parameter_set_mark=fail_at_collect "${selectors[@]}")
"${inside[@]}" "${suite[@]}" --collect-only | tee "$reports/collection.log"
nodes="$reports/collected.txt"
grep -E '^(compiler/tests|examples)/[^:]+\.py::' "$reports/collection.log" > "$nodes"
for selector in "${selectors[@]}"; do
  awk -v selected="$selector" '$0 == selected || index($0, selected "[") == 1 { found=1 } END { exit !found }' "$nodes" ||
    { echo "No collected case for $selector" >&2; exit 1; }
done
result=0
"${inside[@]}" "${suite[@]}" --junitxml="$reports/results.xml" || result=$?
python compiler/ci/verify_feldera_run.py "$nodes" "$reports/results.xml"
exit "$result"
