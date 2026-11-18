#!/usr/bin/env bash
# The check of profile `kubernetes` (README.md#the-check): for every overlay under overlays/ (or the ones named),
#   1. render it with Kustomize, twice, and require the same bytes (a re-render from the same ref is identical);
#   2. validate the render with kubeconform --strict against the schemas of one Kubernetes version and of the CRDs
#      it uses, both read from a pinned commit (an unknown or invalid field fails);
#   3. hold it to the policies in policy/ with conftest (deny fails; warn fails too with --live);
#   4. require that its gate serves exactly the packs the profile publishes (REZONO_PACKS, policy/packs.rego);
# and run the policies' own unit tests (conftest verify), hold the images' Containerfiles (deploy/*/Containerfile) to
# their policy, and require that profile kubernetes-gate is profile kubernetes plus a gate. Pure and repeatable: it reads the overlays and writes only
# under its work directory; it applies nothing to a cluster.
#
#   deploy/profiles/kubernetes/check.sh [--live] [overlay ...]
#
# An overlay is a name under overlays/, or a directory with a kustomization.yaml (an argument with a slash): an
# installation's own overlay outside this repository, or the one run/kind.sh makes with the digests it built.
#
# The tools are pinned by version and SHA-256 and downloaded once into REZONO_K8S_TOOLS (default
# ~/.cache/rezono-k8s-tools) on linux-amd64. KUSTOMIZE, KUBECONFORM and CONFTEST name binaries to use instead (for
# another platform; then the version is the caller's responsibility and the check says which ran).
set -euo pipefail
shopt -s inherit_errexit

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

KUSTOMIZE_VERSION=5.8.3
KUSTOMIZE_SHA256=cb9e31198d3f63b44848bd0afc4c8efc56e6cfef9c93a4a39a211940e6decd61
KUBECONFORM_VERSION=0.8.0
KUBECONFORM_SHA256=9bc2bffbf71f261128533edaf912153948b7ff238f9a531ae6d34466ec287883
CONFTEST_VERSION=0.71.1
CONFTEST_SHA256=c3f6b2a753bd56e377a1e51a95ae3e057f926f2e9139f7d5b5dfbbaf810f7985
# The Kubernetes version the manifests are validated against, and the schema sources at a pinned commit.
KUBERNETES_VERSION=1.34.12
K8S_SCHEMAS=https://raw.githubusercontent.com/yannh/kubernetes-json-schema/89a35a5e9a1412a692a2603d79c3786f602238a4
CRD_SCHEMAS=https://raw.githubusercontent.com/datreeio/CRDs-catalog/3eb90d47aba8d61919d4419dd38301536e32a94b

live=0
overlays=()
for arg in "$@"; do
	case $arg in
		--live) live=1 ;;
		-*) echo "check.sh: unknown option $arg" >&2; exit 2 ;;
		*) overlays+=("$arg") ;;
	esac
