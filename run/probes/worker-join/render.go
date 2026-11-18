package main

import (
	"bytes"
	"flag"
	"fmt"
	"io"
	"os"
	"regexp"

	"github.com/k0sproject/k0smotron/v2/internal/provisioner"
)

// Render the disposable controller's short-lived bootstrap input directly to
// the machine document. Neither input nor output belongs in an observation.
func main() {
	kubevirt := flag.Bool("kubevirt", false, "prepare the worker for the KubeVirt host trial")
	format := flag.String("format", "ignition", "machine document format")
	machine := flag.String("machine", "proof-worker", "node and host name")
	flag.Parse()
	if !regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`).MatchString(*machine) {
		fmt.Fprintln(os.Stderr, "expected a DNS host label")
		os.Exit(2)
	}
	token, err := io.ReadAll(os.Stdin)
	if err != nil || len(bytes.TrimSpace(token)) == 0 {
		panic("missing disposable cluster bootstrap input")
	}
	commands := []string{
		"echo WORKER-STAGE-first_boot >/dev/ttyS0",
		"mkdir -p /opt/bin",
		"curl -fsSL --retry 2 --max-time 90 -o /opt/bin/k0s https://github.com/k0sproject/k0s/releases/download/v1.36.6+k0s.0/k0s-v1.36.6+k0s.0-amd64",
		"echo 60bac39d4ed8292adb8576a55866389cde4700f9be7d152587e15f8aa67c12fc /opt/bin/k0s | sha256sum -c -",
		"echo WORKER-STAGE-binary_verified >/dev/ttyS0",
		"chmod 0755 /opt/bin/k0s",
	}
	install := "/opt/bin/k0s install worker"
	if *kubevirt {
		commands = append(commands, "modprobe kvm_intel || modprobe kvm_amd", "modprobe tun && modprobe vhost_net")
		install += " --kubelet-root-dir=/var/lib/kubelet"
	}
	commands = append(commands,
		install+" --token-file /etc/k0s-worker-token --labels=probe.rezono.org/role=joined-worker --kubelet-extra-args=--hostname-override="+*machine,
		"echo WORKER-STAGE-worker_installed >/dev/ttyS0",
		"systemctl start --no-block k0sworker",
	)
	input := &provisioner.InputProvisionData{
		Files: []provisioner.File{
			{Path: "/etc/k0s-worker-token", Content: string(bytes.TrimSpace(token)), Permissions: "0600"},
			{Path: "/etc/hostname", Content: *machine + "\n", Permissions: "0644"},
		},
		Commands: commands,
	}
	var data []byte
	switch *format {
	case "ignition":
		renderer := provisioner.IgnitionProvisioner{Variant: "flatcar", Version: "1.1.0"}
		data, err = renderer.ToProvisionData(input)
	case "cloud-init":
		// Cloud-init writes runcmd strings into one shell script. Stop before installing
		// the worker if download or digest verification fails.
		input.Commands = append([]string{"set -eu"}, input.Commands...)
		renderer := provisioner.CloudInitProvisioner{}
		data, err = renderer.ToProvisionData(input)
	default:
		fmt.Fprintln(os.Stderr, "unsupported worker provisioning format")
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "failed to render worker bootstrap document")
		os.Exit(1)
	}
	if _, err := os.Stdout.Write(data); err != nil {
		os.Exit(1)
	}
}
