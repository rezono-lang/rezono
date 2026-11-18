#!/usr/bin/env bash
set -euo pipefail
revision=${ARGOCD_APP_REVISION:?}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
read -r renderer _ < <(sha256sum admission_release.py)
read -r publication _ < <(sha256sum fixtures/server/publication.yaml)

# The fixture Service stays inside the runner-owned cluster. The runner's
# locked Python environment renders the same checkout on demand.
host=fixture-git.fixture-system.svc
exec 3<>"/dev/tcp/$host/80"
printf 'GET /release/%s/%s/%s HTTP/1.0\r\nHost: %s\r\n\r\n' \
  "$revision" "$renderer" "$publication" "$host" >&3
IFS= read -r status <&3
if [[ "$status" != "HTTP/1.0 200 "* ]]; then
  printf 'Admission fixture renderer returned %s\n' "${status%$'\r'}" >&2
  exit 1
fi
while IFS= read -r header <&3; do
  if [[ "$header" == $'\r' ]]; then
    cat <&3
    exit 0
  fi
done
exit 1
