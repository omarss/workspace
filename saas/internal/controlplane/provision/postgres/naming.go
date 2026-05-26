package postgres

import (
	"fmt"
	"strings"
)

// Postgres identifier limits. NAMEDATALEN-1 = 63 by default; we refuse
// names that hit the limit even after our DDL-quoted form, because a
// truncated identifier from a future longer slug would silently collide
// with another deployment.
const (
	maxIdentifierLen = 63
	dbNamePrefix     = "saas_"
	roleSuffix       = "_app"
)

// reservedNames are names the adapter refuses to provision against to
// avoid accidentally colliding with platform-internal databases on the
// host. The list is conservative — Postgres reserves the `pg_` prefix
// itself, so this catches operator slugs only.
var reservedNames = map[string]struct{}{
	"postgres":          {},
	"template0":         {},
	"template1":         {},
	"saas":              {}, // the host control-plane DB
	"saas_controlplane": {},
}

// validateSlug enforces the Postgres-identifier alphabet on slugs before
// they participate in name composition. The control-plane already
// constrains slugs to a DNS-safe alphabet (AGENTS.md §6.2), but slugs
// may legitimately contain `-` for DNS while Postgres identifiers do not
// support `-` without quoting; we collapse to [a-z0-9_] explicitly.
//
// Returns ErrInvalidInput so the caller sees a single sentinel for the
// "input was malformed" class of failure regardless of where in the
// pipeline the rejection happened.
func validateSlug(field, slug string) error {
	if slug == "" {
		return fmt.Errorf("%w: %s empty", ErrInvalidInput, field)
	}
	if len(slug) > 32 {
		// 32 is generous given the 63-char identifier limit minus
		// `saas_` (5) + `_` (1) + the longer of two slugs + `_app` (4).
		// Two 32-char slugs already exceed 63; the runtime length
		// check in buildDBName/buildRoleName catches the combination,
		// but reject obviously-too-long single slugs here.
		return fmt.Errorf("%w: %s %q exceeds 32 chars", ErrInvalidInput, field, slug)
	}
	// First char must be a letter — Postgres rejects identifiers that
	// start with a digit unless quoted with E-style which we do not
	// want to rely on for the embedded DDL.
	first := rune(slug[0])
	if first < 'a' || first > 'z' {
		return fmt.Errorf("%w: %s %q must start with [a-z]", ErrInvalidInput, field, slug)
	}
	for i, r := range slug {
		switch {
		case r >= 'a' && r <= 'z':
		case r >= '0' && r <= '9':
		case r == '_':
		default:
			return fmt.Errorf("%w: %s %q has invalid char at %d (must match [a-z0-9_])", ErrInvalidInput, field, slug, i)
		}
	}
	return nil
}

// buildDBName composes the per-Deployment database name from the slug
// pair. Surfaces ErrInvalidName when the combined length exceeds the
// Postgres identifier limit; the caller (Validate) catches this before
// any DDL is issued.
func buildDBName(projectSlug, envSlug string) (string, error) {
	name := dbNamePrefix + projectSlug + "_" + envSlug
	if len(name) > maxIdentifierLen {
		return "", fmt.Errorf("%w: db name %q exceeds %d chars", ErrInvalidName, name, maxIdentifierLen)
	}
	if _, reserved := reservedNames[name]; reserved {
		return "", fmt.Errorf("%w: db name %q is reserved", ErrInvalidName, name)
	}
	return name, nil
}

// buildRoleName composes the per-Deployment app role name. The role name
// is `<dbname>_app`; we re-validate the combined length because the
// `_app` suffix can push a borderline-OK DB name over the limit.
func buildRoleName(projectSlug, envSlug string) (string, error) {
	db, err := buildDBName(projectSlug, envSlug)
	if err != nil {
		return "", err
	}
	role := db + roleSuffix
	if len(role) > maxIdentifierLen {
		return "", fmt.Errorf("%w: role name %q exceeds %d chars", ErrInvalidName, role, maxIdentifierLen)
	}
	return role, nil
}

// quoteIdentifier returns a safely double-quoted Postgres identifier.
// Used everywhere we splice a name into DDL — every internal name has
// already passed validateSlug, so a `"` inside the name is impossible,
// but we still double any embedded quotes per the SQL standard as a
// belt-and-braces defense against a future code path that bypasses
// validateSlug.
func quoteIdentifier(name string) string {
	return `"` + strings.ReplaceAll(name, `"`, `""`) + `"`
}

// quoteLiteral returns a safely single-quoted SQL string literal. We use
// this for the PASSWORD value in CREATE ROLE / ALTER ROLE — Postgres
// does not accept passwords via parameter binding. The escape rule is
// the standard SQL one: double any embedded single quote. Combined with
// the controlled alphabet of generateRolePassword (URL-safe base64,
// no quote chars), this is a defense-in-depth measure.
func quoteLiteral(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "''") + "'"
}
