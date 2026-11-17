# Unit tests of configmaps.rego, with the small render of policy_test.rego.
package main

import rego.v1

config_map(ns, name) := {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name, "namespace": ns}, "data": {"A": "1"}}

in_ns(obj, ns) := object.union(obj, {"metadata": {"namespace": ns}})

# The render with one pod in namespace `n` whose container and volumes are given, and the ConfigMaps given.
config_render(c, volumes, maps) := render(array.concat(
	[namespace, deny_all, external_secret, in_ns(deployment(put(put(pod_spec, "containers", [c]), "volumes", volumes)), "n")],
	maps,
))

from_map(name) := put(container, "envFrom", [{"configMapRef": {"name": name}}])

key_of(name, key) := put(container, "env", [{"name": "A", "valueFrom": {"configMapKeyRef": {"name": name, "key": key}}}])

config_msgs(inp) := {m | some m in deny with input as inp; contains(m, "ConfigMap")}

test_a_config_map_of_the_render_passes if {
	count(config_msgs(config_render(from_map("m-abc"), [{"name": "v", "configMap": {"name": "m-abc"}}], [config_map("n", "m-abc")]))) == 0
	count(config_msgs(config_render(key_of("m-abc", "A"), [], [config_map("n", "m-abc")]))) == 0
}

test_an_unmade_config_map_is_refused if {
	some m in config_msgs(config_render(from_map("m"), [], [config_map("n", "m-abc")]))
	contains(m, "envFrom names ConfigMap m,")
}

test_a_config_map_without_the_pods_namespace_is_refused if {
	some m in config_msgs(config_render(from_map("m-abc"), [], [object.remove(config_map("n", "m-abc"), ["metadata"]) | {"metadata": {"name": "m-abc"}}]))
	contains(m, "envFrom names ConfigMap m-abc,")
}

test_an_unmade_key_is_refused if {
	some m in config_msgs(config_render(key_of("m-abc", "B"), [], [config_map("n", "m-abc")]))
	contains(m, "ConfigMap m-abc key B")
}

test_an_unmade_volume_is_refused if {
	some m in config_msgs(config_render(container, [{"name": "v", "projected": {"sources": [{"configMap": {"name": "gone"}}]}}], []))
	contains(m, "volume v names ConfigMap gone")
}

test_an_optional_config_map_passes if {
	count(config_msgs(config_render(put(container, "envFrom", [{"configMapRef": {"name": "m", "optional": true}}]), [], []))) == 0
}
