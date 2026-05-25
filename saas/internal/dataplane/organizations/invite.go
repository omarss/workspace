package organizations

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/omarss/saas/internal/platform/auth"
	"github.com/omarss/saas/internal/platform/id"
)

// CreateInvitationInput is the application-level input to
// CreateInvitation. The handler builds it from the OpenAPI body.
type CreateInvitationInput struct {
	InviteeEmail     string
	ProposedRoleID   *string
	ExpiresInSeconds *int64
}

// CreateInvitation creates a new invitation, persists it with the
// invitee email envelope-encrypted, dispatches the invitation email via
// the Notifications module, and emits the member.invited audit event.
//
// The plaintext accept-token is returned ONLY in this single response —
// the caller MUST NOT log it. After the handler dispatches the email
// (or stores the token for a sync-mode SMTP retry), the plaintext is
// gone forever; DB rows hold only the sha256 hash and the 8-char prefix.
func (s *Service) CreateInvitation(ctx context.Context, tenantID, organizationID string, in CreateInvitationInput) (Invitation, string, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Invitation{}, "", err
	}
	inviter, ok := auth.PrincipalFromContext(ctx)
	if !ok || inviter.ActorID == "" {
		return Invitation{}, "", auth.ErrUnauthorized
	}

	email := strings.TrimSpace(in.InviteeEmail)
	if email == "" || !strings.Contains(email, "@") {
		return Invitation{}, "", ErrInvalidInput
	}
	if s.hasher != nil {
		email = s.hasher.Normalise(email)
	}

	// Confirm the organization belongs to the caller's tenant. Hides
	// existence of cross-tenant orgs (returns ErrNotFound).
	org, err := s.orgs.Get(ctx, tenantID, organizationID)
	if err != nil {
		return Invitation{}, "", err
	}
	if org.Status != OrganizationStatusActive {
		return Invitation{}, "", ErrInvalidInput
	}

	ttl := DefaultInvitationTTL
	if in.ExpiresInSeconds != nil {
		want := time.Duration(*in.ExpiresInSeconds) * time.Second
		if want < MinInvitationTTL || want > MaxInvitationTTL {
			return Invitation{}, "", ErrInvalidInput
		}
		ttl = want
	}

	// HMAC-SHA256 the email for uniqueness lookup. The hasher port is
	// shared with Identity so a future "invite -> user" linkage can
	// resolve via the same hash.
	if s.hasher == nil {
		return Invitation{}, "", errors.New("organizations: EmailHasher port not wired")
	}
	emailHash, err := s.hasher.Hash(ctx, s.deploymentID, email)
	if err != nil {
		return Invitation{}, "", err
	}

	// Reject duplicate pending invitations early. The DB UNIQUE index
	// catches the race; the explicit check yields a friendlier 422.
	if existing, err := s.invites.GetPendingByEmailHash(ctx, organizationID, emailHash); err == nil && existing.ID != "" {
		return Invitation{}, "", ErrPendingInvitationExists
	} else if err != nil && !errors.Is(err, ErrNotFound) {
		return Invitation{}, "", err
	}

	// Generate the accept token. 32 random bytes via crypto/rand —
	// base64url-encoded for the URL, sha256-hashed for the DB lookup,
	// and the first 8 chars of the encoding kept as a human-readable
	// prefix for operator audit.
	rawToken := make([]byte, 32)
	if _, err := rand.Read(rawToken); err != nil {
		return Invitation{}, "", fmt.Errorf("organizations: token entropy: %w", err)
	}
	encodedToken := base64.RawURLEncoding.EncodeToString(rawToken)
	tokenHash := sha256.Sum256(rawToken)
	tokenPrefix := encodedToken
	if len(tokenPrefix) > 8 {
		tokenPrefix = tokenPrefix[:8]
	}

	now := s.now().UTC()
	inv := Invitation{
		ID:               id.New(id.PrefixInvitation),
		TenantID:         tenantID,
		OrganizationID:   organizationID,
		InviteeEmail:     email,
		InviteeEmailHash: emailHash,
		TokenHash:        tokenHash[:],
		TokenPrefix:      tokenPrefix,
		InvitedByUserID:  inviter.ActorID,
		ProposedRoleID:   in.ProposedRoleID,
		Status:           InvitationStatusPending,
		ExpiresAt:        now.Add(ttl),
		RowSeq:           1,
		CreatedAt:        now,
		UpdatedAt:        now,
	}
	created, err := s.invites.Create(ctx, inv)
	if err != nil {
		return Invitation{}, "", err
	}

	// Dispatch the invitation email. The email failure does NOT roll
	// back the invitation — operators can re-issue via a future
	// /resend endpoint, and the audit row "invitation.email_failed"
	// is reserved for Phase 10.
	if s.notifier != nil {
		// Inviter display name: best-effort lookup; fall back to actor id.
		inviterName := inviter.ActorID
		if s.users != nil {
			if u, lookErr := s.users.LookupUser(ctx, tenantID, inviter.ActorID); lookErr == nil && u.Name != "" {
				inviterName = u.Name
			}
		}
		acceptURL := s.buildAcceptURL(created.ID, encodedToken)
		_ = s.notifier.SendInvitation(ctx, SendInvitationInput{
			TenantID:         tenantID,
			InviteeEmail:     email,
			OrganizationID:   organizationID,
			OrganizationName: org.Name,
			InviterUserID:    inviter.ActorID,
			InviterName:      inviterName,
			AcceptURL:        acceptURL,
			ExpiresAt:        created.ExpiresAt,
		})
	}

	// Outbox event. Email plaintext is NEVER included in the payload —
	// the redactor would catch it but we don't even pass it. Auditors
	// can correlate via the invitation id + token_prefix.
	_ = s.events.Publish(ctx, "invitation.created", tenantID, map[string]any{
		"invitation_id":   created.ID,
		"organization_id": organizationID,
		"invited_by":      inviter.ActorID,
		"token_prefix":    created.TokenPrefix,
	})
	_ = s.events.Publish(ctx, "member.invited", tenantID, map[string]any{
		"invitation_id":   created.ID,
		"organization_id": organizationID,
		"invited_by":      inviter.ActorID,
	})

	// Clear the plaintext in the returned struct — the handler returns
	// only the metadata. The encoded token is returned as a second
	// value so the handler can include it in the 201 response body
	// when (and only when) explicitly opted-in by the operator (Phase
	// 7 default: never echo).
	created.InviteeEmail = ""
	return created, encodedToken, nil
}

