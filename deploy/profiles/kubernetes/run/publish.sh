#!/usr/bin/env bash
# The publish job of the run on kind, inside the toolchain container (kind.sh starts it): what the job `publish`
# of .github/workflows/promote.yml does for profile edge, for profile kubernetes and against the cluster's store.
# The checkout is mounted read-only at /src; the job works on a clone of it, so nothing is written back. The
# keys and the endpoint come from the environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, REDE_S3_ENDPOINT).
# /cache keeps the Python runtime's download and the package caches between runs.
set -euo pipefail
shopt -s inherit_errexit

mkdir -p /cache/python-runtime /cache/pip /cache/npm
export REDE_PYTHON_CACHE=/cache/python-runtime PIP_CACHE_DIR=/cache/pip npm_config_cache=/cache/npm

# The checkout belongs to another user than this container's; Git takes that only from the global configuration
# (of this container, which is thrown away).
git config --global --add safe.directory '*'
git clone -q --no-local /src /work
cd /work
echo "publish job at $(git rev-parse HEAD) (epoch $(git rev-list --count HEAD))"

python=$(scripts/python-runtime.sh)
LD_LIBRARY_PATH=$(dirname "$(dirname "$python")")/lib
export LD_LIBRARY_PATH
PYTHON=$python scripts/install-python.sh requirements/run.txt admission canon checker compiler edge/publisher
export PATH=/work/.venv/bin:$PATH
(cd viewer && npm ci --ignore-scripts --no-audit --no-fund)

export REDE_PROFILE_FILE=/work/deploy/profiles/kubernetes.yaml
deploy/profiles/edge/publish.sh
