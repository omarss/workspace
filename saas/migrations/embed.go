// Package migrations exposes embedded SQL sources for the control plane
// and data plane migration runners. The runner under cmd/migrate consumes
// these via golang-migrate's iofs source driver.
//
// Forward-only convention: every migration is an *.up.sql file. Down
// migrations are allowed but not required (see AGENTS.md §25.4).
package migrations

import "embed"

// Controlplane embeds every forward-only SQL migration for the control plane.
//
//go:embed controlplane/*.up.sql
var Controlplane embed.FS

// Dataplane embeds every forward-only SQL migration for the data plane.
//
//go:embed dataplane/*.up.sql
var Dataplane embed.FS
