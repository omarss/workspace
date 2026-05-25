package deployments

// Test-support exports. These type aliases give the external _test
// package access to the minimal pgx-shaped surface the LocalProvisioner
// depends on, without exposing pgx types to callers.
//
// Keeping the aliases in the production package (instead of a _test.go
// file) lets compile-time interface assertions cover the same shape the
// real implementation uses.

// HostDBForTest is the test-visible alias of the unexported hostDB
// interface so tests can construct fakes that satisfy it.
type HostDBForTest = hostDB

// RowForTest is the test-visible alias of the row interface returned by
// QueryRow.
type RowForTest = row

// CommandTagForTest is the test-visible alias of commandTag returned by
// Exec.
type CommandTagForTest = commandTag
