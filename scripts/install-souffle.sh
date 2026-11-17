#!/usr/bin/env bash
set -euo pipefail
package=x86_64-ubuntu-2404-souffle-2.5-Linux.deb
digest=c7e9dd1349506bbb23c4dcf89e87396198006235f79b1cc516c0a2b67ac067bc
file="$RUNNER_TEMP/$package"
curl --fail --location --silent --show-error --retry 3 \
  "https://github.com/souffle-lang/souffle/releases/download/2.5/$package" -o "$file"
echo "$digest  $file" | sha256sum --check -
sudo apt-get update -qq
sudo apt-get install -y "$file"
souffle --version
