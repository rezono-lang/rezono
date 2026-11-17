# Names, never values, and manifests and automation in sync (AGENTS.md): no Secret object lives in
# Git; every Secret a pod names, with every key it names, is made by an ExternalSecret of the same render; and no
# ConfigMap or literal environment value carries what looks like a secret.
package main

import rego.v1

secret_name := `(?i)(token|secret|password|passwd|private[_-]?key|draft[_-]?key|cookie)`

# The Secrets the render's ExternalSecrets make, and their keys. dataFrom makes keys the render cannot list.
made[name] := keys if {
	some es in objects
	es.kind == "ExternalSecret"
	name := object.get(object.get(es.spec, "target", {}), "name", es.metadata.name)
	keys := {d.secretKey | some d in object.get(es.spec, "data", [])}
}

open_keys contains name if {
	some es in objects
	es.kind == "ExternalSecret"
	count(object.get(es.spec, "dataFrom", [])) > 0
	name := object.get(object.get(es.spec, "target", {}), "name", es.metadata.name)
}

has_key(name, key) if key in made[name]

has_key(name, _) if name in open_keys

deny contains msg if {
	some obj in objects
	obj.kind == "Secret"
	msg := sprintf("%s: a Secret in Git; make it with an ExternalSecret (secrets.yaml)", [id(obj)])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	some e in object.get(c, "env", [])
	ref := e.valueFrom.secretKeyRef
	not ref.optional == true
	not has_key(ref.name, ref.key)
	msg := sprintf("%s: container %s: env %s names secret %s key %s, which no ExternalSecret of this render makes", [id(pod.owner), c.name, e.name, ref.name, ref.key])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	some f in object.get(c, "envFrom", [])
	name := f.secretRef.name
	not made[name]
	msg := sprintf("%s: container %s: envFrom names secret %s, which no ExternalSecret of this render makes", [id(pod.owner), c.name, name])
}

deny contains msg if {
	some pod in pods
	some v in object.get(pod.spec, "volumes", [])
	name := v.secret.secretName
	not made[name]
	msg := sprintf("%s: volume %s names secret %s, which no ExternalSecret of this render makes", [id(pod.owner), v.name, name])
}

deny contains msg if {
	some pod in pods
	some v in object.get(pod.spec, "volumes", [])
	some item in object.get(v.secret, "items", [])
	not has_key(v.secret.secretName, item.key)
	msg := sprintf("%s: volume %s names key %s of secret %s, which its ExternalSecret does not make", [id(pod.owner), v.name, item.key, v.secret.secretName])
}

deny contains msg if {
	some pod in pods
	some v in object.get(pod.spec, "volumes", [])
	some source in object.get(object.get(v, "projected", {}), "sources", [])
	name := source.secret.name
	not made[name]
	msg := sprintf("%s: projected volume %s names secret %s, which no ExternalSecret of this render makes", [id(pod.owner), v.name, name])
}

deny contains msg if {
	some pod in pods
	some v in object.get(pod.spec, "volumes", [])
	some source in object.get(object.get(v, "projected", {}), "sources", [])
	some item in object.get(source.secret, "items", [])
	not has_key(source.secret.name, item.key)
	msg := sprintf("%s: projected volume %s names key %s of secret %s, which its ExternalSecret does not make", [id(pod.owner), v.name, item.key, source.secret.name])
}

deny contains msg if {
	some pod in pods
	some ref in object.get(pod.spec, "imagePullSecrets", [])
	not made[ref.name]
	msg := sprintf("%s: imagePullSecrets names secret %s, which no ExternalSecret of this render makes", [id(pod.owner), ref.name])
}

deny contains msg if {
	some obj in objects
	obj.kind == "ConfigMap"
	some key, _ in object.get(obj, "data", {})
	regex.match(secret_name, key)
	msg := sprintf("%s: key %s looks like a secret; put it in an ExternalSecret", [id(obj), key])
}

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	some e in object.get(c, "env", [])
	e.value
	regex.match(secret_name, e.name)
	msg := sprintf("%s: container %s: env %s looks like a secret but has a literal value", [id(pod.owner), c.name, e.name])
}

# A CSI volume reaches a secret past the ExternalSecrets: its driver credential (nodePublishSecretRef) is a Secret
# the render must make, and a secrets-store CSI driver mounts values from a store directly, which X8 routes through
# the External Secrets Operator instead.
deny contains msg if {
	some pod in pods
	some v in object.get(pod.spec, "volumes", [])
	name := v.csi.nodePublishSecretRef.name
	not made[name]
	msg := sprintf("%s: CSI volume %s names secret %s, which no ExternalSecret of this render makes", [id(pod.owner), v.name, name])
}

deny contains msg if {
	some pod in pods
	some v in object.get(pod.spec, "volumes", [])
	startswith(v.csi.driver, "secrets-store.")
	msg := sprintf("%s: CSI volume %s mounts secrets through %s; make them with an ExternalSecret", [id(pod.owner), v.name, v.csi.driver])
}

# An ExternalSecret's template is Git too: a key that looks like a secret takes its value from the store (a template
# expression), never a literal written there.
deny contains msg if {
	some es in objects
	es.kind == "ExternalSecret"
	some key, value in object.get(object.get(object.get(es.spec, "target", {}), "template", {}), "data", {})
	regex.match(secret_name, key)
	not contains(value, "{{")
	msg := sprintf("%s: template key %s looks like a secret but has a literal value; take it from the store", [id(es), key])
}
