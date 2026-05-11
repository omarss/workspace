package auth

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"

	"github.com/omarss/qudrat/internal/store"
)

// ExternalStore is the slice of *store.Queries the external-auth path needs.
type ExternalStore interface {
	GetExternalUser(ctx context.Context, arg store.GetExternalUserParams) (store.User, error)
	CreateExternalUser(ctx context.Context) (store.User, error)
	LinkExternalUser(ctx context.Context, arg store.LinkExternalUserParams) error
}

// PoolBeginner is the subset of pgxpool.Pool we use to start a tx for the
// create+link pair. Defined here so unit tests can stub it.
type PoolBeginner interface {
	Begin(ctx context.Context) (pgx.Tx, error)
}

// TxQueriesFn returns an ExternalStore scoped to the given transaction.
// Production wiring passes `func(tx pgx.Tx) ExternalStore { return store.New(tx) }`.
type TxQueriesFn func(tx pgx.Tx) ExternalStore

// ExternalService creates / retrieves a qudrat user from a (channel,
// external_id) pair. Used by the bot to fold each chat user into the
// existing user model so attempts, sessions, mastery all reuse the same
// machinery.
//
// IMPORTANT: this path bypasses OTP, so the API must protect it with a
// shared bot-side bearer token (see RequireBotToken middleware). A leaked
// token would let anyone impersonate any external_id.
type ExternalService struct {
	store     ExternalStore
	pool      PoolBeginner
	txQueries TxQueriesFn // optional; tests can leave nil
}

// NewExternalService wires the dependencies. txQueries=nil falls back to
// the non-transactional store (acceptable for unit tests with in-memory
// stubs).
func NewExternalService(s ExternalStore, pool PoolBeginner, txQueries TxQueriesFn) *ExternalService {
	return &ExternalService{store: s, pool: pool, txQueries: txQueries}
}

// ResolveOrCreate returns the user behind (channel, external_id). On first
// call it creates a fresh user row + the link in one transaction.
func (s *ExternalService) ResolveOrCreate(ctx context.Context, channel, externalID string) (store.User, error) {
	if channel == "" || externalID == "" {
		return store.User{}, ErrInvalidIdentifier
	}
	// Fast path: existing link.
	u, err := s.store.GetExternalUser(ctx, store.GetExternalUserParams{
		Channel:    channel,
		ExternalID: externalID,
	})
	if err == nil {
		// Touch last_seen_at — cheap activity heartbeat.
		_ = s.store.LinkExternalUser(ctx, store.LinkExternalUserParams{
			Channel:    channel,
			ExternalID: externalID,
			UserID:     u.ID,
		})
		return u, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return store.User{}, fmt.Errorf("get external: %w", err)
	}

	// Slow path: create user + link in one transaction so a partial
	// failure doesn't leave an orphan user behind.
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return store.User{}, fmt.Errorf("begin: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	q := s.queriesFor(tx)
	user, err := q.CreateExternalUser(ctx)
	if err != nil {
		return store.User{}, fmt.Errorf("create user: %w", err)
	}
	if err := q.LinkExternalUser(ctx, store.LinkExternalUserParams{
		Channel:    channel,
		ExternalID: externalID,
		UserID:     user.ID,
	}); err != nil {
		return store.User{}, fmt.Errorf("link: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return store.User{}, fmt.Errorf("commit: %w", err)
	}
	return user, nil
}

func (s *ExternalService) queriesFor(tx pgx.Tx) ExternalStore {
	if s.txQueries != nil {
		return s.txQueries(tx)
	}
	return s.store
}
