# Manifests and automation in sync (AGENTS.md): every ConfigMap a pod names, with every key it names, is made by
# the same render, in the pod's namespace. An overlay that generates a ConfigMap without the namespace of the base
# renders `gate-<hash>` beside a Deployment that still asks for `gate`: valid YAML, and a pod that never starts.
package main

import rego.v1

namespace_of(obj) := object.get(obj.metadata, "namespace", "")

# The ConfigMaps of the render, by namespace and name, with their keys.
config_keys[[namespace_of(cm), cm.metadata.name]] := keys if {
	some cm in objects
	cm.kind == "ConfigMap"
	keys := {k | some k, _ in object.get(cm, "data", {})} | {k | some k, _ in object.get(cm, "binaryData", {})}
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	some f in object.get(c, "envFrom", [])
	ref := f.configMapRef
	not ref.optional == true
	not config_keys[[namespace_of(pod.owner), ref.name]]
	msg := sprintf("%s: container %s: envFrom names ConfigMap %s, which this render does not make in the pod's namespace", [id(pod.owner), c.name, ref.name])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	some e in object.get(c, "env", [])
	ref := e.valueFrom.configMapKeyRef
	not ref.optional == true
	not ref.key in object.get(config_keys, [[namespace_of(pod.owner), ref.name]], set())
	msg := sprintf("%s: container %s: env %s names ConfigMap %s key %s, which this render does not make in the pod's namespace", [id(pod.owner), c.name, e.name, ref.name, ref.key])
}

# A ConfigMap as a volume, on its own or inside a projected volume.
config_volumes(spec) := array.concat(
	[[v.name, v.configMap] | some v in object.get(spec, "volumes", []); v.configMap],
	[[v.name, s.configMap] | some v in object.get(spec, "volumes", []); some s in object.get(object.get(v, "projected", {}), "sources", []); s.configMap],
)

deny contains msg if {
	some pod in pods
	some [volume, ref] in config_volumes(pod.spec)
	not ref.optional == true
	not config_keys[[namespace_of(pod.owner), ref.name]]
	msg := sprintf("%s: volume %s names ConfigMap %s, which this render does not make in the pod's namespace", [id(pod.owner), volume, ref.name])
}
