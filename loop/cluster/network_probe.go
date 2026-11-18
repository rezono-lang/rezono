// The shared fixture's local TCP listener, dial probe and JSON-lines recorder.
package main

import (
	"fmt"
	"io"
	"net"
	"os"
	"time"
)

func serve(ports []string) error {
	if len(ports) == 0 {
		return fmt.Errorf("at least one TCP listener port is required")
	}
	var listeners []net.Listener
	for _, port := range ports {
		listener, err := net.Listen("tcp4", ":"+port)
		if err != nil {
			return err
		}
		defer listener.Close()
		listeners = append(listeners, listener)
	}
	failed := make(chan error, 1)
	for _, listener := range listeners {
		go func(listener net.Listener) {
			for {
				conn, err := listener.Accept()
				if err != nil {
					failed <- err
					return
				}
				conn.Close()
			}
		}(listener)
	}
	return <-failed
}

func probe(args []string) error {
	if len(args) != 2 {
		return fmt.Errorf("a destination address and port are required")
	}
	conn, err := net.DialTimeout("tcp4", net.JoinHostPort(args[0], args[1]), 2*time.Second)
	switch {
	case err == nil:
		conn.Close()
		fmt.Println("0")
	case os.IsTimeout(err):
		fmt.Println("124")
	default:
		fmt.Fprintln(os.Stderr, err)
		fmt.Println("1")
	}
	return nil
}

func record(args []string) error {
	if len(args) != 1 {
		return fmt.Errorf("an evidence file is required")
	}
	source, err := os.Open(args[0])
	if err != nil {
		return err
	}
	defer source.Close()
	_, err = io.Copy(os.Stdout, source)
	return err
}

func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("expected serve, probe or record")
	}
	switch args[0] {
	case "serve":
		return serve(args[1:])
	case "probe":
		return probe(args[1:])
	case "record":
		return record(args[1:])
	default:
		return fmt.Errorf("unsupported command %q", args[0])
	}
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
