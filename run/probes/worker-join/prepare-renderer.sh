#!/usr/bin/env bash
set -euo pipefail

# Build inside the verified module so Go's internal-package boundary and its lockfile both apply.
sources=$(cd "$(dirname "$0")" && pwd)
destination=${1:?expected an absolute renderer output path}
[[ $destination = /* ]]
revision=c23391b08842d8b824e40e1324267f08b923f743
checkout=$(mktemp -d)
trap 'rm -rf -- "$checkout"' EXIT
git -C "$checkout" init -q
git -C "$checkout" fetch -q --depth=1 https://github.com/k0sproject/k0smotron.git "$revision"
[[ $(git -C "$checkout" rev-parse FETCH_HEAD) = "$revision" ]]
git -C "$checkout" checkout -q --detach FETCH_HEAD
test -s "$checkout/go.sum"
cp "$sources/render.go" "$checkout/probe.go"
(cd "$checkout" && go build -mod=readonly -trimpath -o "$destination" probe.go)
git -C "$checkout" diff --exit-code -- go.mod go.sum
