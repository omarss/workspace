// Package parent owns the parent ↔ child link with consent and the
// read-only summary surface (spec §4 #11, §23).
//
// Phase 10 scope:
//
//   - Parents request a link by referencing the child's email/phone; the
//     child must accept before any reads succeed.
//   - The summary is intentionally minimal — attempts count, average
//     accuracy, distinct active days in the last 7 days. No question
//     content, no per-skill breakdown. The point is consistency +
//     improvement (spec §4 #11), not pressure.
package parent

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/omarss/qudrat/internal/store"
)

// ErrChildNotFound is returned when the parent references an identifier
// (email/phone) that doesn't resolve to a user. The error is intentionally
// the same as a denied link to avoid leaking which identifiers exist.
var (
	ErrChildNotFound = errors.New("parent: child not found or link not authorized")
	ErrLinkNotFound  = errors.New("parent: link not found")
	ErrSelfLink      = errors.New("parent: cannot link to self")
	ErrNoConsent     = errors.New("parent: child has not accepted the link")
)

// Store is the slice of *store.Queries the parent surface consumes.
type Store interface {
	GetUserByEmail(ctx context.Context, email *string) (store.User, error)
	GetUserByPhone(ctx context.Context, phone *string) (store.User, error)
	RequestParentLink(ctx context.Context, arg store.RequestParentLinkParams) (store.ParentLink, error)
	AcceptParentLink(ctx context.Context, arg store.AcceptParentLinkParams) error
	RevokeParentLink(ctx context.Context, arg store.RevokeParentLinkParams) error
	ListChildrenForParent(ctx context.Context, parentID uuid.UUID) ([]store.ListChildrenForParentRow, error)
	GetParentLinkForView(ctx context.Context, arg store.GetParentLinkForViewParams) (store.ParentLink, error)
	WeeklySummaryForUser(ctx context.Context, userID uuid.UUID) (store.WeeklySummaryForUserRow, error)
}

// Service exposes the parent API.
type Service struct {
	store Store
}

// NewService wires the dependency.
func NewService(s Store) *Service { return &Service{store: s} }

// RequestLink creates a pending parent_links row from parentID to the
// user identified by (email or phone). identifier is interpreted by
// channel: "email" or "sms".
func (s *Service) RequestLink(ctx context.Context, parentID uuid.UUID, channel, identifier string) (store.ParentLink, error) {
	child, err := s.findChild(ctx, channel, identifier)
	if err != nil {
		return store.ParentLink{}, err
	}
	if child.ID == parentID {
		return store.ParentLink{}, ErrSelfLink
	}
	link, err := s.store.RequestParentLink(ctx, store.RequestParentLinkParams{
		ParentID: parentID,
		ChildID:  child.ID,
	})
	if err != nil {
		return store.ParentLink{}, fmt.Errorf("request: %w", err)
	}
	return link, nil
}

// Accept transitions a pending link to accepted. childID must be the
// authenticated user's ID — only the child can consent.
func (s *Service) Accept(ctx context.Context, linkID, childID uuid.UUID) error {
	return s.store.AcceptParentLink(ctx, store.AcceptParentLinkParams{
		ID:      linkID,
		ChildID: childID,
	})
}

// Revoke marks a link revoked. Either side (parent or child) may revoke;
// userID is the authenticated user's ID.
func (s *Service) Revoke(ctx context.Context, linkID, userID uuid.UUID) error {
	return s.store.RevokeParentLink(ctx, store.RevokeParentLinkParams{
		ID:       linkID,
		ParentID: userID,
	})
}

// Children returns the parent's link list (any status — pending shows up
// so the parent knows the child hasn't accepted yet).
func (s *Service) Children(ctx context.Context, parentID uuid.UUID) ([]ChildLink, error) {
	rows, err := s.store.ListChildrenForParent(ctx, parentID)
	if err != nil {
		return nil, fmt.Errorf("list children: %w", err)
	}
	out := make([]ChildLink, 0, len(rows))
	for _, r := range rows {
		out = append(out, ChildLink{
			LinkID:        r.ID,
			ChildID:       r.ChildID,
			ChildNickname: r.ChildNickname,
			Status:        r.Status,
		})
	}
	return out, nil
}

// Summary returns the weekly read-only view for a child. The parent must
// have an accepted link to the child first.
func (s *Service) Summary(ctx context.Context, parentID, childID uuid.UUID) (Summary, error) {
	if _, err := s.store.GetParentLinkForView(ctx, store.GetParentLinkForViewParams{
		ParentID: parentID,
		ChildID:  childID,
	}); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return Summary{}, ErrNoConsent
		}
		return Summary{}, fmt.Errorf("link check: %w", err)
	}
	row, err := s.store.WeeklySummaryForUser(ctx, childID)
	if err != nil {
		return Summary{}, fmt.Errorf("weekly: %w", err)
	}
	return Summary{
		AttemptsLast7Days: int(row.Attempts),
		Accuracy:          row.Accuracy,
		ActiveDays:        int(row.ActiveDays),
	}, nil
}

func (s *Service) findChild(ctx context.Context, channel, identifier string) (store.User, error) {
	switch channel {
	case "email":
		u, err := s.store.GetUserByEmail(ctx, &identifier)
		if err != nil {
			return store.User{}, ErrChildNotFound
		}
		return u, nil
	case "sms", "phone":
		u, err := s.store.GetUserByPhone(ctx, &identifier)
		if err != nil {
			return store.User{}, ErrChildNotFound
		}
		return u, nil
	default:
		return store.User{}, ErrChildNotFound
	}
}

// ChildLink is the public list-row.
type ChildLink struct {
	LinkID        uuid.UUID `json:"link_id"`
	ChildID       uuid.UUID `json:"child_id"`
	ChildNickname string    `json:"child_nickname"`
	Status        string    `json:"status"`
}

// Summary is the parent-facing read-only view.
type Summary struct {
	AttemptsLast7Days int     `json:"attempts_last_7_days"`
	Accuracy          float64 `json:"accuracy"`
	ActiveDays        int     `json:"active_days"`
}