done
if [ ${#overlays[@]} -eq 0 ]; then
	for d in "$here"/overlays/*/; do overlays+=("$(basename "$d")"); done
fi

tools=${REZONO_K8S_TOOLS:-$HOME/.cache/rezono-k8s-tools}
# fetch <name> <url> <sha256> <member>: download a release archive, check its SHA-256, unpack one binary, and only
# then move it into the cache under a directory named by that hash. Every step fails the function on its own,
# because it runs inside $( ), where bash does not apply -e: an archive that does not match never reaches the
# cache, so a later run cannot find and start an unverified binary.
fetch() {
	local name=$1 url=$2 sum=$3 member=$4 dir="$tools/$1-$3" tmp
	if [ ! -x "$dir/$name" ]; then
		case "$(uname -s)-$(uname -m)" in
			Linux-x86_64) ;;
			*) echo "check.sh: no pinned $name for $(uname -s)-$(uname -m); set ${name^^} to a binary" >&2; return 2 ;;
		esac
		mkdir -p "$tools" || return 1
		tmp=$(mktemp -d "$tools/.$name.XXXXXX") || return 1
		if ! curl -fsSL --retry 3 -o "$tmp/archive.tar.gz" "$url"; then
			rm -rf "$tmp"; echo "check.sh: download of $name failed" >&2; return 1
		fi
		if ! echo "$sum  $tmp/archive.tar.gz" | sha256sum -c --quiet - >&2; then
			rm -rf "$tmp"; echo "check.sh: checksum mismatch for $name; nothing is kept" >&2; return 1
		fi
		if ! tar -xzf "$tmp/archive.tar.gz" -C "$tmp" "$member"; then
			rm -rf "$tmp"; echo "check.sh: cannot unpack $name" >&2; return 1
		fi
		rm -rf "$dir"
		mkdir -p "$dir" && mv "$tmp/$member" "$dir/$name" && rm -rf "$tmp" || { rm -rf "$tmp" "$dir"; return 1; }
	fi
	echo "$dir/$name"
}
# A plain assignment from $( ) fails the script (set -e) when fetch returns non-zero.
if [ -n "${KUSTOMIZE:-}" ]; then kustomize=$KUSTOMIZE; else
	kustomize=$(fetch kustomize "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv$KUSTOMIZE_VERSION/kustomize_v${KUSTOMIZE_VERSION}_linux_amd64.tar.gz" $KUSTOMIZE_SHA256 kustomize)
fi
if [ -n "${KUBECONFORM:-}" ]; then kubeconform=$KUBECONFORM; else
	kubeconform=$(fetch kubeconform "https://github.com/yannh/kubeconform/releases/download/v$KUBECONFORM_VERSION/kubeconform-linux-amd64.tar.gz" $KUBECONFORM_SHA256 kubeconform)
fi
if [ -n "${CONFTEST:-}" ]; then conftest=$CONFTEST; else
	conftest=$(fetch conftest "https://github.com/open-policy-agent/conftest/releases/download/v$CONFTEST_VERSION/conftest_${CONFTEST_VERSION}_Linux_x86_64.tar.gz" $CONFTEST_SHA256 conftest)
fi
echo "tools: kustomize $("$kustomize" version 2>/dev/null | head -1), kubeconform $("$kubeconform" -v), $("$conftest" --version | head -1)"

work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/rezono-k8s-check.XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/schemas"

echo "== policy unit tests"
"$conftest" verify --no-color --policy "$here/policy"

failed=0
# The images' recipes before any image is built (policy/containerfile.rego), and the gated profile against the
# profile it extends (policy/profiles.rego).
root=$(cd "$here/../../.." && pwd)
echo "== image recipes"
"$conftest" test --no-color --parser dockerfile --combine --namespace containerfile --policy "$here/policy" \
	"$root"/deploy/*/Containerfile || failed=1
echo "== profiles kubernetes and kubernetes-gate"
"$conftest" test --no-color --combine --namespace profiles --policy "$here/policy" \
	"$root/deploy/profiles/kubernetes.yaml" "$root/deploy/profiles/kubernetes-gate.yaml" || failed=1

# Every pack's own name (pack.yaml), which the profile's directories are read against.
mapfile -t pack_files < <(find "$root/examples" "$root/packs" -name pack.yaml | LC_ALL=C sort)
for overlay in "${overlays[@]}"; do
	case $overlay in
		*/*) dir=${overlay%/}; overlay=$(basename "$dir") ;;
		*) dir="$here/overlays/$overlay" ;;
	esac
	[ -f "$dir/kustomization.yaml" ] || { echo "check.sh: no overlay $dir" >&2; exit 2; }
	echo "== overlay $overlay"
	"$kustomize" build "$dir" > "$work/$overlay.yaml"
	"$kustomize" build "$dir" > "$work/$overlay.again.yaml"
	if ! cmp -s "$work/$overlay.yaml" "$work/$overlay.again.yaml"; then
		echo "FAIL $overlay: two renders of the same tree differ"; failed=1; continue
	fi
	echo "rendered: $(grep -c '^kind:' "$work/$overlay.yaml") objects, sha256 $(sha256sum "$work/$overlay.yaml" | cut -d' ' -f1)"
	# REZONO_K8S_RENDERS names a directory that gets each render, so a caller applies the bytes that were checked.
	if [ -n "${REZONO_K8S_RENDERS:-}" ]; then cp "$work/$overlay.yaml" "$REZONO_K8S_RENDERS/$overlay.yaml"; fi
	"$kubeconform" -strict -summary -cache "$work/schemas" -kubernetes-version "$KUBERNETES_VERSION" \
		-schema-location "$K8S_SCHEMAS/{{.NormalizedKubernetesVersion}}-standalone{{.StrictSuffix}}/{{.ResourceKind}}{{.KindSuffix}}.json" \
		-schema-location "$CRD_SCHEMAS/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json" \
		"$work/$overlay.yaml" || failed=1
	flags=(--no-color --combine --policy "$here/policy")
	[ $live -eq 1 ] && flags+=(--fail-on-warn)
	"$conftest" test "${flags[@]}" "$work/$overlay.yaml" || failed=1
	# The gate of this render serves the packs the profile publishes (policy/packs.rego).
	"$conftest" test --no-color --combine --namespace packs --policy "$here/policy" 		"$work/$overlay.yaml" "$root/deploy/profiles/kubernetes.yaml" "${pack_files[@]}" || failed=1
done

if [ $failed -ne 0 ]; then echo "check.sh: FAILED"; exit 1; fi
echo "check.sh: every overlay renders the same twice, validates strictly and meets the policies"