// AcceptInvitation consumes a pending invitation. The caller MUST be
// authenticated (their JWT supplies the user_id); the platform refuses
// anonymous accepts as a phishing-mitigation. Validation order:
//
//  1. Look up the invitation by sha256(token) — constant-time db match.
//  2. Verify the invitation is pending + not expired.
//  3. Verify the caller's email matches the invitee email
//     (constant-time crypto/subtle.ConstantTimeCompare).
//  4. Create the member row + mark the invitation accepted.
//
// Documented CONVENTIONS.md exception: the accept path does NOT take
// tenantID as the first non-ctx argument because the invitation row IS
// the source of truth for the tenant binding. The auth principal's
// tenant is verified to match the invitation's tenant before any state
// change.
func (s *Service) AcceptInvitation(ctx context.Context, encodedToken string) (Member, error) {
	caller, ok := auth.PrincipalFromContext(ctx)
	if !ok || caller.ActorID == "" || caller.TenantID == "" {
		return Member{}, auth.ErrUnauthorized
	}

	rawToken, err := base64.RawURLEncoding.DecodeString(strings.TrimSpace(encodedToken))
	if err != nil || len(rawToken) == 0 {
		return Member{}, ErrInvalidToken
	}
	tokenHash := sha256.Sum256(rawToken)

	inv, err := s.invites.GetByTokenHash(ctx, tokenHash[:])
	if err != nil {
		if errors.Is(err, ErrNotFound) {
			return Member{}, ErrInvalidToken
		}
		return Member{}, err
	}
	// Constant-time confirm the stored hash matches (defence in depth;
	// the DB lookup is already an equality predicate but the explicit
	// compare keeps the call site self-documenting).
	if subtle.ConstantTimeCompare(inv.TokenHash, tokenHash[:]) != 1 {
		return Member{}, ErrInvalidToken
	}

	// The accept path is the documented tenancy-context exception
	// (CONVENTIONS.md §2). Cross-tenant accept is denied here: the
	// caller's JWT tenant must match the invitation's tenant.
	if subtle.ConstantTimeCompare([]byte(inv.TenantID), []byte(caller.TenantID)) != 1 {
		return Member{}, auth.ErrCrossTenant
	}

	if inv.Status != InvitationStatusPending {
		return Member{}, ErrInvitationConsumed
	}
	if !inv.ExpiresAt.After(s.now().UTC()) {
		return Member{}, ErrInvitationExpired
	}

	// Resolve the caller's email + constant-time compare to the invitee.
	if s.users == nil {
		return Member{}, errors.New("organizations: UserLookup port not wired")
	}
	user, err := s.users.LookupUser(ctx, caller.TenantID, caller.ActorID)
	if err != nil {
		return Member{}, err
	}
	callerEmail := strings.TrimSpace(user.Email)
	if s.hasher != nil {
		callerEmail = s.hasher.Normalise(callerEmail)
	}
	if subtle.ConstantTimeCompare([]byte(inv.InviteeEmail), []byte(callerEmail)) != 1 {
		return Member{}, ErrEmailMismatch
	}

	// Refuse duplicate active membership.
	if existing, err := s.members.GetByUser(ctx, inv.OrganizationID, caller.ActorID); err == nil && existing.ID != "" {
		return Member{}, ErrMemberExists
	} else if err != nil && !errors.Is(err, ErrNotFound) {
		return Member{}, err
	}

	now := s.now().UTC()
	m := Member{
		ID:             id.New(id.PrefixMember),
		TenantID:       inv.TenantID,
		OrganizationID: inv.OrganizationID,
		UserID:         caller.ActorID,
		RoleID:         inv.ProposedRoleID,
		Status:         MemberStatusActive,
		Metadata:       map[string]string{},
		RowSeq:         1,
		JoinedAt:       now,
		UpdatedAt:      now,
	}
	created, err := s.members.Create(ctx, m)
	if err != nil {
		return Member{}, err
	}
	if _, err := s.invites.MarkAccepted(ctx, inv.ID, caller.ActorID); err != nil {
		// The member row already exists; surface a 5xx so the operator
		// reconciles. Future Phase 10 audit will note the inconsistency.
		return Member{}, err
	}

	_ = s.events.Publish(ctx, "invitation.accepted", inv.TenantID, map[string]any{
		"invitation_id":   inv.ID,
		"organization_id": inv.OrganizationID,
		"accepted_by":     caller.ActorID,
		"member_id":       created.ID,
	})
	_ = s.events.Publish(ctx, "member.joined", inv.TenantID, map[string]any{
		"member_id":       created.ID,
		"organization_id": inv.OrganizationID,
		"user_id":         caller.ActorID,
	})
	return created, nil
}

