# The images' recipes (deploy/gate, deploy/viewer, deploy/engine), checked before any image is built: the same
# rules the manifests meet (images.rego, pods.rego), held at the source. check.sh runs conftest with
# --parser dockerfile --combine --namespace containerfile, so `input` is a list of {path, contents}, and contents is
# the file's instructions in order, each {Cmd, Value, Stage, ...}.
package containerfile

import rego.v1

digest_pattern := `^[^@\s]+@sha256:[0-9a-f]{64}$`

# A numeric user and group that is not root: a pod's runAsNonRoot can only verify a number.
user_pattern := `^[1-9][0-9]*(:[1-9][0-9]*)?$`

secret_name := `(?i)(token|secret|passw(or)?d|private_?key|api_?key|credential)`

instructions(file) := [i | some i in file.contents; i.Cmd != "comment"]

# Stage names a later FROM may name instead of an image.
stages(file) := {lower(i.Value[2]) |
	some i in instructions(file)
	i.Cmd == "from"
	count(i.Value) == 3
	lower(i.Value[1]) == "as"
}

last_stage(file) := max({i.Stage | some i in instructions(file)})

# Pinned and reproducible (AGENTS.md, non-negotiable 6): every base image by digest, or an earlier stage.
deny contains msg if {
	some file in input
	some i in instructions(file)
	i.Cmd == "from"
	image := i.Value[0]
	not lower(image) in stages(file)
	not regex.match(digest_pattern, image)
	msg := sprintf("%s: FROM %q is not pinned by digest (name@sha256:<64 hex>)", [file.path, image])
}

# Non-root by construction: the stage that is the image ends with a numeric user other than 0.
deny contains msg if {
	some file in input
	users := [i | some i in instructions(file); i.Cmd == "user"; i.Stage == last_stage(file)]
	count(users) == 0
	msg := sprintf("%s: the final stage sets no USER; the image would run as root", [file.path])
}

deny contains msg if {
	some file in input
	users := [i | some i in instructions(file); i.Cmd == "user"; i.Stage == last_stage(file)]
	count(users) > 0
	user := users[count(users) - 1].Value[0]
	not regex.match(user_pattern, user)
	msg := sprintf("%s: the final USER %q is not a numeric user and group other than root (uid:gid)", [file.path, user])
}

# COPY only: ADD fetches URLs and unpacks archives, which no digest or lock covers.
deny contains msg if {
	some file in input
	some i in instructions(file)
	i.Cmd == "add"
	msg := sprintf("%s: ADD %v; use COPY of a file in the context", [file.path, i.Value])
}

# No secret in a layer: a build argument or an environment variable named like one is readable in the image.
deny contains msg if {
	some file in input
	some i in instructions(file)
	i.Cmd == "arg"
	some v in i.Value
	name := split(v, "=")[0]
	regex.match(secret_name, name)
	msg := sprintf("%s: ARG %s looks like a secret; a secret comes from the pod (an ExternalSecret), never the image", [file.path, name])
}

deny contains msg if {
	some file in input
	some i in instructions(file)
	i.Cmd == "env"
	some k, name in i.Value
	k % 2 == 0
	regex.match(secret_name, name)
	msg := sprintf("%s: ENV %s looks like a secret; a secret comes from the pod (an ExternalSecret), never the image", [file.path, name])
}

# The process is the entry point itself, in exec form, so it gets the pod's signals (no shell in between).
deny contains msg if {
	some file in input
	entries := [i | some i in instructions(file); i.Cmd == "entrypoint"; i.Stage == last_stage(file)]
	count(entries) == 0
	msg := sprintf("%s: the final stage has no ENTRYPOINT", [file.path])
}

deny contains msg if {
	some file in input
	some i in instructions(file)
	i.Cmd in {"entrypoint", "cmd"}
	not i.JSON
	msg := sprintf("%s: %s %v is in shell form; use the exec form [\"...\"]", [file.path, upper(i.Cmd), i.Value])
}
