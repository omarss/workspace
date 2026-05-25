// Production-build no-op for the `saasctl debug` registration. The
// `prod` build tag excludes both the registration AND the underlying
// command definitions (see debug_nginx.go), so the production binary
// neither links nor advertises the verification helpers.

//go:build prod

package main

import "github.com/spf13/cobra"

func registerDebug(_ *cobra.Command) {}
