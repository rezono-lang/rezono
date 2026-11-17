# Unit tests of the policies: a small render that passes, and for every rule one change that it must refuse.
# Run: conftest verify --policy deploy/profiles/kubernetes/policy (check.sh does).
package main

import rego.v1

digest := "sha256:1111111111111111111111111111111111111111111111111111111111111111"

container := {
	"name": "c",
	"image": sprintf("registry.example.org/c@%s", [digest]),
	"env": [{"name": "STORE_SECRET", "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}}}],
	"readinessProbe": {"tcpSocket": {"port": 80}},
	"livenessProbe": {"tcpSocket": {"port": 80}},
	"resources": {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"memory": "32Mi"}},
	"securityContext": {"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true, "capabilities": {"drop": ["ALL"]}},
}

pod_spec := {
	"automountServiceAccountToken": false,
	"securityContext": {"runAsNonRoot": true, "seccompProfile": {"type": "RuntimeDefault"}},
	"containers": [container],
	"volumes": [{"name": "v", "secret": {"secretName": "s", "items": [{"key": "k", "path": "k"}]}}],
}

deployment(spec) := {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "d"}, "spec": {"template": {"spec": spec}}}

external_secret := {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "metadata": {"name": "s"}, "spec": {"target": {"name": "s"}, "data": [{"secretKey": "k", "remoteRef": {"key": "r"}}]}}

deny_all := {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "default-deny"}, "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}}

namespace := {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "n", "labels": {"pod-security.kubernetes.io/enforce": "restricted"}}}

render(objs) := [{"path": "render.yaml", "contents": objs}]

# object.union merges nested objects; put replaces a key whole.
put(o, k, v) := object.union(object.remove(o, [k]), {k: v})

with_pod(spec) := render([namespace, deny_all, external_secret, deployment(spec)])

with_container(c) := with_pod(object.union(pod_spec, {"containers": [c]}))

refused(inp, text) if {
	msgs := deny with input as inp
	some m in msgs
	contains(m, text)
}

test_the_good_render_passes if {
	msgs := deny with input as with_pod(pod_spec)
	count(msgs) == 0
	warnings := warn with input as with_pod(pod_spec)
	count(warnings) == 0
}

test_the_good_render_passes_as_separate_files if {
	msgs := deny with input as [{"path": "a.yaml", "contents": namespace}, {"path": "b.yaml", "contents": [deny_all, external_secret, deployment(pod_spec)]}]
	count(msgs) == 0
}

test_an_image_by_tag_is_refused if refused(with_container(object.union(container, {"image": "registry.example.org/c:1.0"})), "not pinned by digest")

test_a_short_digest_is_refused if refused(with_container(object.union(container, {"image": "registry.example.org/c@sha256:abc"})), "not pinned by digest")

test_the_zero_digest_warns if {
	zero := object.union(container, {"image": "registry.example.org/c@sha256:0000000000000000000000000000000000000000000000000000000000000000"})
	warnings := warn with input as with_container(zero)
	count(warnings) == 1
	msgs := deny with input as with_container(zero)
	count(msgs) == 0
}

test_host_network_is_refused if refused(with_pod(object.union(pod_spec, {"hostNetwork": true})), "hostNetwork")

test_a_host_path_is_refused if refused(with_pod(object.union(pod_spec, {"volumes": [{"name": "h", "hostPath": {"path": "/"}}]})), "hostPath")

test_a_service_account_token_is_refused if refused(with_pod(object.remove(pod_spec, ["automountServiceAccountToken"])), "automountServiceAccountToken")

test_root_is_refused if refused(with_pod(object.union(pod_spec, {"securityContext": {"runAsNonRoot": false, "seccompProfile": {"type": "RuntimeDefault"}}})), "runAsNonRoot")

test_user_zero_is_refused if refused(with_container(object.union(container, {"securityContext": object.union(container.securityContext, {"runAsUser": 0})})), "runAsUser 0")

test_no_seccomp_is_refused if refused(with_pod(put(pod_spec, "securityContext", {"runAsNonRoot": true})), "seccompProfile")

