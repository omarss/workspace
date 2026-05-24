// Package migrations exposes embedded SQL sources for the control plane
// and data plane migration runners. The runner under cmd/migrate consumes
// these via golang-migrate's iofs source driver.
//
// Forward-only convention: every migration is an *.up.sql file. Down
// migrations are allowed but not required (see AGENTS.md §25.4).
package migrations

import "embed"

// Controlplane embeds every SQL migration for the control plane. Both
// *.up.sql and *.down.sql are included so golang-migrate's iofs source can
// drive `migrate down` from inside the compiled binary.
//
//go:embed controlplane/*.sql
var Controlplane embed.FS

// Dataplane embeds every SQL migration for the data plane (up + down).
//
//go:embed dataplane/*.sql
var Dataplane embed.FS
