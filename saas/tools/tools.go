// Package tools holds blank-import declarations for tooling dependencies
// that must stay pinned in go.mod even when no production code imports
// them.
//
// Today this carries one entry:
//
//   - github.com/quasilyte/go-ruleguard/dsl — loaded by gocritic's
//     ruleguard checker against `.golangci-rules/rules.go`. The rules file
//     itself uses `//go:build ruleguard` so `go mod tidy` never sees the
//     import; without this tools.go the dep would be pruned and lint would
//     fail to start.
//
// The build constraint below ensures this file is never part of any normal
// compilation — `go build ./...` skips it because no caller sets the
// `tools` tag, and `go mod tidy` still scans it because tidy processes
// every file regardless of build constraints.
//
//go:build tools

package tools

import (
	_ "github.com/quasilyte/go-ruleguard/dsl"
)
