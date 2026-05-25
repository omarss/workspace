package organizations

import (
	"context"

	"github.com/omarss/saas/internal/dataplane/tenancy"
)

// TenantLookupAdapter bridges the organizations.TenantLookup port to the
// tenancy.Service read-side. The adapter is the only place that converts
// tenancy.Tenant into the narrow organizations.TenantBasic view; keeping
// it here avoids a circular dependency between tenancy and organizations.
//
// MultiOrg is read from tenant.metadata.multi_org per AGENTS.md §7.
// jsonb values come back as Go strings — we accept "true" / "1" (case
// insensitive) to keep the gate operator-friendly.
type TenantLookupAdapter struct {
	svc *tenancy.Service
}

// NewTenantLookupAdapter wires the adapter over the tenancy service.
func NewTenantLookupAdapter(svc *tenancy.Service) *TenantLookupAdapter {
	return &TenantLookupAdapter{svc: svc}
}

// GetTenantBasic implements organizations.TenantLookup. Resolves the
// tenant via the tenancy service and projects only the fields this module
// consumes.
func (a *TenantLookupAdapter) GetTenantBasic(ctx context.Context, tenantID string) (TenantBasic, error) {
	if a == nil || a.svc == nil {
		return TenantBasic{}, ErrNotFound
	}
	t, err := a.svc.Get(ctx, tenantID)
	if err != nil {
		return TenantBasic{}, err
	}
	multiOrg := false
	if v, ok := t.Metadata["multi_org"]; ok {
		switch v {
		case "true", "True", "TRUE", "1":
			multiOrg = true
		}
	}
	out := TenantBasic{
		ID:                    t.ID,
		Name:                  t.Name,
		Slug:                  t.Slug,
		DefaultOrganizationID: t.DefaultOrganizationID,
		MultiOrg:              multiOrg,
	}
	return out, nil
}
