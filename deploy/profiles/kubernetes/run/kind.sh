#!/usr/bin/env bash
# Profile `kubernetes`, run: on a plain local cluster (kind), from this checkout, in one command (README.md).
#
#   deploy/profiles/kubernetes/run/kind.sh        bring it up, read it through its front door, take it down
#   deploy/profiles/kubernetes/run/kind.sh down   take down what a run left (REZONO_RUN_KEEP=1, or a failed run)
#
#   1. a kind cluster of one node, and a registry beside it for the images of this checkout;
#   2. what a platform gives, as fixtures: External Secrets with a ClusterSecretStore `rezono` of test values made
#      for this run, Envoy Gateway with a Gateway that ends TLS, a store (S3 API) and an issuer (OIDC);
#   3. the gate's and the viewer's images, built from deploy/gate and deploy/viewer and pushed to that registry;
#   4. the publish job: the packs of publish.packs in deploy/profiles/kubernetes.yaml into the store, as the job
#      `publish` of promote.yml does it (run/publish.sh, in a container: it stands where CI stands);
#   5. the overlay `kind` with the digests of step 3: held to ../check.sh --live, and that same render applied;
#   6. the reading: without a login nothing; as a reader of the group the gate knows, every published pack and
#      no other; as a reader without that group, nothing; and the viewer cannot reach the store, the gate can.
#
# Needs docker, kind, kubectl, openssl, curl and a Git checkout (the publish job reads the commit). KIND and
# KUBECTL name other binaries. Nothing leaves this machine but the downloads of pinned images and manifests; no
# value of the run is printed, and its work directory (certificates, test credentials) is removed at the end.
# REZONO_RUN_KEEP=1 leaves the cluster up after the reading, for a look; `kind.sh down` removes it.
set -euo pipefail
shopt -s inherit_errexit
umask 077

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
profile_dir=$(cd "$here/.." && pwd)
root=$(cd "$here/../../../.." && pwd)

CLUSTER=${REZONO_RUN_CLUSTER:-rezono-run}
# Kubernetes 1.34, the minor version ../check.sh validates against; the digest kind v0.33.0 publishes for it.
NODE_IMAGE=kindest/node:v1.34.11@sha256:44e222ee2132dab25ff87301682f89eb82c7880ea3a1bf543bfe9708fd08d67d
REGISTRY_IMAGE=registry:3.0.0@sha256:6c5666b861f3505b116bb9aa9b25175e71210414bd010d92035ff64018f9457e
ESO_URL=https://github.com/external-secrets/external-secrets/releases/download/v2.15.0/external-secrets.yaml
ESO_SHA256=34cf25e951da2aeefe465e6767036272a1db1f713b9be6a1b7bc811ae9a739c2
GATEWAY_URL=https://github.com/envoyproxy/gateway/releases/download/v1.10.0/install.yaml
GATEWAY_SHA256=f87f4d59b983aa760da52a2a0002c612028106fe69beefdf3d30cfb03905944e
HOST=rezono.example.test
ISSUER=issuer.rezono-platform.svc.cluster.local

kind=${KIND:-kind}
kubectl=${KUBECTL:-kubectl}
registry=$CLUSTER-registry
node=$CLUSTER-control-plane

k() { "$kubectl" --context "kind-$CLUSTER" "$@"; }
step() { printf '\n== %s (%ss)\n' "$*" "$SECONDS"; }
fail() { echo "kind.sh: $*" >&2; exit 1; }
# retry <times> <command...>: a controller that is not ready yet is not a failed run.
retry() {
	local n=$1 i; shift
	for ((i = 1; i <= n; i++)); do
		if "$@"; then return 0; fi
		sleep 5
	done
	return 1
}

down() {
	"$kind" delete cluster --name "$CLUSTER" >/dev/null 2>&1 || true
	docker rm -f "$registry" >/dev/null 2>&1 || true
}

case ${1:-up} in
	up) ;;
	down) down; echo "kind.sh: cluster $CLUSTER and its registry are gone"; exit 0 ;;
	*) fail "usage: kind.sh [up|down]" ;;
esac

for tool in docker "$kind" "$kubectl" openssl curl git; do
	command -v "$tool" >/dev/null || fail "needs $tool"
done
git -C "$root" rev-parse HEAD >/dev/null 2>&1 || fail "needs a Git checkout: the publish job reads the commit, its count and its time"
if "$kind" get clusters 2>/dev/null | grep -qx "$CLUSTER"; then fail "a cluster $CLUSTER exists; kind.sh down removes it"; fi

