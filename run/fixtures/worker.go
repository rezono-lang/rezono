package main

import (
	"fmt"
	"os"

	"github.com/k0sproject/k0smotron/v2/internal/provisioner"
)

func main() {
	renderer := provisioner.IgnitionProvisioner{Variant: "flatcar", Version: "1.1.0"}
	result, err := renderer.ToProvisionData(&provisioner.InputProvisionData{
		Files: []provisioner.File{{Path: "/etc/rezono-probe", Content: "worker", Permissions: "0644"}},
		Commands: []string{"/opt/bin/k0s version"},
	})
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	os.Stdout.Write(result)
}