// RevokeInvitation flips a pending invitation to status='revoked'.
// The caller must hold the invitation's tenant context. Accepted /
// already-revoked / expired invitations cannot be revoked again.
func (s *Service) RevokeInvitation(ctx context.Context, tenantID, invitationID string, expectedSeq int64) error {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return err
	}
	caller, ok := auth.PrincipalFromContext(ctx)
	if !ok || caller.ActorID == "" {
		return auth.ErrUnauthorized
	}
	revoked, err := s.invites.MarkRevoked(ctx, tenantID, invitationID, expectedSeq, caller.ActorID)
	if err != nil {
		return err
	}
	_ = s.events.Publish(ctx, "invitation.revoked", revoked.TenantID, map[string]any{
		"invitation_id":   revoked.ID,
		"organization_id": revoked.OrganizationID,
		"revoked_by":      caller.ActorID,
	})
	return nil
}

// GetInvitation returns an invitation scoped to the caller's tenant.
// The returned InviteeEmail is decrypted plaintext (read-path PII).
func (s *Service) GetInvitation(ctx context.Context, tenantID, invitationID string) (Invitation, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return Invitation{}, err
	}
	return s.invites.Get(ctx, tenantID, invitationID)
}

// ListInvitations enumerates invitations for an organization in the
// caller's tenant.
func (s *Service) ListInvitations(ctx context.Context, tenantID, organizationID string, limit int) ([]Invitation, error) {
	if err := auth.AssertTenant(ctx, tenantID); err != nil {
		return nil, err
	}
	if _, err := s.orgs.Get(ctx, tenantID, organizationID); err != nil {
		return nil, err
	}
	if limit <= 0 || limit > 200 {
		limit = 25
	}
	return s.invites.List(ctx, tenantID, organizationID, limit)
}

// SweepExpiredInvitations is invoked by the 5-min ticker in
// cmd/dataplane. Flips every pending invitation past its expires_at
// into 'expired' status and emits one outbox event per row.
//
// Returns the count of flipped rows so the caller can log the result.
func (s *Service) SweepExpiredInvitations(ctx context.Context) (int, error) {
	rows, err := s.invites.ExpireOverdue(ctx, s.now().UTC())
	if err != nil {
		return 0, err
	}
	for _, r := range rows {
		_ = s.events.Publish(ctx, "invitation.expired", r.TenantID, map[string]any{
			"invitation_id":   r.InvitationID,
			"organization_id": r.OrganizationID,
		})
	}
	return len(rows), nil
}

// buildAcceptURL renders the URL invited users click in the email.
// The format mirrors the canonical AGENTS.md §21 invite workflow.
func (s *Service) buildAcceptURL(invitationID, encodedToken string) string {
	base := strings.TrimRight(s.publicBaseURL, "/")
	if base == "" {
		base = "https://localhost"
	}
	return fmt.Sprintf("%s/invitations/%s/accept?token=%s", base, invitationID, encodedToken)
}
