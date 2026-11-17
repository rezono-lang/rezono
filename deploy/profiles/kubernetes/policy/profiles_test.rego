# Unit tests of profiles.rego.
package profiles

import rego.v1

base := {"profile": "kubernetes", "viewer": {"host": "node"}, "git": {"host": "github"}}

gated := object.union(base, {"profile": "kubernetes-gate", "gate": {"url": "http://gate:8080"}})

pair(b, g) := [
	{"path": "deploy/profiles/kubernetes.yaml", "contents": b},
	{"path": "deploy/profiles/kubernetes-gate.yaml", "contents": g},
]

refused(inp, text) if {
	msgs := deny with input as inp
	some m in msgs
	contains(m, text)
}

test_the_pair_passes if {
	msgs := deny with input as pair(base, gated)
	count(msgs) == 0
}

test_a_changed_key_is_refused if refused(pair(base, object.union(gated, {"git": {"host": "forgejo"}})), "\"git\" differs")

test_a_key_only_in_one_is_refused if refused(pair(object.union(base, {"publish": {"classes": ["unclassified"]}}), gated), "\"publish\" differs")

test_no_gate_is_refused if refused(pair(base, object.remove(gated, ["gate"])), "no gate.url")

test_a_gate_in_the_default_profile_is_refused if refused(pair(object.union(base, {"gate": {"url": "x"}}), gated), "kubernetes.yaml: has a gate")

test_a_missing_file_is_refused if refused([{"path": "deploy/profiles/kubernetes.yaml", "contents": base}], "kubernetes-gate.yaml is not in the input")
