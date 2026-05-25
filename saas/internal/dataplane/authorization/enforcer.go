package authorization

import (
	"context"
	_ "embed"
	"errors"
	"fmt"
	"sync"

	"github.com/casbin/casbin/v2"
	casbinmodel "github.com/casbin/casbin/v2/model"
	"github.com/casbin/casbin/v2/persist"
	"github.com/jackc/pgx/v5/pgxpool"
	pgxadapter "github.com/pckhoi/casbin-pgx-adapter/v3"
)

// modelText is the RBAC-with-domains Casbin model. Shipped in-binary so
// operators can't swap it at runtime (anti-pattern guard from the Phase 8
// plan: the model file is never edited live).
//
//go:embed rbac.conf
var modelText string

// wildcardDomainToken is the token whose presence in tenant_id is treated
// as a privilege-escalation attempt. The DB CHECK constraint rejects the
// underlying row; this guard refuses before the round-trip.
const wildcardDomainToken = "*"

// CasbinEnforcer is the Casbin-backed PolicyStore implementation. One
// instance per data-plane process (lifecycle owned by cmd/dataplane).
// EnableAutoSave is on so AddPolicy / RemovePolicy / AddGroupingPolicy /
// RemoveGroupingPolicy mutate both the in-memory cache and the DB.
//
// Single-replica MVP: LoadPolicy is called once on construction. ADR 005
// documents that a Redis watcher (casbin/redis-watcher/v2) is the chosen
// mechanism when scaling to multiple replicas; until then a second
// process would diverge until the next process restart.
type CasbinEnforcer struct {
	mu sync.Mutex
	e  *casbin.Enforcer
}

// NewCasbinEnforcer constructs the enforcer over the per-Deployment pool
// using pckhoi/casbin-pgx-adapter v3. The adapter's table-create path is
// disabled because our migration owns the schema (CHECK constraints +
// custom indexes the adapter would not emit).
func NewCasbinEnforcer(ctx context.Context, pool *pgxpool.Pool) (*CasbinEnforcer, error) {
	m, err := casbinmodel.NewModelFromString(modelText)
	if err != nil {
		return nil, fmt.Errorf("authorization: parse model: %w", err)
	}
	// WithConnectionPool reuses the data-plane pool — every connection
	// goes through pgxpool.NewPool which sets app.current_tenant_id via
	// PrepareConn. Casbin's LoadPolicy reads all rows in one shot so RLS
	// would refuse the read; the adapter operates outside the tenant
	// guc by design (the casbin_rule table is intentionally NOT
	// RLS-protected — tenant scoping is encoded in v1/v2 columns).
	//
	// WithSkipTableCreate stops the adapter from running its own
	// CREATE TABLE — our migration owns the schema with the wildcard
	// CHECK constraint the adapter cannot reproduce.
	a, err := pgxadapter.NewAdapter(
		nil,
		pgxadapter.WithConnectionPool(pool),
		pgxadapter.WithTableName("casbin_rule"),
		pgxadapter.WithSchema("public"),
		pgxadapter.WithSkipTableCreate(),
	)
	if err != nil {
		return nil, fmt.Errorf("authorization: adapter: %w", err)
	}
	e, err := casbin.NewEnforcer(m, a)
	if err != nil {
		return nil, fmt.Errorf("authorization: enforcer: %w", err)
	}
	e.EnableAutoSave(true)
	if err := e.LoadPolicy(); err != nil {
		return nil, fmt.Errorf("authorization: load policy: %w", err)
	}
	return &CasbinEnforcer{e: e}, nil
}

// NewCasbinEnforcerFromAdapter is the test seam: callers (unit tests)
// can pass an in-memory adapter so the enforcer logic runs without a
// live Postgres. Production callers use NewCasbinEnforcer.
func NewCasbinEnforcerFromAdapter(adapter persist.Adapter) (*CasbinEnforcer, error) {
	m, err := casbinmodel.NewModelFromString(modelText)
	if err != nil {
		return nil, fmt.Errorf("authorization: parse model: %w", err)
	}
	e, err := casbin.NewEnforcer(m, adapter)
	if err != nil {
		return nil, fmt.Errorf("authorization: enforcer: %w", err)
	}
	e.EnableAutoSave(true)
	if err := e.LoadPolicy(); err != nil {
		return nil, fmt.Errorf("authorization: load policy: %w", err)
	}
	return &CasbinEnforcer{e: e}, nil
}

