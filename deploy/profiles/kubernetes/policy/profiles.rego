# Profile kubernetes-gate is profile kubernetes plus `gate`, and nothing else (deploy/profiles/kubernetes-gate.yaml):
# one profile's data in two files that may not drift apart. check.sh runs conftest with --combine --namespace
# profiles on the two files, so `input` is a list of {path, contents}.
package profiles

import rego.v1

profile(name) := file.contents if {
	some file in input
	endswith(file.path, sprintf("/%s.yaml", [name]))
}

# The keys that make the difference, and the only ones that may differ.
own := {"profile", "gate"}

deny contains msg if {
	base := profile("kubernetes")
	gated := profile("kubernetes-gate")
	some key in {k | some k, _ in base} | {k | some k, _ in gated}
	not key in own
	object.get(base, key, null) != object.get(gated, key, null)
	msg := sprintf("kubernetes-gate.yaml: %q differs from kubernetes.yaml; the two profiles differ only in %v", [key, own])
}

deny contains msg if {
	gated := profile("kubernetes-gate")
	not gated.gate.url
	msg := "kubernetes-gate.yaml: no gate.url; without it the viewer's build bundles the example data"
}

deny contains msg if {
	base := profile("kubernetes")
	base.gate
	msg := "kubernetes.yaml: has a gate; the viewer's development and tests read the example data through this profile"
}

deny contains msg if {
	some name in ["kubernetes", "kubernetes-gate"]
	not profile(name)
	msg := sprintf("profile %s.yaml is not in the input", [name])
}