work=$(mktemp -d "${TMPDIR:-/tmp}/rezono-run.XXXXXX")
finish() {
	local status=$?
	if [ $status -ne 0 ]; then
		echo
		echo "== the run failed; what the cluster says"
		k get pods -A -o wide 2>/dev/null | grep -v ' Running \| Completed ' || true
		k -n rezono get events --sort-by=.lastTimestamp 2>/dev/null | tail -15 || true
		for d in front viewer gate; do
			echo "-- $d"; k -n rezono logs "deploy/$d" --tail=15 2>/dev/null || true
		done
	fi
	rm -rf "$work"
	if [ "${REZONO_RUN_KEEP:-0}" = 1 ]; then
		echo "kind.sh: cluster $CLUSTER is left up (REZONO_RUN_KEEP=1); kind.sh down removes it"
	else
		down
	fi
	exit $status
}
trap finish EXIT

echo "kind.sh: $("$kind" version), kubectl $("$kubectl" version --client 2>/dev/null | head -1), docker $(docker version --format '{{.Server.Version}}')"
echo "checkout: $(git -C "$root" rev-parse HEAD)"

# --- the run's own values: test credentials and a certificate authority, never printed, never kept ----------------
value() { mkdir -p "$work/values"; printf %s "$2" > "$work/values/$1"; }
hex() { openssl rand -hex "$1"; }
value client-secret "$(hex 24)"
value cookie-secret "$(openssl rand -base64 32 | tr '+/' '-_')"
value draft-key "$(hex 32)"
value root-user "run$(hex 6)"
value root-password "$(hex 20)"
value reader-id "gate$(hex 6)"
value reader-secret "$(hex 20)"
value reader-password "$(hex 16)"
value stranger-password "$(hex 16)"
v() { cat "$work/values/$1"; }

openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 2 -subj "/CN=rezono run authority" \
	-keyout "$work/ca.key" -out "$work/ca.crt" 2>/dev/null
openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -subj "/CN=$HOST" \
	-keyout "$work/tls.key" -out "$work/tls.csr" 2>/dev/null
printf 'subjectAltName=DNS:%s\nbasicConstraints=CA:FALSE\n' "$HOST" > "$work/tls.ext"
openssl x509 -req -in "$work/tls.csr" -CA "$work/ca.crt" -CAkey "$work/ca.key" -CAcreateserial -days 2 \
	-extfile "$work/tls.ext" -out "$work/tls.crt" 2>/dev/null

# --- 1. the cluster and its registry --------------------------------------------------------------------------------
step "1. cluster $CLUSTER"
docker run -d --name "$registry" -p 127.0.0.1::5000 "$REGISTRY_IMAGE" >/dev/null
"$kind" create cluster --name "$CLUSTER" --config "$here/cluster.yaml" --image "$NODE_IMAGE" --wait 180s
docker network connect kind "$registry"
# The node pulls from the registry by its name on the cluster's network, over plain HTTP.
docker exec "$node" mkdir -p "/etc/containerd/certs.d/$registry:5000"
printf '[host."http://%s:5000"]\n  capabilities = ["pull", "resolve"]\n' "$registry" |
	docker exec -i "$node" sh -c "cat > '/etc/containerd/certs.d/$registry:5000/hosts.toml'"
node_ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' "$node")
push_port=$(docker port "$registry" 5000/tcp | head -1 | sed 's/.*://')

# --- 2. the platform's part --------------------------------------------------------------------------------------------
step "2. platform: External Secrets, Envoy Gateway, store, issuer"
manifest() {
	curl -fsSL --retry 3 -o "$work/$1.yaml" "$2"
	echo "$3  $work/$1.yaml" | sha256sum -c --quiet - || fail "checksum mismatch for $2"
}
manifest external-secrets "$ESO_URL" "$ESO_SHA256"
manifest gateway "$GATEWAY_URL" "$GATEWAY_SHA256"
k apply --server-side -f "$work/external-secrets.yaml" >/dev/null
k apply --server-side -f "$work/gateway.yaml" >/dev/null

k apply -f "$here/platform/namespace.yaml" >/dev/null
k -n rezono-platform create secret generic store \
	--from-file=root-user="$work/values/root-user" --from-file=root-password="$work/values/root-password" \
	--from-file=reader-id="$work/values/reader-id" --from-file=reader-secret="$work/values/reader-secret" >/dev/null
sed -e "s/@CLIENT_SECRET@/$(v client-secret)/" -e "s/@READER_PASSWORD@/$(v reader-password)/" \
	-e "s/@STRANGER_PASSWORD@/$(v stranger-password)/" "$here/realm.json" > "$work/rezono-realm.json"