// Check evaluates whether memberID has (resourceType, action) inside
// tenantID. Returns (allowed, matchedRoleID, err). When allowed is
// false the role id is empty.
func (c *CasbinEnforcer) Check(_ context.Context, memberID, tenantID, resourceType, action string) (bool, string, error) {
	if err := guardDomain(tenantID); err != nil {
		return false, "", err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	sub := FormatSubject(memberID)
	ok, matched, err := c.e.EnforceEx(sub, tenantID, resourceType, action)
	if err != nil {
		return false, "", fmt.Errorf("authorization: enforce: %w", err)
	}
	if !ok {
		return false, "", nil
	}
	// matched is the matched p-row: [sub, dom, obj, act]. sub is the role id.
	if len(matched) == 0 {
		return ok, "", nil
	}
	return ok, matched[0], nil
}

// AddRolePolicy persists a p-row granting roleID (resourceType, action)
// within tenantID.
func (c *CasbinEnforcer) AddRolePolicy(_ context.Context, roleID, tenantID, resourceType, action string) error {
	if err := guardDomain(tenantID); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	_, err := c.e.AddPolicy(roleID, tenantID, resourceType, action)
	if err != nil {
		return fmt.Errorf("authorization: add policy: %w", err)
	}
	return nil
}

// RemoveRolePolicy removes a p-row.
func (c *CasbinEnforcer) RemoveRolePolicy(_ context.Context, roleID, tenantID, resourceType, action string) error {
	if err := guardDomain(tenantID); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	_, err := c.e.RemovePolicy(roleID, tenantID, resourceType, action)
	if err != nil {
		return fmt.Errorf("authorization: remove policy: %w", err)
	}
	return nil
}

// RemoveAllRolePolicies clears every p-row for roleID inside tenantID.
// Used by UpdateRole's set-replace semantics and by DeleteRole.
func (c *CasbinEnforcer) RemoveAllRolePolicies(_ context.Context, roleID, tenantID string) error {
	if err := guardDomain(tenantID); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	// RemoveFilteredPolicy(fieldIndex, fieldValues...) — index 0 is
	// `sub`; index 1 is `dom`. Filtering on both pins the rows to this
	// (role, tenant) pair.
	_, err := c.e.RemoveFilteredPolicy(0, roleID, tenantID)
	if err != nil {
		return fmt.Errorf("authorization: clear policies: %w", err)
	}
	return nil
}

// AssignRole creates a g-row binding member->role within tenant.
func (c *CasbinEnforcer) AssignRole(_ context.Context, memberID, roleID, tenantID string) error {
	if err := guardDomain(tenantID); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	_, err := c.e.AddGroupingPolicy(FormatSubject(memberID), roleID, tenantID)
	if err != nil {
		return fmt.Errorf("authorization: assign role: %w", err)
	}
	return nil
}

// UnassignRole removes the g-row.
func (c *CasbinEnforcer) UnassignRole(_ context.Context, memberID, roleID, tenantID string) error {
	if err := guardDomain(tenantID); err != nil {
		return err
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	_, err := c.e.RemoveGroupingPolicy(FormatSubject(memberID), roleID, tenantID)
	if err != nil {
		return fmt.Errorf("authorization: unassign role: %w", err)
	}
	return nil
}

// guardDomain refuses empty or wildcard tenant ids. The DB CHECK
// constraint enforces the same invariant at the storage layer; this
// guard runs first so the round-trip is avoided and the error is
// distinguishable from a generic constraint violation.
func guardDomain(tenantID string) error {
	if tenantID == "" {
		return errors.New("authorization: tenant id required")
	}
	if tenantID == wildcardDomainToken {
		return ErrWildcardDomain
	}
	return nil
}
