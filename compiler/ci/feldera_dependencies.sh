#!/usr/bin/env bash

feldera_dependencies_dir() {
  printf '%s\n' "${RUNNER_TEMP:?}/feldera-dependencies"
}

feldera_dependency_home() {
  local home
  home=$(sed -n 's/^HOME=//p' "$(feldera_dependencies_dir)/toolchain.txt") || return
  [[ "$home" =~ ^/([a-zA-Z0-9_.-]+/)*[a-zA-Z0-9_.-]+$ && "$home/" != */../* && "$home/" != */./* ]] || return 1
  printf '%s\n' "$home"
}

feldera_dependency_identity() {
  local image=$1
  printf '%s\n' "$image" "${GITHUB_SHA:?}" "${GITHUB_RUN_ID:?}" "${GITHUB_RUN_ATTEMPT:?}" unoptimized
}

feldera_seed_dependencies() (
  set -euo pipefail
  image=$1
  seed="feldera-dependencies-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
  cache=$(feldera_dependencies_dir)
  staging=$(mktemp -d "${RUNNER_TEMP:?}/feldera-seed.XXXXXXXX")
  cleanup_seed() {
    docker rm --force --volumes "$seed" >/dev/null 2>&1 || true
    rm -rf -- "$staging"
  }
  trap cleanup_seed EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  mkdir "$cache"
  started=$(date +%s)
  nil=feldera_pipe_pipeline_00000000_0000_0000_0000_000000000000_main
  docker pull "$image"
  docker create --name "$seed" --network none --entrypoint /bin/bash "$image" -euo pipefail -c '
    workspace="$HOME/.feldera/compiler/rust-compilation"
    profile=unoptimized
    # The image ships the optimized build of this same empty pipeline.
    rm -f -- "$workspace/crates/$1/stdout.log" "$workspace/crates/$1/stderr.log"
    "$HOME/feldera/build/pipeline-manager" --bind-address=0.0.0.0 \
      --sql-compiler-path="$HOME/feldera/build/sql2dbsp-jar-with-dependencies.jar" \
      --compilation-cargo-lock-path="$HOME/feldera/Cargo.lock" \
      --dbsp-override-path="$HOME/feldera" --precompile --compilation-profile="$profile"
    cd "$workspace"
    test -d "target/$profile"
    {
      sha256sum "$HOME/feldera/Cargo.lock"
      rustc -vV
      cargo -V
      printf "HOME=%s\nRUSTFLAGS=%s\nCARGO_BUILD_TARGET=%s\n" "$HOME" "${RUSTFLAGS:-}" "${CARGO_BUILD_TARGET:-}"
    } > /tmp/feldera-dependency-toolchain.txt
    target=$(awk '"'"'$1 == "host:" {print $2}'"'"' /tmp/feldera-dependency-toolchain.txt)
    test -n "$target"
    cargo metadata --offline --locked --format-version 1 --filter-platform "$target" \
      > /tmp/feldera-dependency-metadata.json
    touch /tmp/feldera-dependency-ready
    exec sleep infinity
  ' feldera-dependencies "$nil"
  docker start "$seed" >/dev/null
  until docker exec "$seed" test -f /tmp/feldera-dependency-ready; do
    if [[ "$(docker container inspect --format '{{.State.Running}}' "$seed")" != true ]]; then
      docker logs "$seed" >&2
      exit 1
    fi
    sleep 3
  done
  docker logs "$seed"
  docker cp "$seed:/tmp/feldera-dependency-toolchain.txt" "$cache/toolchain.txt"
  engine_home=$(feldera_dependency_home)
  workspace="$engine_home/.feldera/compiler/rust-compilation"
  docker cp "$seed:$engine_home/feldera/Cargo.lock" "$staging/Cargo.lock"
  docker cp "$seed:/tmp/feldera-dependency-metadata.json" "$staging/metadata.json"
  docker cp "$seed:$workspace/crates/$nil/stdout.log" "$staging/cargo.log"
  feldera_dependency_identity "$image" > "$cache/identity.txt"
  # Preserve Cargo's timestamps and materialize both names of each build-script executable.
  docker exec "$seed" tar --format=pax --hard-dereference -cf - -C "$workspace/target/unoptimized" . |
    python compiler/ci/export_feldera_dependencies.py export "$engine_home" "$staging/Cargo.lock" "$staging/metadata.json" "$staging/cargo.log" |
    zstd -q -T0 -3 -o "$cache/dependencies.tar.zst"
  digest=$(cd "$cache" && sha256sum dependencies.tar.zst identity.txt toolchain.txt)
  printf '%s\n' "$digest" > "$cache/checksums.txt"
  provenance=$(sha256sum "$cache/checksums.txt")
  printf 'provenance=%s\n' "${provenance%% *}" >> "${GITHUB_OUTPUT:?}"
  printf 'Feldera dependency seed elapsed_seconds=%d bytes=%s\n' \
    "$(( $(date +%s) - started ))" "$(stat -c '%s' "$cache/dependencies.tar.zst")"
)

feldera_restore_dependencies() (
  set -euo pipefail
  image=$1
  container=$2
  cache=$(feldera_dependencies_dir)
  started=$(date +%s)
  expected=${FELDERA_DEPENDENCY_PROVENANCE:?Feldera dependency seed is required}
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]]
  verifier="$PWD/compiler/ci/export_feldera_dependencies.py"
  cd "$cache"
  # The seed job output and the same-attempt artifact independently identify these bytes.
  printf '%s  checksums.txt\n' "$expected" | sha256sum --check --status -
  sha256sum --check --strict --status checksums.txt
  feldera_dependency_identity "$image" | cmp - identity.txt
  docker exec "$container" bash -euo pipefail -c '
    cd "$HOME/.feldera/compiler/rust-compilation"
    sha256sum "$HOME/feldera/Cargo.lock"
    rustc -vV
    cargo -V
    printf "HOME=%s\nRUSTFLAGS=%s\nCARGO_BUILD_TARGET=%s\n" "$HOME" "${RUSTFLAGS:-}" "${CARGO_BUILD_TARGET:-}"
  ' | cmp - toolchain.txt
  zstd -q -d -c dependencies.tar.zst |
    python "$verifier" verify |
    docker exec -i "$container" bash -euo pipefail -c '
      profile="$HOME/.feldera/compiler/rust-compilation/target/unoptimized"
      mkdir -p "$profile"
      tar --extract --no-same-owner --no-same-permissions --directory "$profile"
    '
  printf 'Feldera dependency restore elapsed_seconds=%d bytes=%s provenance=%s\n' \
    "$(( $(date +%s) - started ))" "$(stat -c '%s' dependencies.tar.zst)" "$expected"
)

feldera_dependency_activity() {
  local container=$1 engine_home
  engine_home=$(feldera_dependency_home) || return
  docker exec "$container" bash -euo pipefail -c '
    crates="$HOME/.feldera/compiler/rust-compilation/crates"
    nil=feldera_pipe_pipeline_00000000_0000_0000_0000_000000000000_main
    logs=$(find "$crates" -mindepth 2 -maxdepth 2 -type f \
      -path "*/feldera_pipe_pipeline_*_main/stdout.log" ! -path "*/$nil/stdout.log" -printf "%T@ %p\n" | sort -n)
    oldest=${logs%%$'"'"'\n'"'"'*}
    test -n "$oldest"
    cat -- "${oldest#* }"
  ' | python compiler/ci/export_feldera_dependencies.py activity "$engine_home"
}
