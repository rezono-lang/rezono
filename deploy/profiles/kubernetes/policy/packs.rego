# The gate of a render serves exactly the packs profile kubernetes publishes: REZONO_PACKS is the
# deployed copy of publish.packs in deploy/profiles/kubernetes.yaml, by the name in each pack.yaml and in that order,
# as edge/publisher/tests/test_live_host.py holds it for profile edge. A name on one side only fails here, so a pack
# never stays on a site, or leaves it, by accident. The gate's own rule at start (edge/gate/src/config.ts, packsFrom)
# is repeated, so a render whose gate would not start is refused at review: the packs that take proposals and the
# packs the engine holds are served packs. The gate serves exactly the roles the profile publishes for a reader,
# so a role does not reach a site, or stay on it, by an overlay alone. check.sh runs conftest with --combine --namespace packs on one render,
# the profile and every pack.yaml, so `input` is a list of {path, contents}, one entry per YAML document.
package packs

import rego.v1

# A file by its path from the repository's root, however the caller named the root.
at(path, tail) if path == tail

at(path, tail) if endswith(path, sprintf("/%s", [tail]))

profile := file.contents if {
	some file in input
	at(file.path, "deploy/profiles/kubernetes.yaml")
}

# The name a pack gives itself, from the directory a profile names.
pack_name(dir) := file.contents.name if {
	some file in input
	at(file.path, sprintf("%s/pack.yaml", [dir]))
}

published := object.get(profile, ["publish", "packs"], [])

held := object.get(profile, ["live", "packs"], [])

# The roles the publisher writes a filtered snapshot for (access.roles, mode may_read). A `complete` role (the
# checker's) is for server use only: its snapshot is unfiltered, so no gate serves it.
readers := {role | some role, mode in object.get(profile, ["access", "roles"], {}); mode == "may_read"}

# The objects of the render (as lib.rego reads them: a document per entry, or a list of documents).
objects contains obj if {
	some file in input
	is_array(file.contents)
	some obj in file.contents
	is_object(obj)
}

objects contains obj if {
	some file in input
	is_object(file.contents)
	obj := file.contents
}

gate_containers contains c if {
	some obj in objects
	obj.kind == "Deployment"
	obj.metadata.name == "gate"
	some c in obj.spec.template.spec.containers
	c.name == "gate"
}

# A setting of the gate as the pod gets it: a literal in `env` wins over a ConfigMap in `envFrom` (Kubernetes' order).
literal(key) := value if {
	some c in gate_containers
	some e in object.get(c, "env", [])
	e.name == key
	value := e.value
}

mapped(key) := value if {
	some c in gate_containers
	some from in object.get(c, "envFrom", [])
	some obj in objects
	obj.kind == "ConfigMap"
	obj.metadata.name == from.configMapRef.name
	value := obj.data[key]
}

setting(key) := literal(key)

setting(key) := mapped(key) if not literal(key)

# `a, b` as the gate reads it: trimmed, empty parts dropped.
names(text) := [trim_space(part) | some part in split(text, ","); trim_space(part) != ""]

deny contains msg if {
	not profile
	msg := "deploy/profiles/kubernetes.yaml is not in the input"
}

deny contains msg if {
	count(gate_containers) == 0
	msg := "the render has no Deployment `gate` with a container `gate`: nothing to hold the profile's packs to"
}

deny contains msg if {
	count(gate_containers) > 0
	not setting("REZONO_PACKS")
	msg := "the gate has no REZONO_PACKS: it does not start without the packs it serves"
}

deny contains msg if {
	some dir in array.concat(published, held)
	not pack_name(dir)
	msg := sprintf("kubernetes.yaml names the pack %s, and no %s/pack.yaml with a name is in the input", [dir, dir])
}

deny contains msg if {
	served := names(setting("REZONO_PACKS"))
	want := [pack_name(dir) | some dir in published]
	served != want
	msg := sprintf("the gate serves REZONO_PACKS %v and kubernetes.yaml publishes %v (publish.packs, by name): they are the same names in the same order", [served, want])
}

deny contains msg if {
	live := names(setting("REZONO_LIVE_PACKS"))
	want := [pack_name(dir) | some dir in held]
	live != want
	msg := sprintf("the gate asks the engine for REZONO_LIVE_PACKS %v and the engine holds %v (live.packs of kubernetes.yaml, by name): they are the same names in the same order", [live, want])
}

deny contains msg if {
	served := names(setting("REZONO_PACKS"))
	some key in ["REZONO_PROPOSE_PACKS", "REZONO_LIVE_PACKS"]
	some item in names(setting(key))
	name := split(item, "=")[0]
	not name in served
	msg := sprintf("%s names %s, which REZONO_PACKS does not: the gate does not start", [key, name])
}

# The roles. The profile in Git is the truth: REZONO_ROLES names the profile's reader roles and no other, as
# REZONO_ROLES in edge/gate/wrangler.jsonc names those of edge.yaml. The gate's order (most specific first) is its
# own and access.roles is a map, so the names are compared as sets. A role the profile does not name has no
# snapshot of its own; a `complete` role would hand a reader every row.
deny contains msg if {
	count(gate_containers) > 0
	not setting("REZONO_ROLES")
	msg := "the gate has no REZONO_ROLES: it does not start without the roles it serves"
}

deny contains msg if {
	roles := names(setting("REZONO_ROLES"))
	{role | some role in roles} != readers
	msg := sprintf("the gate serves REZONO_ROLES %v and kubernetes.yaml publishes for the roles %v (access.roles, may_read): they are the same roles", [roles, sort(readers)])
}

deny contains msg if {
	roles := names(setting("REZONO_ROLES"))
	count(roles) != count({role | some role in roles})
	msg := sprintf("REZONO_ROLES %v names a role twice", [roles])
}

# REZONO_ROLE_GROUPS (`role=group,group;role2=group`, edge/gate/src/identity.ts) gives groups to served roles only.
deny contains msg if {
	roles := names(setting("REZONO_ROLES"))
	some part in split(setting("REZONO_ROLE_GROUPS"), ";")
	trim_space(part) != ""
	role := trim_space(split(part, "=")[0])
	not role in roles
	msg := sprintf("REZONO_ROLE_GROUPS gives groups to the role %s, which REZONO_ROLES does not serve", [role])
}
