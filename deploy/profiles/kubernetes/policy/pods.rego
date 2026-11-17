# Secure by construction (AGENTS.md, non-negotiable 5): every pod meets Pod Security `restricted` before admission
# sees it, asks for the resources it needs, has no Kubernetes API token, and a serving pod has its probes.
package main

import rego.v1

deny contains msg if {
	some obj in unknown_workloads
	msg := sprintf("%s: a pod template in a kind the policies do not read; list the kind in policy/lib.rego", [id(obj)])
}

deny contains msg if {
	some pod in pods
	some field in ["hostNetwork", "hostPID", "hostIPC"]
	pod.spec[field] == true
	msg := sprintf("%s: %s is not allowed", [id(pod.owner), field])
}

deny contains msg if {
	some pod in pods
	some v in object.get(pod.spec, "volumes", [])
	v.hostPath
	msg := sprintf("%s: volume %s is a hostPath", [id(pod.owner), v.name])
}

deny contains msg if {
	some pod in pods
	not pod.spec.automountServiceAccountToken == false
	msg := sprintf("%s: automountServiceAccountToken must be false (no pod of Rede talks to the Kubernetes API)", [id(pod.owner)])
}

deny contains msg if {
	some pod in pods
	not pod.spec.securityContext.runAsNonRoot == true
	msg := sprintf("%s: securityContext.runAsNonRoot must be true", [id(pod.owner)])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	c.securityContext.runAsNonRoot == false
	msg := sprintf("%s: container %s sets runAsNonRoot false", [id(pod.owner), c.name])
}

deny contains msg if {
	some pod in pods
	some ctx in array.concat([object.get(pod.spec, "securityContext", {})], [object.get(c, "securityContext", {}) | some c in containers(pod.spec)])
	ctx.runAsUser == 0
	msg := sprintf("%s: runAsUser 0 (root)", [id(pod.owner)])
}

seccomp_ok(spec) if spec.securityContext.seccompProfile.type in {"RuntimeDefault", "Localhost"}

deny contains msg if {
	some pod in pods
	not seccomp_ok(pod.spec)
	msg := sprintf("%s: securityContext.seccompProfile.type must be RuntimeDefault or Localhost", [id(pod.owner)])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	not c.securityContext.allowPrivilegeEscalation == false
	msg := sprintf("%s: container %s: allowPrivilegeEscalation must be false", [id(pod.owner), c.name])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	c.securityContext.privileged == true
	msg := sprintf("%s: container %s is privileged", [id(pod.owner), c.name])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	not c.securityContext.readOnlyRootFilesystem == true
	msg := sprintf("%s: container %s: readOnlyRootFilesystem must be true (write to an emptyDir)", [id(pod.owner), c.name])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	not "ALL" in object.get(object.get(object.get(c, "securityContext", {}), "capabilities", {}), "drop", [])
	msg := sprintf("%s: container %s must drop every capability (capabilities.drop: [ALL])", [id(pod.owner), c.name])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	count(object.get(object.get(object.get(c, "securityContext", {}), "capabilities", {}), "add", [])) > 0
	msg := sprintf("%s: container %s adds a capability", [id(pod.owner), c.name])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	some path in [["requests", "cpu"], ["requests", "memory"], ["limits", "memory"]]
	object.get(c, array.concat(["resources"], path), null) == null
	msg := sprintf("%s: container %s has no resources.%s", [id(pod.owner), c.name, concat(".", path)])
}

deny contains msg if {
	some pod in pods
	pod.serves
	some c in pod.spec.containers
	some probe in ["readinessProbe", "livenessProbe"]
	not c[probe]
	msg := sprintf("%s: container %s has no %s", [id(pod.owner), c.name, probe])
}
