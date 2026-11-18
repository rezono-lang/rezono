#!/usr/bin/env bash
set -euo pipefail
umask 077
work="$RUNNER_TEMP/rezono-fixture"
[[ "$KUBECONFIG" == "$RUNNER_TEMP/rezono-fixture.kubeconfig" ]]
kube=(kubectl --kubeconfig "$KUBECONFIG" --context kind-rezono-fixture --request-timeout=30s)
apply() {
  for attempt in 1 2 3; do
    if "${kube[@]}" apply --server-side "$@"; then
      return 0
    fi
    if [[ "$attempt" != 3 ]]; then sleep 4; fi
  done
  return 1
}
revision=$(git rev-parse HEAD)
mirror="$work/git"
mkdir -p "$mirror"
git init --bare --quiet "$mirror/rezono.git"
git --git-dir "$mirror/rezono.git" fetch --quiet --depth=1 "$PWD" "$revision:refs/heads/fixture"
git --git-dir "$mirror/rezono.git" symbolic-ref HEAD refs/heads/fixture

gateway=$(docker network inspect kind | jq -er '.[0].IPAM.Config[].Gateway | strings | select(test("^[0-9.]+$"))')
port=18080
python -u loop/cluster/admission_fixture.py serve "$gateway" "$port" "$mirror" "$revision" \
  > "$work/admission-bridge.log" 2>&1 &
echo "$!" > "$work/admission-bridge.pid"
curl --fail --silent --show-error --retry 10 --retry-connrefused --max-time 15 "http://$gateway:$port/healthz"
test "$(git ls-remote "http://$gateway:$port/rezono.git" HEAD | cut -f1)" = "$revision"

# These resources only serve the local fixture. Admission resources themselves
# are produced by the plugin and reconciled by the Argo Application.
cat > "$work/fixture-git.yaml" <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: fixture-system
---
apiVersion: v1
kind: Service
metadata:
  name: fixture-git
  namespace: fixture-system
spec:
  ports:
    - {name: http, port: 80, targetPort: $port}
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: fixture-git
  namespace: fixture-system
  labels:
    kubernetes.io/service-name: fixture-git
addressType: IPv4
ports:
  - {name: http, protocol: TCP, port: $port}
endpoints:
  - addresses: ["$gateway"]
    conditions: {ready: true}
---
apiVersion: v1
kind: Namespace
metadata:
  name: argocd
EOF
apply -f "$work/fixture-git.yaml"

argo_source="$work/argo-core-install.yaml"
curl --fail --silent --show-error --location --retry 3 --max-time 120 \
  --output "$argo_source" 'https://raw.githubusercontent.com/argoproj/argo-cd/v3.6.1/manifests/core-install.yaml'
printf '0b38189d6e1fd76ef5c3db10355026c48a02020d82bf21a1a1b5ab16dffe4f3c  %s\n' "$argo_source" | sha256sum --check
python loop/cluster/admission_fixture.py argo "$argo_source" > "$work/argo-fixture.yaml"
apply --namespace argocd -f "$work/argo-fixture.yaml"
"${kube[@]}" wait --for=condition=Established --timeout=90s crd/applications.argoproj.io crd/appprojects.argoproj.io
for component in deployment/argocd-redis deployment/argocd-repo-server statefulset/argocd-application-controller; do
  "${kube[@]}" --namespace argocd rollout status --timeout=180s "$component"
done
python loop/cluster/admission_application.py --revision "$revision" > "$work/admission-application.json"
repository=$(jq -er '.spec.source.repoURL' "$work/admission-application.json")
cat > "$work/admission-project.yaml" <<EOF
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: default
spec:
  sourceRepos: ["$repository"]
  destinations:
    - {server: "https://kubernetes.default.svc", namespace: "*"}
  clusterResourceWhitelist:
    - {group: "", kind: Namespace}
    - {group: apiextensions.k8s.io, kind: CustomResourceDefinition}
    - {group: admissionregistration.k8s.io, kind: ValidatingAdmissionPolicy}
    - {group: admissionregistration.k8s.io, kind: ValidatingAdmissionPolicyBinding}
  namespaceResourceWhitelist:
    - {group: admission.rezono.org, kind: NamespacePublication}
EOF
apply --namespace argocd -f "$work/admission-project.yaml"
apply --namespace argocd -f "$work/admission-application.json"
application=application.argoproj.io/rezono-admission
for attempt in {1..48}; do
  if "${kube[@]}" --namespace argocd get "$application" -o json > "$work/application-observed.json" &&
      jq --exit-status --arg revision "$revision" \
        '.spec.source.targetRevision == $revision and .status.sync.revision == $revision and .status.sync.status == "Synced"' \
        "$work/application-observed.json" > /dev/null; then
    echo "Argo reconciled admission from checkout $revision"
    {
      printf 'REZONO_CLUSTER_KUBECONFIG=%s\nREZONO_ADMISSION_TEST_KUBECONFIG=%s\n' "$KUBECONFIG" "$KUBECONFIG"
      printf 'REZONO_ADMISSION_TEST_APPLICATION=rezono-admission\n'
      printf 'REZONO_ADMISSION_TEST_APPLICATION_NAMESPACE=argocd\n'
    } >> "$GITHUB_ENV"
    exit 0
  fi
  sleep 5
done
"${kube[@]}" --namespace argocd get "$application" -o jsonpath='{.status.conditions}'
echo
exit 1