k -n rezono-platform create secret generic issuer-realm --from-file="$work/rezono-realm.json" >/dev/null
k -n gateway create secret tls rezono-tls --cert="$work/tls.crt" --key="$work/tls.key" >/dev/null
k apply -k "$here/platform" >/dev/null

# External Secrets' release manifest installs into the namespace `default`.
k -n default wait --for=condition=Available deployment/external-secrets deployment/external-secrets-webhook 	deployment/external-secrets-cert-controller --timeout=600s >/dev/null
k -n envoy-gateway-system wait --for=condition=Available deployment --all --timeout=600s >/dev/null
# The platform's secret store, here External Secrets' own fake provider: the keys the profile's ExternalSecrets
# name (README.md of the profile, "Making it live", 3), with this run's values.
cat > "$work/secret-store.yaml" <<EOF
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: rezono
spec:
  provider:
    fake:
      data:
        - key: rezono/front
          value: '{"client-id":"rezono","client-secret":"$(v client-secret)","cookie-secret":"$(v cookie-secret)"}'
        - key: rezono/viewer
          value: '{"draft-key":"$(v draft-key)"}'
        - key: rezono/gate
          value: '{"store-key-id":"$(v reader-id)","store-secret":"$(v reader-secret)"}'
EOF
retry 24 k apply -f "$work/secret-store.yaml" >/dev/null 2>&1 || fail "External Secrets does not take the ClusterSecretStore"

k -n rezono-platform wait --for=condition=Available deployment/store --timeout=300s >/dev/null
# The gate's keys: a user of the store that may list the bucket and get its objects (platform/store.yaml).
# shellcheck disable=SC2016  # the variables are the pod's
retry 12 k -n rezono-platform exec deploy/store -- sh -c '
	mc alias set run http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null &&
	mc admin policy create run rezono-read /etc/rezono/read.json >/dev/null &&
	mc admin user add run "$READER_ID" "$READER_SECRET" >/dev/null &&
	mc admin policy attach run rezono-read --user "$READER_ID" >/dev/null' || fail "the store does not take the reader's keys"
k -n rezono-platform wait --for=condition=Available deployment/issuer --timeout=600s >/dev/null
echo "platform ready"

# --- 3. the images of this checkout ----------------------------------------------------------------------------------
step "3. images: gate, viewer"
declare -A digest
for name in gate viewer; do
	docker build -q -f "$root/deploy/$name/Containerfile" -t "localhost:$push_port/rezono/$name:run" "$root" >/dev/null
	docker push -q "localhost:$push_port/rezono/$name:run" >/dev/null
	digest[$name]=$(curl -fsSI -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json' \
		"http://localhost:$push_port/v2/rezono/$name/manifests/run" | tr -d '\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: //p')
	[[ ${digest[$name]} =~ ^sha256:[0-9a-f]{64}$ ]] || fail "no digest for the image of $name"
	echo "$name ${digest[$name]}"
done

# --- 4. the publish job -------------------------------------------------------------------------------------------------
step "4. publish: the packs of deploy/profiles/kubernetes.yaml into the store"
docker build -q -f "$here/toolchain.Containerfile" -t "$CLUSTER-toolchain" "$here" >/dev/null
AWS_ACCESS_KEY_ID=$(v root-user) AWS_SECRET_ACCESS_KEY=$(v root-password) docker run --rm --network kind \
	-v "$root:/src:ro" -v "$CLUSTER-cache:/cache" \
	-e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e REZONO_S3_ENDPOINT="http://$node:30900" \
	"$CLUSTER-toolchain" /src/deploy/profiles/kubernetes/run/publish.sh

# --- 5. the profile: checked as a live installation, then that render applied -----------------------------------
step "5. overlay kind: check --live, apply"
mkdir -p "$work/kind" "$work/renders"
cat > "$work/kind/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - $(realpath --relative-to="$work/kind" "$profile_dir/overlays/kind")
images:
  - name: registry.example.test/rezono/gate
    newName: $registry:5000/rezono/gate
    digest: ${digest[gate]}
  - name: registry.example.test/rezono/viewer
    newName: $registry:5000/rezono/viewer
    digest: ${digest[viewer]}
EOF
REZONO_K8S_RENDERS="$work/renders" "$profile_dir/check.sh" --live "$work/kind"
k apply -f "$work/renders/kind.yaml" >/dev/null
k -n rezono wait --for=condition=Ready externalsecret --all --timeout=180s >/dev/null
k -n rezono wait --for=condition=Available deployment --all --timeout=600s >/dev/null
k -n rezono get deployments,externalsecrets,httproutes -o wide | cut -c1-150

# --- 6. the reading, through the front door -------------------------------------------------------------------------
step "6. reading through https://$HOST"
proxies=gateway.envoyproxy.io/owning-gateway-name=gateway
retry 36 k -n envoy-gateway-system wait --for=condition=Available deployment -l "$proxies" --timeout=5s >/dev/null 2>&1 ||
	fail "Envoy Gateway made no proxy for the Gateway"
https_port=$(k -n envoy-gateway-system get service -l "$proxies" -o jsonpath='{.items[0].spec.ports[?(@.port==443)].nodePort}')
[ -n "$https_port" ] || fail "the Gateway's proxy has no port 443"
# The reader's browser: the Gateway's name and the issuer's name both lead to the node, the certificate is checked
# against the run's authority.
web() {
	curl -sS --max-time 120 --cacert "$work/ca.crt" --connect-to "$HOST:443:$node_ip:$https_port" \
		--connect-to "$ISSUER:8080:$node_ip:30808" "$@"
}
code() { web -o /dev/null -w '%{http_code}' "$@"; }
location() { tr -d '\r' < "$1" | sed -n 's/^[Ll]ocation: //p' | tail -1; }
# login <user>: the browser's way through the front and the issuer's form; leaves the session in $work/<user>.jar.
login() {
	local user=$1 jar=$work/$1.jar h=$work/$1.headers to cookies action back
	web -c "$jar" -b "$jar" -D "$h.1" -o /dev/null "https://$HOST/"
	to=$(location "$h.1")
	case $to in "http://$ISSUER:8080/realms/rezono/protocol/openid-connect/auth?"*) ;; *) fail "the front did not send $user to the issuer" ;; esac
	web -D "$h.2" -o "$h.html" "$to"
	cookies=$(tr -d '\r' < "$h.2" | sed -n 's/^[Ss]et-[Cc]ookie: \([^;]*\).*/\1/p' | paste -sd ';' -)
	action=$(grep -o 'action="[^"]*"' "$h.html" | head -1 | sed 's/^action="//; s/"$//; s/&amp;/\&/g')
	[ -n "$action" ] || fail "the issuer showed $user no login form"
	web -D "$h.3" -o /dev/null -H "Cookie: $cookies" --data-urlencode "username=$user" \
		--data-urlencode "password@$work/values/$user-password" "$action"
	back=$(location "$h.3")
	case $back in "https://$HOST/oauth2/callback?"*) ;; *) fail "the issuer did not send $user back to the front" ;; esac
	web -c "$jar" -b "$jar" -D "$h.4" -o /dev/null "$back"
}

