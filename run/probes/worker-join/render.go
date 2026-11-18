package main

import (
	"bytes"
	"fmt"
	"io"
	"os"

	"github.com/k0sproject/k0smotron/v2/internal/provisioner"
)

// Render the disposable controller's short-lived bootstrap input directly to
// the machine document. Neither input nor output belongs in an observation.
func main() {
	token, err := io.ReadAll(os.Stdin)
	if err != nil || len(bytes.TrimSpace(token)) == 0 {
		panic("missing disposable cluster bootstrap input")
	}
	renderer := provisioner.IgnitionProvisioner{Variant: "flatcar", Version: "1.1.0"}
	data, err := renderer.ToProvisionData(&provisioner.InputProvisionData{
		Files: []provisioner.File{
			{Path: "/etc/k0s-worker-token", Content: string(bytes.TrimSpace(token)), Permissions: "0600"},
			{Path: "/etc/hostname", Content: "proof-worker\n", Permissions: "0644"},
		},
		Commands: []string{
			"echo WORKER-STAGE-first_boot >/dev/ttyS0",
			"mkdir -p /opt/bin",
			"curl -fsSL --retry 2 --max-time 90 -o /opt/bin/k0s https://github.com/k0sproject/k0s/releases/download/v1.36.6+k0s.0/k0s-v1.36.6+k0s.0-amd64",
			"echo 60bac39d4ed8292adb8576a55866389cde4700f9be7d152587e15f8aa67c12fc /opt/bin/k0s | sha256sum -c -",
			"echo WORKER-STAGE-binary_verified >/dev/ttyS0",
			"chmod 0755 /opt/bin/k0s",
			"/opt/bin/k0s install worker --token-file /etc/k0s-worker-token --labels=probe.rezono.org/role=joined-worker --kubelet-extra-args=--hostname-override=proof-worker",
			"echo WORKER-STAGE-worker_installed >/dev/ttyS0",
			"systemctl start --no-block k0sworker",
		},
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, "failed to render worker Ignition")
		os.Exit(1)
	}
	if _, err := os.Stdout.Write(data); err != nil {
		os.Exit(1)
	}
}
