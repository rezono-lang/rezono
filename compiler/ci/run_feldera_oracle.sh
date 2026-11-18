#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
reports="${RUNNER_TEMP:?}/feldera-oracle"
mkdir -p "$reports"
# Official v0.383.0 Linux amd64 image. The release includes the SQL compiler and Rust build cache.
image=images.feldera.com/feldera/pipeline-manager@sha256:7e1580efd340af0f6267386bd5da57aa10ef5b46572855245108209baf24bb5f
container="feldera-oracle-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
export FELDERA_ORACLE_SANDBOX="$container" FELDERA_ORACLE_REPORTS="$reports"
inputs=$(mktemp -d "$RUNNER_TEMP/feldera-inputs.XXXXXXXX")
chmod 755 "$inputs"
cleanup() {
  status=$?
  trap - EXIT
  if docker container inspect "$container" >/dev/null 2>&1; then
    python compiler/tests/feldera_service.py || status=1
    docker rm --force --volumes "$container" >/dev/null || status=1
  fi
  rm -rf -- "$inputs" || exit 1
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Hold the isolated network while each compilation replaces its writable engine and build artifacts.
docker run --detach --name "$container" --network none --read-only --entrypoint /bin/sleep "$image" infinity
docker image inspect --format 'pinned image bytes={{.Size}}' "$image" > "$reports/storage.log"
pid=$(docker inspect --format '{{.State.Pid}}' "$container")
# Only loopback exists here. Enter the service network, then drop back to the runner user.
export FELDERA_URL=http://127.0.0.1:8080
inside=(sudo nsenter --target "$pid" --net -- sudo -H -u "$(id -un)" --
        env "PATH=$PATH" "FELDERA_URL=$FELDERA_URL" FELDERA_PROFILE=unoptimized GITHUB_ACTIONS=true \
        "FELDERA_ORACLE_INPUT_DIR=$inputs" "FELDERA_ORACLE_IMAGE=$image"
        "FELDERA_ORACLE_SANDBOX=$container" "FELDERA_ORACLE_REPORTS=$reports")

selectors=(
  compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives
  compiler/tests/test_bound.py::test_the_check_view_on_feldera_holds_the_rows_past_the_bound
  compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does
  examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors
  examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch
  examples/test_platform_incremental_proof.py::test_platform_incremental_delta_and_witnesses_match_batch
)
suite=(python -u -m pytest --rootdir="$PWD" -o empty_parameter_set_mark=fail_at_collect)
"${inside[@]}" "${suite[@]}" -q --collect-only "${selectors[@]}" | tee "$reports/collection.log"
inventory="$reports/collection.txt"
grep -E '^(compiler/tests|examples)/[^:]+\.py::' "$reports/collection.log" > "$inventory"
for selector in "${selectors[@]}"; do
  awk -v selected="$selector" '$0 == selected || index($0, selected "[") == 1 { found=1 } END { exit !found }' "$inventory" ||
    { echo "No collected case for $selector" >&2; exit 1; }
done
nodes="$reports/collected.txt"
shard=${FELDERA_SHARD:-}
if [[ -n "$shard" ]]; then
  python compiler/ci/feldera_shards.py select "$shard" "$inventory" > "$nodes"
else
  cp "$inventory" "$nodes"
fi
mapfile -t tests < "$nodes"
result=0
"${inside[@]}" "${suite[@]}" -v --junitxml="$reports/results.xml" "${tests[@]}" || result=$?
if [[ -z "$shard" ]]; then
  python compiler/ci/verify_feldera_run.py "$nodes" "$reports/results.xml"
fi
exit "$result"
