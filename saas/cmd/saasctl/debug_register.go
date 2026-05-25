// Build-tag-gated registration of the `saasctl debug` subtree. In `prod`
// builds the register function is a no-op (see debug_register_prod.go),
// so the production binary literally cannot run `saasctl debug ...`.

//go:build !prod

package main

import "github.com/spf13/cobra"

// registerDebug attaches the Phase-12 verification helpers. Called from
// main() during cobra root setup.
func registerDebug(root *cobra.Command) {
	root.AddCommand(debugCmd())
}