retry 24 test "$(code "https://$HOST/")" = 302 || fail "without a login the front answers $(code "https://$HOST/"), not a redirect to the issuer"
echo "no login: 302 to the issuer"

login reader
web -b "$work/reader.jar" -o "$work/home.html" "https://$HOST/"
# The packs the gate in the cluster was told to serve: REZONO_PACKS of the ConfigMap its Deployment names.
settings=$(k -n rezono get deployment gate -o jsonpath='{.spec.template.spec.containers[?(@.name=="gate")].envFrom[0].configMapRef.name}')
packs=$(k -n rezono get configmap "$settings" -o jsonpath='{.data.REZONO_PACKS}')
[ -n "$packs" ] || fail "no REZONO_PACKS in the cluster"
for pack in ${packs//,/ }; do
	grep -q "href=\"/$pack\"" "$work/home.html" || fail "the home page does not list $pack"
	status=$(code -b "$work/reader.jar" "https://$HOST/$pack")
	[ "$status" = 200 ] || fail "pack $pack answers $status to a reader"
	echo "reader: /$pack 200"
done
status=$(code -b "$work/reader.jar" "https://$HOST/no-such-pack")
[ "$status" = 404 ] || fail "a pack the gate does not serve answers $status, not 404"
echo "reader: a pack that is not served 404"

login stranger
status=$(code -b "$work/stranger.jar" "https://$HOST/")
[ "$status" = 403 ] || fail "a reader without the group gets $status, not 403"
echo "stranger (no group): 403"

# The network: only the gate reaches the store. One request from each, with the same code.
probe='fetch("http://store.rezono-platform.svc.cluster.local:9000/minio/health/live", { signal: AbortSignal.timeout(8000) }).then((r) => console.log("reached", r.status), (e) => console.log("no way", e.name))'
[ "$(k -n rezono exec deploy/gate -- node -e "$probe")" = "reached 200" ] || fail "the gate does not reach the store"
[ "$(k -n rezono exec deploy/viewer -- node -e "$probe")" = "no way TimeoutError" ] || fail "the viewer reaches the store"
echo "network: the gate reaches the store, the viewer does not"

step "done: profile kubernetes runs on $CLUSTER and serves ${packs}"
