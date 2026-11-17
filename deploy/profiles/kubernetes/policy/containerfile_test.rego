# Unit tests of containerfile.rego: a recipe that passes, and for every rule one change that it must refuse.
package containerfile

import rego.v1

base := "node:24@sha256:1111111111111111111111111111111111111111111111111111111111111111"

ins(cmd, value, stage) := {"Cmd": cmd, "Value": value, "Stage": stage, "JSON": false, "Flags": [], "SubCmd": ""}

exec(cmd, value, stage) := object.union(ins(cmd, value, stage), {"JSON": true})

good := [
	{"Cmd": "comment", "Value": ["a recipe"], "Stage": 0, "JSON": false, "Flags": null, "SubCmd": ""},
	ins("from", [base, "AS", "build"], 0),
	ins("run", ["npm ci"], 0),
	ins("from", [base], 1),
	ins("copy", ["--from=build", "/a", "/a"], 1),
	ins("user", ["1000:1000"], 1),
	ins("env", ["NODE_ENV", "production", "PORT", "8080"], 1),
	exec("entrypoint", ["node", "a.js"], 1),
]

recipe(instructions) := [{"path": "Containerfile", "contents": instructions}]

# good with the instruction at position n replaced, or appended when n is the length.
with_at(n, i) := array.concat(array.slice(good, 0, n), array.concat([i], array.slice(good, n + 1, count(good))))

refused(inp, text) if {
	msgs := deny with input as inp
	some m in msgs
	contains(m, text)
}

test_a_good_recipe_passes if {
	msgs := deny with input as recipe(good)
	count(msgs) == 0
}

test_a_later_stage_may_name_an_earlier_one if {
	msgs := deny with input as recipe(with_at(3, ins("from", ["BUILD"], 1)))
	count(msgs) == 0
}

test_a_tag_is_refused if refused(recipe(with_at(1, ins("from", ["node:24", "AS", "build"], 0))), "not pinned by digest")

test_a_stage_name_of_another_file_is_refused if refused(recipe(with_at(3, ins("from", ["other"], 1))), "not pinned by digest")

test_no_user_is_refused if refused(recipe(with_at(5, ins("run", ["true"], 1))), "sets no USER")

test_a_user_of_the_build_stage_only_is_refused if {
	only_build := array.concat([ins("user", ["1000"], 0)], with_at(5, ins("run", ["true"], 1)))
	refused(recipe(only_build), "sets no USER")
}

test_a_user_name_is_refused if refused(recipe(with_at(5, ins("user", ["node"], 1))), "not a numeric user")

test_root_is_refused if refused(recipe(with_at(5, ins("user", ["0:0"], 1))), "not a numeric user")

test_group_root_is_refused if refused(recipe(with_at(5, ins("user", ["1000:0"], 1))), "not a numeric user")

test_root_after_a_user_is_refused if {
	again := array.concat(array.slice(good, 0, 6), array.concat([ins("user", ["0"], 1)], array.slice(good, 6, count(good))))
	refused(recipe(again), "not a numeric user")
}

test_add_is_refused if refused(recipe(with_at(2, ins("add", ["https://example.org/x.tgz", "/x"], 0))), "use COPY")

test_a_secret_argument_is_refused if refused(recipe(with_at(2, ins("arg", ["NPM_TOKEN=x"], 0))), "ARG NPM_TOKEN")

test_a_secret_variable_is_refused if refused(recipe(with_at(6, ins("env", ["PORT", "8080", "DB_PASSWORD", "x"], 1))), "ENV DB_PASSWORD")

test_a_value_that_names_a_secret_is_not_a_secret if {
	msgs := deny with input as recipe(with_at(6, ins("env", ["HINT", "token"], 1)))
	count(msgs) == 0
}

test_no_entrypoint_is_refused if refused(recipe(with_at(7, ins("run", ["true"], 1))), "no ENTRYPOINT")

test_a_shell_entrypoint_is_refused if refused(recipe(with_at(7, ins("entrypoint", ["node a.js"], 1))), "shell form")

test_a_shell_cmd_is_refused if {
	shell := array.concat(good, [ins("cmd", ["--port 1"], 1)])
	refused(recipe(shell), "shell form")
}
