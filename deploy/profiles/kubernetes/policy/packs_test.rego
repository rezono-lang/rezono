# Unit tests of packs.rego: one input that passes, and for every rule one change that it must refuse.
package packs

import rego.v1

access_roles := {"checker": "complete", "viewer": "may_read", "editor": "may_read"}

profile_file(publish, live) := profile_with_roles(publish, live, access_roles)

profile_with_roles(publish, live, access) := {
	"path": "/repo/deploy/profiles/kubernetes.yaml",
	"contents": {
		"profile": "kubernetes",
		"access": {"roles": access},
		"publish": {"classes": ["unclassified"], "packs": publish},
		"live": {"packs": live},
	},
}

pack_file(dir, name) := {"path": sprintf("/repo/%s/pack.yaml", [dir]), "contents": {"name": name, "version": "0.1.0"}}

packs := [pack_file("examples/one", "pack-one"), pack_file("examples/deep/two", "pack-two"), pack_file("examples/three", "pack-three")]

gate(env) := {
	"apiVersion": "apps/v1",
	"kind": "Deployment",
	"metadata": {"name": "gate"},
	"spec": {"template": {"spec": {"containers": [
		{"name": "gate", "envFrom": [{"configMapRef": {"name": "gate-abc"}}], "env": env},
		{"name": "engine", "env": [{"name": "REZONO_PACKS", "value": "not-the-gate"}]},
	]}}},
}

config(values) := {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "gate-abc"}, "data": values}

other := {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "viewer-abc"}, "data": {"REZONO_PACKS": "not-the-gate"}}

settings := {
	"REZONO_PACKS": "pack-one,pack-two",
	"REZONO_PROPOSE_PACKS": "pack-two=examples/deep/two",
	"REZONO_LIVE_PACKS": "pack-one",
	"REZONO_ROLES": "editor,viewer",
	"REZONO_ROLE_GROUPS": "viewer=readers;editor=editors,leads",
}

# One entry per document of the render, as conftest --combine gives them.
inputs(objs, publish, live) := array.concat([{"path": "/work/example.yaml", "contents": obj} | some obj in objs], array.concat([profile_file(publish, live)], packs))

good := inputs([gate([]), config(settings), other], ["examples/one", "examples/deep/two"], ["examples/one"])

with_settings(values) := inputs([gate([]), config(values), other], ["examples/one", "examples/deep/two"], ["examples/one"])

put(o, k, v) := object.union(object.remove(o, [k]), {k: v})

refused(inp, text) if {
	msgs := deny with input as inp
	some m in msgs
	contains(m, text)
}

test_the_gate_serves_what_the_profile_publishes if {
	msgs := deny with input as good
	count(msgs) == 0
}

test_a_render_as_one_list_and_paths_from_the_root_pass if {
	msgs := deny with input as [
		{"path": "example.yaml", "contents": [gate([]), config(settings)]},
		{"path": "deploy/profiles/kubernetes.yaml", "contents": profile_file(["examples/one", "examples/deep/two"], ["examples/one"]).contents},
		{"path": "examples/one/pack.yaml", "contents": {"name": "pack-one"}},
		{"path": "examples/deep/two/pack.yaml", "contents": {"name": "pack-two"}},
	]
	count(msgs) == 0
}

test_no_live_and_no_proposals_pass if {
	msgs := deny with input as with_settings({"REZONO_PACKS": " pack-one , pack-two ", "REZONO_ROLES": " viewer , editor "})
	count(msgs) == 0
}

test_a_pack_only_in_the_profile_is_refused if refused(inputs([gate([]), config(settings), other], ["examples/one", "examples/deep/two", "examples/three"], ["examples/one"]), "the same names in the same order")

test_a_pack_only_in_the_gate_is_refused if refused(with_settings(put(settings, "REZONO_PACKS", "pack-one,pack-two,pack-three")), "REZONO_PACKS [\"pack-one\", \"pack-two\", \"pack-three\"]")

test_another_order_is_refused if refused(with_settings(put(settings, "REZONO_PACKS", "pack-two,pack-one")), "the same names in the same order")

test_a_directory_instead_of_a_name_is_refused if refused(with_settings(put(settings, "REZONO_PACKS", "examples/one,examples/deep/two")), "the same names in the same order")

test_every_pack_in_the_store_is_refused if refused(with_settings(put(settings, "REZONO_PACKS", "*")), "REZONO_PACKS [\"*\"]")

test_no_setting_is_refused if refused(with_settings(object.remove(settings, ["REZONO_PACKS"])), "the gate has no REZONO_PACKS")

test_a_literal_wins_over_the_config_map if refused(inputs([gate([{"name": "REZONO_PACKS", "value": "pack-one"}]), config(settings), other], ["examples/one", "examples/deep/two"], ["examples/one"]), "REZONO_PACKS [\"pack-one\"]")

test_no_gate_is_refused if refused(inputs([config(settings)], ["examples/one"], []), "no Deployment `gate`")

test_no_profile_is_refused if refused(array.concat([{"path": "/work/example.yaml", "contents": gate([])}, {"path": "/work/example.yaml", "contents": config(settings)}], packs), "kubernetes.yaml is not in the input")

test_a_profile_pack_without_pack_yaml_is_refused if refused(inputs([gate([]), config(settings), other], ["examples/one", "examples/deep/two", "examples/gone"], ["examples/one"]), "no examples/gone/pack.yaml")

test_live_packs_other_than_the_engines_are_refused if refused(with_settings(put(settings, "REZONO_LIVE_PACKS", "pack-one,pack-two")), "REZONO_LIVE_PACKS [\"pack-one\", \"pack-two\"]")

test_a_live_pack_that_is_not_served_is_refused if refused(inputs([gate([]), config(put(settings, "REZONO_LIVE_PACKS", "pack-three")), other], ["examples/one", "examples/deep/two"], ["examples/three"]), "REZONO_LIVE_PACKS names pack-three, which REZONO_PACKS does not")

# The roles: the gate's REZONO_ROLES against the profile's reader roles.
roles_against(access) := array.concat(
	[{"path": "/work/example.yaml", "contents": obj} | some obj in [gate([]), config(settings), other]],
	array.concat([profile_with_roles(["examples/one", "examples/deep/two"], ["examples/one"], access)], packs),
)

test_a_role_only_in_the_gate_is_refused if refused(with_settings(put(settings, "REZONO_ROLES", "propose,editor,viewer")), "they are the same roles")

test_a_role_only_in_the_profile_is_refused if refused(roles_against(put(access_roles, "propose", "may_read")), "they are the same roles")

test_the_complete_role_is_refused if refused(with_settings(put(settings, "REZONO_ROLES", "checker,editor,viewer")), "REZONO_ROLES [\"checker\", \"editor\", \"viewer\"]")

test_a_role_named_twice_is_refused if refused(with_settings(put(settings, "REZONO_ROLES", "editor,viewer,editor")), "names a role twice")

test_no_roles_is_refused if refused(with_settings(object.remove(settings, ["REZONO_ROLES"])), "the gate has no REZONO_ROLES")

test_groups_for_a_role_that_is_not_served_are_refused if refused(with_settings(put(settings, "REZONO_ROLE_GROUPS", "viewer=readers;propose=proposers")), "gives groups to the role propose")

test_a_proposal_pack_that_is_not_served_is_refused if refused(with_settings(put(settings, "REZONO_PROPOSE_PACKS", "pack-three=examples/three")), "REZONO_PROPOSE_PACKS names pack-three, which REZONO_PACKS does not")