test_privilege_escalation_is_refused if refused(with_container(put(container, "securityContext", object.remove(container.securityContext, ["allowPrivilegeEscalation"]))), "allowPrivilegeEscalation")

test_privileged_is_refused if refused(with_container(object.union(container, {"securityContext": object.union(container.securityContext, {"privileged": true})})), "privileged")

test_a_writable_root_is_refused if refused(with_container(put(container, "securityContext", object.remove(container.securityContext, ["readOnlyRootFilesystem"]))), "readOnlyRootFilesystem")

test_kept_capabilities_are_refused if refused(with_container(object.union(container, {"securityContext": object.union(container.securityContext, {"capabilities": {"drop": ["NET_RAW"]}})})), "drop every capability")

test_an_added_capability_is_refused if refused(with_container(object.union(container, {"securityContext": object.union(container.securityContext, {"capabilities": {"drop": ["ALL"], "add": ["NET_ADMIN"]}})})), "adds a capability")

test_no_memory_limit_is_refused if refused(with_container(put(container, "resources", {"requests": {"cpu": "10m", "memory": "16Mi"}})), "resources.limits.memory")

test_a_serving_pod_without_probes_is_refused if refused(with_container(object.remove(container, ["readinessProbe"])), "readinessProbe")

test_a_job_needs_no_probes if {
	job := {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "j"}, "spec": {"template": {"spec": object.union(pod_spec, {"containers": [object.remove(container, ["readinessProbe", "livenessProbe"])]})}}}
	msgs := deny with input as render([namespace, deny_all, external_secret, job])
	count(msgs) == 0
}

test_a_cron_job_is_checked if {
	cron := {"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "c"}, "spec": {"jobTemplate": {"spec": {"template": {"spec": object.union(pod_spec, {"hostPID": true})}}}}}
	refused(render([namespace, deny_all, external_secret, cron]), "hostPID")
}

test_a_secret_in_git_is_refused if refused(render([namespace, deny_all, external_secret, deployment(pod_spec), {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "x"}}]), "a Secret in Git")

test_a_key_no_external_secret_makes_is_refused if refused(with_container(object.union(container, {"env": [{"name": "X", "valueFrom": {"secretKeyRef": {"name": "s", "key": "other"}}}]})), "no ExternalSecret of this render makes")

test_an_optional_key_may_be_missing if {
	msgs := deny with input as with_container(object.union(container, {"env": [{"name": "X", "valueFrom": {"secretKeyRef": {"name": "s", "key": "other", "optional": true}}}]}))
	count(msgs) == 0
}

test_a_secret_no_external_secret_makes_is_refused if refused(with_container(object.union(container, {"envFrom": [{"secretRef": {"name": "elsewhere"}}]})), "envFrom names secret elsewhere")

test_a_volume_of_an_unmade_secret_is_refused if refused(with_pod(object.union(pod_spec, {"volumes": [{"name": "v", "secret": {"secretName": "elsewhere"}}]})), "volume v names secret elsewhere")

test_a_volume_key_not_made_is_refused if refused(with_pod(object.union(pod_spec, {"volumes": [{"name": "v", "secret": {"secretName": "s", "items": [{"key": "other", "path": "o"}]}}]})), "volume v names key other")

test_data_from_makes_any_key if {
	open := {"apiVersion": "external-secrets.io/v1", "kind": "ExternalSecret", "metadata": {"name": "s"}, "spec": {"dataFrom": [{"extract": {"key": "r"}}]}}
	inp := render([namespace, deny_all, open, deployment(object.union(pod_spec, {"containers": [object.union(container, {"env": [{"name": "X", "valueFrom": {"secretKeyRef": {"name": "s", "key": "any"}}}]})]}))])
	msgs := deny with input as inp
	count(msgs) == 0
}

test_a_secret_in_a_config_map_is_refused if refused(render([namespace, deny_all, external_secret, deployment(pod_spec), {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "m"}, "data": {"API_TOKEN": "x"}}]), "looks like a secret")

test_a_literal_secret_is_refused if refused(with_container(object.union(container, {"env": [{"name": "REZONO_LIVE_TOKEN", "value": "x"}]})), "literal value")

