# Nothing reaches a pod, and a pod reaches nothing, unless a NetworkPolicy says so; the namespace enforces Pod
# Security `restricted` at admission as well (two independent guards of the same rules).
package main

import rego.v1

default_deny if {
	some np in objects
	np.kind == "NetworkPolicy"
	np.spec.podSelector == {}
	{"Ingress", "Egress"} == {t | some t in np.spec.policyTypes}
	not np.spec.ingress
	not np.spec.egress
}

deny contains msg if {
	count(pods) > 0
	not default_deny
	msg := "the render has pods but no NetworkPolicy that denies all ingress and egress (podSelector {}, both policy types, no rules)"
}

# An egress rule without `to` reaches every address, in the cluster too. The base leaves the narrowing to the
# platform's address ranges to an installation, so the example warns and a real installation (--live) must narrow.
warn contains msg if {
	some np in objects
	np.kind == "NetworkPolicy"
	some rule in object.get(np.spec, "egress", [])
	not rule.to
	msg := sprintf("%s: an egress rule to every address (ports %v); name the platform's address ranges with `to`", [id(np), [p.port | some p in object.get(rule, "ports", [])]])
}

deny contains msg if {
	some ns in objects
	ns.kind == "Namespace"
	not ns.metadata.labels["pod-security.kubernetes.io/enforce"] == "restricted"
	msg := sprintf("%s: label pod-security.kubernetes.io/enforce must be restricted", [id(ns)])
}
