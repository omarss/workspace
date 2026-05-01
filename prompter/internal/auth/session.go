package auth

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/omarss/prompter/internal/store"
)

// SessionStore is the slice of *store.Queries the SessionService uses.
type SessionStore interface {
	CreateSession(ctx context.Context, arg store.CreateSessionParams) (store.Session, error)
	GetActiveSessionByRefreshHash(ctx context.Context, refreshHash string) (store.Session, error)
	RevokeSession(ctx context.Context, id uuid.UUID) error
	GetUserByID(ctx context.Context, id uuid.UUID) (store.User, error)
}

// SessionConfig tunes session lifetime. TTL=0 falls back to 30 days.
type SessionConfig struct {
	TTL time.Duration
}

func (c SessionConfig) withDefaults() SessionConfig {
	if c.TTL == 0 {
		c.TTL = 30 * 24 * time.Hour
	}
	return c
}

// SessionService creates, looks up, and revokes refresh-token-backed sessions.
// Plaintext tokens flow through the cookie layer only; the store sees hashes.
type SessionService struct {
	store SessionStore
	cfg   SessionConfig
	now   func() time.Time
}

// NewSessionService wires the dependencies. now=nil falls back to time.Now.
func NewSessionService(s SessionStore, cfg SessionConfig, now func() time.Time) *SessionService {
	if now == nil {
		now = time.Now
	}
	return &SessionService{store: s, cfg: cfg.withDefaults(), now: now}
}

// Create issues a fresh session for userID. The plaintext token is the only
// copy returned; persist it in the response cookie immediately.
func (s *SessionService) Create(ctx context.Context, userID uuid.UUID, ip, ua string) (token string, expiresAt time.Time, err error) {
	plaintext, err := GenerateSessionToken()
	if err != nil {
		return "", time.Time{}, fmt.Errorf("generate token: %w", err)
	}
	hash := HashSessionToken(plaintext)
	expires := s.now().Add(s.cfg.TTL)

	if _, err := s.store.CreateSession(ctx, store.CreateSessionParams{
		UserID:      userID,
		RefreshHash: hash,
		ExpiresAt:   pgxTimestamptz(expires),
		Ip:          optStr(ip),
		Ua:          optStr(ua),
	}); err != nil {
		return "", time.Time{}, fmt.Errorf("create session: %w", err)
	}
	return plaintext, expires, nil
}

// LookupResult bundles the session row with the resolved user, saving the
// caller a round-trip.
type LookupResult struct {
	Session store.Session
	User    store.User
}

// Lookup resolves a plaintext cookie value to its session + user, or
// ErrSessionNotFound if revoked, expired, or unknown.
func (s *SessionService) Lookup(ctx context.Context, token string) (LookupResult, error) {
	if token == "" {
		return LookupResult{}, ErrSessionNotFound
	}
	hash := HashSessionToken(token)
	sess, err := s.store.GetActiveSessionByRefreshHash(ctx, hash)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return LookupResult{}, ErrSessionNotFound
		}
		return LookupResult{}, fmt.Errorf("get session: %w", err)
	}
	user, err := s.store.GetUserByID(ctx, sess.UserID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return LookupResult{}, ErrSessionNotFound
		}
		return LookupResult{}, fmt.Errorf("get user: %w", err)
	}
	return LookupResult{Session: sess, User: user}, nil
}

// Revoke marks the session backing `token` as revoked. Idempotent: looking up
// an unknown or already-revoked token returns nil.
func (s *SessionService) Revoke(ctx context.Context, token string) error {
	if token == "" {
		return nil
	}
	hash := HashSessionToken(token)
	sess, err := s.store.GetActiveSessionByRefreshHash(ctx, hash)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil
		}
		return fmt.Errorf("get session: %w", err)
	}
	if err := s.store.RevokeSession(ctx, sess.ID); err != nil {
		return fmt.Errorf("revoke: %w", err)
	}
	return nil
}
