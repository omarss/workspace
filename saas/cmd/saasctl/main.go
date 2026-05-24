// Command saasctl is the operator CLI for the SaaS control plane.
//
// Phase 1 ships only `saasctl version`. The full command surface
// (init wizard, deployment CRUD, vault helpers) lands in later phases.
package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"
)

func main() {
	root := &cobra.Command{
		Use:   "saasctl",
		Short: "Operator CLI for the SaaS control plane.",
	}
	root.AddCommand(&cobra.Command{
		Use:   "version",
		Short: "Print version.",
		Run:   func(*cobra.Command, []string) { fmt.Println("saasctl dev") },
	})
	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}
