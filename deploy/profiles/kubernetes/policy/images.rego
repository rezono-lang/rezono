# Pinned and reproducible (AGENTS.md, non-negotiable 6): every image by its digest, never by a tag alone, so the
# same Git ref runs the same bytes.
package main

import rego.v1

digest_pattern := `^[^@\s]+@sha256:[0-9a-f]{64}$`

zero_digest := "sha256:0000000000000000000000000000000000000000000000000000000000000000"

deny contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	not regex.match(digest_pattern, c.image)
	msg := sprintf("%s: container %s: image %q is not pinned by digest (name@sha256:<64 hex>)", [id(pod.owner), c.name, c.image])
}

# The zero digest stands for an image that is not built yet (overlays/example). A real installation refuses it:
# check.sh --live runs conftest with --fail-on-warn.
warn contains msg if {
	some pod in pods
	some c in containers(pod.spec)
	endswith(c.image, sprintf("@%s", [zero_digest]))
	msg := sprintf("%s: container %s: image %q has the placeholder digest; the image build writes the real one", [id(pod.owner), c.name, c.image])
}
