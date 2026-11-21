#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."
source compiler/ci/feldera_dependencies.sh
# Official v0.383.0 Linux amd64 image. The release includes the SQL compiler and Rust build cache.
image=images.feldera.com/feldera/pipeline-manager@sha256:7e1580efd340af0f6267386bd5da57aa10ef5b46572855245108209baf24bb5f
if [[ "${1:-}" == --pull ]]; then
  exec docker pull "$image"
fi
if [[ "${1:-}" == --seed-dependencies ]]; then
  feldera_seed_dependencies "$image"
  exit
fi
if (( $# != 0 )); then
  echo "Usage: $0 [--pull | --seed-dependencies]" >&2
  exit 2
fi
reports="${RUNNER_TEMP:?}/feldera-oracle"
mkdir -p "$reports"
container="feldera-oracle-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
inputs=$(mktemp -d "$RUNNER_TEMP/feldera-inputs.XXXXXXXX")
chmod 755 "$inputs"
shard=${FELDERA_SHARD:-}
collector=
copy_rust_trace() {
  local snapshot="$reports/.rustc.$BASHPID"
  if docker exec "$container" sh -c '
      expected="$HOME/.feldera/compiler/rust-compilation"
      cd "$expected" && [ "$(pwd -P)" = "$expected" ] &&
        test -s .rezono-rustc.log && cat .rezono-rustc.log
    ' > "$snapshot" 2>/dev/null; then
    mv -f -- "$snapshot" "$reports/rustc.log"
  else
    rm -f -- "$snapshot"
  fi
}
cleanup() {
  status=$?
  trap - EXIT
  if [[ -n "$collector" ]]; then
    kill "$collector" 2>/dev/null || true
    wait "$collector" 2>/dev/null || true
  fi
  if docker container inspect "$container" >/dev/null 2>&1; then
    copy_rust_trace || true
    case "$shard" in
      platform-incremental|platform-e2e|subsidy) feldera_dependency_activity "$container" > "$reports/dependency-build.json" || true ;;
    esac
    if (( status != 0 )); then
      docker logs --tail 250 "$container" > "$reports/engine.log" 2>&1 || true
    fi
    docker rm --force --volumes "$container" >/dev/null || status=1
  fi
  rm -rf -- "$inputs" || exit 1
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! docker image inspect "$image" >/dev/null 2>&1; then
  docker pull "$image"
fi
original="$inputs/original-wrapper"
docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$image" |
  sed -n 's/^RUSTC_WRAPPER=//p' > "$original"
chmod 644 "$original"
compiler_env=(--env CARGO_NET_OFFLINE=true --env RUSTC_WRAPPER=/tmp/rezono-measure-feldera-rustc
              --env CARGO_PROFILE_DEV_DEBUG=0 --env CARGO_PROFILE_UNOPTIMIZED_DEBUG=0)
# The generated operator crates are small and independent. Leave the engine's dependencies and
# the pipeline link crate on their original profile.
printf '\n' > "$inputs/operator-codegen-units"
if [[ "$shard" == platform-incremental ]]; then
  printf '1\n' > "$inputs/operator-codegen-units"
fi
chmod 644 "$inputs/operator-codegen-units"
docker run --detach --name "$container" --network none "${compiler_env[@]}" \
  --mount "type=bind,src=$PWD/compiler/ci/measure_feldera_rustc.sh,dst=/tmp/rezono-measure-feldera-rustc,readonly" \
  --mount "type=bind,src=$original,dst=/tmp/rezono-feldera-original-wrapper,readonly" \
  --mount "type=bind,src=$inputs,dst=/tmp/rezono-oracle-input,readonly" "$image"
case "$shard" in
  platform-incremental|platform-e2e|subsidy)
    feldera_restore_dependencies "$image" "$container" | tee "$reports/dependency-restore.log"
    ;;
esac
pid=$(docker inspect --format '{{.State.Pid}}' "$container")
# Only loopback exists here. Enter the service network, then drop back to the runner user.
export FELDERA_URL=http://127.0.0.1:8080
inside=(sudo nsenter --target "$pid" --net -- sudo -H -u "$(id -un)" --
        env "PATH=$PATH" "FELDERA_URL=$FELDERA_URL" FELDERA_PROFILE=unoptimized GITHUB_ACTIONS=true \
        "FELDERA_ORACLE_REPORTS=$reports" "FELDERA_ORACLE_INPUT_DIR=$inputs")
"${inside[@]}" curl --fail --silent --show-error --retry 45 --retry-connrefused \
  --retry-delay 2 --retry-max-time 95 --max-time 5 "$FELDERA_URL/healthz"
if [[ "$shard" == platform-incremental ]]; then
  # Retain the active Rust invocation even if GitHub stops the job before cleanup.
  (
    while docker container inspect "$container" >/dev/null 2>&1; do
      copy_rust_trace || true
      if [[ -s "$reports/storage.log" && ! -s "$reports/dependency-build.json" ]] &&
         grep -q 'compiled compile_seconds=' "$reports/storage.log"; then
        feldera_dependency_activity "$container" > "$reports/dependency-build.json" || true
      fi
      sleep 5
    done
  ) &
  collector=$!
fi
docker image inspect --format 'pinned image bytes={{.Size}}' "$image" > "$reports/storage.log"
df -h "$reports" >> "$reports/storage.log"
printf 'runner cpus=%s architecture=%s\n' "$(nproc)" "$(uname -m)" >> "$reports/storage.log"
awk '/^(MemTotal|SwapTotal):/ { print }' /proc/meminfo >> "$reports/storage.log"
for control in cpu.max memory.max; do
  if [[ -r "/sys/fs/cgroup/$control" ]]; then
    printf 'runner cgroup %s=%s\n' "$control" "$(cat "/sys/fs/cgroup/$control")" >> "$reports/storage.log"
  fi
done

selectors=(
  compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives
  compiler/tests/test_bound.py::test_the_check_view_on_feldera_holds_the_rows_past_the_bound
  compiler/tests/test_boolean_rule_inputs.py::test_native_boolean_rule_inputs
  compiler/tests/test_recorded_dates.py::test_independent_date_equality
  compiler/tests/test_rules_sql_and_access_guards.py::test_rational_functional_overflow_unknown_and_invalid_denominator
  compiler/tests/test_rules_sql_and_access_guards.py::test_zero_rule_functional_relation_emits_valid_sql_with_empty_state
  compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does
  compiler/tests/test_ordered_rule_scalars_engines.py::test_feldera_orders_typed_values
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
if [[ -n "$shard" ]]; then
  python compiler/ci/feldera_shards.py select "$shard" "$inventory" > "$nodes"
else
  cp "$inventory" "$nodes"
fi
mapfile -t tests < "$nodes"
result=0
"${inside[@]}" "${suite[@]}" -v --capture=tee-sys --junitxml="$reports/results.xml" "${tests[@]}" || result=$?
if [[ -z "$shard" ]]; then
  python compiler/ci/verify_feldera_run.py "$nodes" "$reports/results.xml"
fi
exit "$result"
