#!/usr/bin/env bash
# Install the pinned Python runtime from its artifact (docs/ci.md#8-pinned-versions).
#   scripts/python-runtime.sh [requirements/.python-artifact]
# Downloads the artifact the file names (url), checks its SHA-256 (sha256) before anything is unpacked,
# unpacks it at the prefix its build expects, and checks the runtime digest of the result
# (requirements/.python-digest, scripts/python-digest.sh). Either check failing leaves nothing behind.
# A prefix in /opt/hostedtoolcache moves to the runner's own tool cache (RUNNER_TOOL_CACHE), as
# actions/setup-python does: a self-hosted runner installs nothing with root. Its libpython is then
# found through LD_LIBRARY_PATH. In CI the runtime goes first on PATH for the next steps (GITHUB_PATH
# and GITHUB_ENV, also on Forgejo Actions). Linux x86_64, like the locks.
#
# REZONO_PYTHON_CACHE, a directory, keeps the artifact as python-<sha256>.tar.gz between jobs (CI restores it
# with actions/cache, keyed on the SHA-256). A kept artifact goes through the same SHA-256 and digest
# checks as a download, so its source does not matter; one that does not match is dropped and downloaded
# again. Only an artifact that passed the SHA-256 check is kept. REZONO_RUNTIME_TOKEN, if set, goes only to
# github.com as a bearer token (curl does not pass it on through a redirect): GitHub serves release
# assets to anonymous clients less reliably.
set -euo pipefail
cd "$(dirname "$0")/.."
spec=${1:-requirements/.python-artifact}
field() { sed -n "s/^$1=//p" "$spec"; }
url=$(field url); sha=$(field sha256); prefix=$(field prefix)
[ -n "$url" ] && [ -n "$sha" ] && [ -n "$prefix" ] || { echo "python-runtime: $spec needs url, sha256 and prefix" >&2; exit 1; }
hosted=/opt/hostedtoolcache
case "$prefix" in "$hosted"/*) prefix=${RUNNER_TOOL_CACHE:-$hosted}/${prefix#"$hosted"/} ;; esac
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
sha256_of() { if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1; }
tarball=$tmp/python.tar.gz
cache=${REZONO_PYTHON_CACHE:-}
kept=${cache:+$cache/python-$sha.tar.gz}
# The copy is checked, not the kept file: a job beside this one on the same host may be writing the kept file
# (four runners shared one HOME on 11-11-2026, and a cache restore tore it between the check and the copy).
if [ -n "$kept" ] && [ -f "$kept" ]; then
  cp "$kept" "$tarball"
  if [ "$(sha256_of "$tarball")" = "$sha" ]; then
    echo "python-runtime: artifact from the cache ($kept)" >&2
  else
    echo "python-runtime: $kept does not have the pinned SHA-256; dropped, downloading" >&2
    rm -f "$kept" "$tarball"
  fi
fi
if [ ! -f "$tarball" ]; then
  auth=()
  case "$url" in
    https://github.com/*)
      if [ -n "${REZONO_RUNTIME_TOKEN:-}" ]; then
        (umask 077; printf 'Authorization: Bearer %s\n' "$REZONO_RUNTIME_TOKEN" > "$tmp/auth")
        auth=(-H "@$tmp/auth")
      fi ;;
  esac
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 10 --connect-timeout 20 --max-time 300 \
    ${auth[@]+"${auth[@]}"} -o "$tarball" "$url"
  echo "python-runtime: artifact downloaded from $url" >&2
fi
got=$(sha256_of "$tarball")
if [ "$got" != "$sha" ]; then
  echo "python-runtime: $url has SHA-256 $got, not the pinned $sha; nothing unpacked" >&2
  exit 1
fi
if [ -n "$kept" ] && [ ! -f "$kept" ]; then
  mkdir -p "$cache"
  cp "$tarball" "$kept.part" && mv "$kept.part" "$kept"
fi
rm -rf "$prefix"
mkdir -p "$prefix"
tar -xzf "$tarball" -C "$prefix" --no-same-owner
digest=$(scripts/python-digest.sh "$prefix/bin/python3" || echo unmeasurable)
if [ "$digest" != "$(cat requirements/.python-digest)" ]; then
  rm -rf "$prefix"
  echo "python-runtime: the unpacked runtime has digest $digest, not the one in requirements/.python-digest" >&2
  exit 1
fi
if [ -n "${GITHUB_PATH:-}" ]; then echo "$prefix/bin" >> "$GITHUB_PATH"; fi
if [ -n "${GITHUB_ENV:-}" ]; then echo "LD_LIBRARY_PATH=$prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" >> "$GITHUB_ENV"; fi
echo "$prefix/bin/python3"