test_no_default_deny_is_refused if refused(render([namespace, external_secret, deployment(pod_spec)]), "denies all ingress and egress")

test_a_default_deny_with_rules_is_not_one if refused(render([namespace, object.union(deny_all, {"spec": object.union(deny_all.spec, {"ingress": [{}]})}), external_secret, deployment(pod_spec)]), "denies all ingress and egress")

test_a_namespace_without_restricted_is_refused if refused(render([{"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "n"}}, deny_all, external_secret, deployment(pod_spec)]), "pod-security.kubernetes.io/enforce")

test_an_unknown_workload_kind_is_refused if {
	rc := {"apiVersion": "v1", "kind": "ReplicationController", "metadata": {"name": "rc"}, "spec": {"template": {"spec": pod_spec}}}
	refused(render([namespace, deny_all, external_secret, rc]), "a pod template in a kind the policies do not read")
}

test_a_projected_secret_not_made_is_refused if refused(with_pod(put(pod_spec, "volumes", [{"name": "p", "projected": {"sources": [{"secret": {"name": "elsewhere"}}]}}])), "projected volume p names secret elsewhere")

test_a_projected_key_not_made_is_refused if refused(with_pod(put(pod_spec, "volumes", [{"name": "p", "projected": {"sources": [{"secret": {"name": "s", "items": [{"key": "other", "path": "o"}]}}]}}])), "projected volume p names key other")

test_an_image_pull_secret_not_made_is_refused if refused(with_pod(object.union(pod_spec, {"imagePullSecrets": [{"name": "registry"}]})), "imagePullSecrets names secret registry")

test_egress_to_every_address_warns if {
	open := {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "out"}, "spec": {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{"ports": [{"protocol": "TCP", "port": 443}]}]}}
	inp := render([namespace, deny_all, open, external_secret, deployment(pod_spec)])
	warnings := warn with input as inp
	count(warnings) == 1
	msgs := deny with input as inp
	count(msgs) == 0
}

test_egress_with_to_does_not_warn if {
	narrow := {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "out"}, "spec": {"podSelector": {}, "policyTypes": ["Egress"], "egress": [{"to": [{"ipBlock": {"cidr": "10.0.0.0/8"}}], "ports": [{"protocol": "TCP", "port": 443}]}]}}
	warnings := warn with input as render([namespace, deny_all, narrow, external_secret, deployment(pod_spec)])
	count(warnings) == 0
}

csi(attrs) := {"name": "c", "csi": object.union({"driver": "csi.example.org"}, attrs)}

test_a_csi_volume_without_a_secret_passes if {
	msgs := deny with input as with_pod(put(pod_spec, "volumes", [csi({})]))
	count(msgs) == 0
}

test_a_csi_credential_not_made_is_refused if refused(with_pod(put(pod_spec, "volumes", [csi({"nodePublishSecretRef": {"name": "elsewhere"}})])), "CSI volume c names secret elsewhere")

test_a_csi_credential_made_passes if {
	msgs := deny with input as with_pod(put(pod_spec, "volumes", [csi({"nodePublishSecretRef": {"name": "s"}})]))
	count(msgs) == 0
}

test_a_secrets_store_csi_volume_is_refused if refused(with_pod(put(pod_spec, "volumes", [csi({"driver": "secrets-store.csi.k8s.io"})])), "mounts secrets through secrets-store.csi.k8s.io")

templated(entries) := object.union(external_secret, {"spec": object.union(external_secret.spec, {"target": {"name": "s", "template": {"data": entries}}})})

test_a_template_from_the_store_passes if {
	msgs := deny with input as render([namespace, deny_all, templated({"DB_PASSWORD": "{{ .password }}", "url": "postgres://db:5432/rezono"}), deployment(pod_spec)])
	count(msgs) == 0
}

test_a_literal_secret_in_a_template_is_refused if refused(render([namespace, deny_all, templated({"DB_PASSWORD": "hunter2"}), deployment(pod_spec)]), "template key DB_PASSWORD looks like a secret")
