# Helpers for the policies of profile `kubernetes` (README.md#the-policies). conftest runs with --combine, so
# `input` is a list of {path, contents}; a multi-document file's contents is a list of objects.
package main

import rego.v1

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

id(obj) := sprintf("%s %s", [obj.kind, obj.metadata.name])

# Every pod template in the render, with the object it belongs to.
pods contains {"owner": obj, "spec": obj.spec.template.spec, "serves": true} if {
	some obj in objects
	obj.kind in {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"}
}

pods contains {"owner": obj, "spec": obj.spec.template.spec, "serves": false} if {
	some obj in objects
	obj.kind == "Job"
}

pods contains {"owner": obj, "spec": obj.spec.jobTemplate.spec.template.spec, "serves": false} if {
	some obj in objects
	obj.kind == "CronJob"
}

pods contains {"owner": obj, "spec": obj.spec, "serves": true} if {
	some obj in objects
	obj.kind == "Pod"
}

known_workloads := {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob", "Pod"}

# A kind not listed above that carries a pod template (a ReplicationController, an operator's own kind) would pass
# every rule unseen: it is refused until it is listed here (policy/pods.rego).
template_paths := [["spec", "containers"], ["spec", "template", "spec", "containers"], ["spec", "jobTemplate", "spec", "template", "spec", "containers"]]

unknown_workloads contains obj if {
	some obj in objects
	not obj.kind in known_workloads
	some path in template_paths
	is_array(object.get(obj, path, null))
}

# Every container of a pod: ordinary, init and ephemeral.
containers(spec) := array.concat(array.concat(object.get(spec, "containers", []), object.get(spec, "initContainers", [])), object.get(spec, "ephemeralContainers", []))
