#!/usr/bin/env bash
# Install Rede's Python packages exactly as locked, into a fresh virtualenv (docs/ci.md#8-pinned-versions).
#   scripts/install-python.sh requirements/run.txt admission canon compiler edge/publisher
# Every distribution is checked against its SHA-256 in the lock; this repository's own packages are
# installed from source without dependencies, so nothing outside the lock gets in. Then pip check and
# scripts/check-pinned.py must pass. The same command works in CI, on a runner or a workstation, and
# rezono_publisher.kept uses it for a replay. PYTHON names the runtime (default python3), VENV the
# virtualenv (default .venv). In CI the virtualenv goes first on PATH for the next steps (GITHUB_PATH,
# also on Forgejo Actions).
# With REZONO_VENV_REUSE=1 an existing VENV counts as a cache restored by CI (.github/actions/python): it
# moves aside, a fresh virtualenv is made as always, and scripts/venv-reuse.py moves in only the locked
# distributions whose every file matches its RECORD; anything else in it is dropped, and if anything fails
# to verify the install starts fresh. The lock install, pip check and check-pinned.py run either way.
# With --only NAME just the one stanza NAME of the lock goes in, with the lock's hashes, as a wheel only
# (--only-binary :all:, so nothing is built and no build requirement comes from the index), without this
# repository's packages and without a cached virtualenv:
#   scripts/install-python.sh --only pyyaml requirements/run.txt   (the promotion gates, RV-S08)
set -euo pipefail
only=
if [ "${1:-}" = --only ]; then only=$2; shift 2; fi
lock=$1; shift
if [ -n "$only" ] && [ $# -gt 0 ]; then
  echo "install-python: --only installs one locked distribution, not this repository's packages" >&2
  exit 2
fi
venv=${VENV:-.venv}
py0=${PYTHON:-python3}
cd "$(dirname "$0")/.."
# Nothing from the calling environment reaches Python or pip: no PYTHONPATH, PYTHONHOME or other
# PYTHON* variable, no PIP_* variable and no pip configuration file. Every Python below also runs
# isolated (-I) and pip with --isolated, so a variable set later cannot reach it either.
for v in $(compgen -e); do
  case $v in PYTHON*|PIP_*|VIRTUAL_ENV*|CONDA*) unset "$v" ;; esac
done
export PIP_CONFIG_FILE=/dev/null
# The runtime is pinned too: exactly the build whose digest is in requirements/.python-digest
# (scripts/python-digest.sh, measured from outside the interpreter, before it runs at all), and then the
# version in requirements/.python-version, CPython, on the platform the locks are for. Another Python
# gives other bytes, so it is refused, not used, also when it has the same version.
digest=$(scripts/python-digest.sh "$py0" || echo unmeasurable)
if [ "$digest" != "$(cat requirements/.python-digest 2>/dev/null)" ]; then
  echo "install-python: runtime digest $digest of $py0 is not the one in requirements/.python-digest; see docs/ci.md section 8" >&2
  exit 1
fi
want="cpython $(cat requirements/.python-version) linux-x86_64"
have=$("$py0" -I -S -c 'import platform, sys, sysconfig; print(sys.implementation.name, platform.python_version(), sysconfig.get_platform())')
if [ "$have" != "$want" ]; then
  echo "install-python: needs $want, found $have ($py0); see docs/ci.md section 8" >&2
  exit 1
fi
rm -rf "$venv.reuse"
if [ "${REZONO_VENV_REUSE:-}" = 1 ] && [ -z "$only" ] && [ -d "$venv" ]; then mv "$venv" "$venv.reuse"; fi
rm -rf "$venv"
# -S: no site hooks of the runtime's own site-packages run while the virtualenv is made.
"$py0" -I -S -m venv "$venv"
if [ -d "$venv.reuse" ]; then
  if ! "$py0" -I -S scripts/venv-reuse.py "$venv.reuse" "$venv" "$lock"; then
    echo "install-python: the cached virtualenv does not verify; installing fresh" >&2
    rm -rf "$venv"
    "$py0" -I -S -m venv "$venv"
  fi
  rm -rf "$venv.reuse"
fi
py="$venv/bin/python"
pip=("$py" -I -m pip --isolated)
# After a reuse pip finds the reused distributions satisfied and installs only what is missing, hash-checked.
req=$lock
binary=()
if [ -n "$only" ]; then
  # The stanza NAME==VERSION with its --hash lines, and the lock's index options (none in the locks here).
  req=$(mktemp)
  trap 'rm -f "$req"' EXIT
  if ! awk -v want="$only" '
    function norm(s) { s = tolower(s); gsub(/[-_.]+/, "-", s); return s }
    /^--(no-index|find-links|index-url|extra-index-url)([ =]|$)/ { print; next }
    keep { print; keep = /\\$/; next }
    /^[A-Za-z0-9]/ && index($0, "==") {
      name = $0; sub(/[^A-Za-z0-9_.-].*/, "", name)
      if (norm(name) == norm(want)) { print; found = 1; keep = /\\$/ }
    }
    END { exit !found }' "$lock" > "$req"; then
    echo "install-python: $only is not pinned in $lock" >&2
    exit 1
  fi
  binary=(--only-binary :all:)
fi
"${pip[@]}" install -q --no-deps "${binary[@]}" --require-hashes -r "$req"
editable=()
for p in "$@"; do editable+=(-e "$p"); done
# No build isolation: setuptools comes from the lock, not from the index at build time.
if [ ${#editable[@]} -gt 0 ]; then
  "${pip[@]}" install -q --no-deps --no-build-isolation "${editable[@]}"
fi
"${pip[@]}" check
"$py" -I scripts/check-pinned.py "$lock"
case $venv in /*) ;; *) venv=$PWD/$venv ;; esac
if [ -n "${GITHUB_PATH:-}" ]; then echo "$venv/bin" >> "$GITHUB_PATH"; fi
