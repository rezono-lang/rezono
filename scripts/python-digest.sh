#!/usr/bin/env bash
# The digest of a Python runtime, as installed (docs/ci.md#8-pinned-versions).
#   scripts/python-digest.sh python3
# One SHA-256 over the interpreter binary, its libpython and its standard library (without
# site-packages and __pycache__), measured from outside with coreutils: the interpreter is never asked
# about itself, so a replacement cannot report the pinned digest. requirements/.python-digest pins it;
# scripts/install-python.sh refuses a runtime with another digest, also of the same version.
set -euo pipefail
exe=$(command -v "$1") || { echo "python-digest: $1 not found" >&2; exit 1; }
exe=$(readlink -f "$exe")
name=$(basename "$exe")
case "$name" in
  python[0-9].[0-9]*) ;;
  *) echo "python-digest: $exe is not named pythonX.Y" >&2; exit 1 ;;
esac
prefix=$(dirname "$(dirname "$exe")")
if command -v sha256sum >/dev/null; then sha=(sha256sum); else sha=(shasum -a 256); fi
cd "$prefix"
# The files that count, of one type (f: file, l: link), as NUL-separated paths in a fixed order.
members() {
  { [ "$1" = l ] || printf 'bin/%s\0' "$name"
    find lib -maxdepth 1 -name "lib${name}*" -type "$1" -print0
    if [ -d "lib/$name" ]; then
      find "lib/$name" \( -name site-packages -o -name __pycache__ \) -prune -o -type "$1" -print0
    fi
  } | LC_ALL=C sort -z
}
# A file counts by its bytes, a link by its target.
{
  members f | xargs -0 "${sha[@]}"
  members l | while IFS= read -r -d '' f; do echo "link $(readlink "$f")  $f"; done
} | "${sha[@]}" | cut -d' ' -f1
