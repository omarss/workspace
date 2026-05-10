package auth

import (
	"context"
	"errors"
	"fmt"
	"net/mail"
	"regexp"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/omarss/qudrat/internal/store"
	"github.com/omarss/qudrat/pkg/notifier"
)

// OTPStore captures the slice of *store.Queries the OTP flow uses. Defining
// it here lets tests substitute a fake without depending on pgx directly.
type OTPStore interface {
	CreateEmailOTPChallenge(ctx context.Context, arg store.CreateEmailOTPChallengeParams) (store.OtpChallenge, error)
	CreateSMSOTPChallenge(ctx context.Context, arg store.CreateSMSOTPChallengeParams) (store.OtpChallenge, error)
	GetOTPChallengeByID(ctx context.Context, id uuid.UUID) (store.OtpChallenge, error)
	IncrementOTPAttempts(ctx context.Context, id uuid.UUID) (store.OtpChallenge, error)
	ConsumeOTPChallenge(ctx context.Context, id uuid.UUID) error
	CountRecentOTPChallengesForIdentifier(ctx context.Context, arg store.CountRecentOTPChallengesForIdentifierParams) (int32, error)

	GetUserByEmail(ctx context.Context, email *string) (store.User, error)
	GetUserByPhone(ctx context.Context, phone *string) (store.User, error)
	CreateUser(ctx context.Context, arg store.CreateUserParams) (store.User, error)
	TouchUserLastLogin(ctx context.Context, id uuid.UUID) error
}

// OTPConfig tunes the OTP flow. Defaults are applied when zero.
type OTPConfig struct {
	// TTL controls how long a challenge stays valid. Default 10 minutes.
	TTL time.Duration
	// MaxAttempts caps brute-force on the email path. Default 5.
	// Twilio caps the SMS path itself.
	MaxAttempts int
	// RateWindow + RateLimit form a sliding-window cap on /otp/start per
	// identifier. Default: 3 starts per 5 minutes (spec §10).
	RateWindow time.Duration
	RateLimit  int
}

func (c OTPConfig) withDefaults() OTPConfig {
	if c.TTL == 0 {
		c.TTL = 10 * time.Minute
	}
	if c.MaxAttempts == 0 {
		c.MaxAttempts = 5
	}
	if c.RateWindow == 0 {
		c.RateWindow = 5 * time.Minute
	}
	if c.RateLimit == 0 {
		c.RateLimit = 3
	}
	return c
}

// OTPService runs the start/verify flow for both channels.
type OTPService struct {
	store OTPStore
	email notifier.EmailSender
	sms   notifier.SMSVerifier
	cfg   OTPConfig
	now   func() time.Time
}

// NewOTPService wires the dependencies. now=nil falls back to time.Now.
func NewOTPService(s OTPStore, email notifier.EmailSender, sms notifier.SMSVerifier, cfg OTPConfig, now func() time.Time) *OTPService {
	if now == nil {
		now = time.Now
	}
	return &OTPService{store: s, email: email, sms: sms, cfg: cfg.withDefaults(), now: now}
}

// StartParams is the input to /otp/start.
type StartParams struct {
	Channel    string // "email" | "sms"
	Identifier string // RFC-822 email or E.164 phone
	IP         string
	UA         string
}

// StartResult is what we return to the client (and what they hand back on /verify).
type StartResult struct {
	ChallengeID uuid.UUID
	ExpiresAt   time.Time
}

// E.164 — leading '+', 1-15 digits. Permissive enough for any country.
var phoneE164Re = regexp.MustCompile(`^\+[1-9][0-9]{1,14}$`)

// Start validates input, enforces the rate limit, and dispatches to the
// channel-appropriate path.
func (s *OTPService) Start(ctx context.Context, p StartParams) (StartResult, error) {
	if err := s.validateStart(p); err != nil {
		return StartResult{}, err
	}

	count, err := s.store.CountRecentOTPChallengesForIdentifier(ctx, store.CountRecentOTPChallengesForIdentifierParams{
		Identifier: p.Identifier,
		Channel:    p.Channel,
		Column3:    pgxInterval(s.cfg.RateWindow),
	})
	if err != nil {
		return StartResult{}, fmt.Errorf("rate count: %w", err)
	}
	if int(count) >= s.cfg.RateLimit {
		return StartResult{}, ErrRateLimited
	}

	expires := s.now().Add(s.cfg.TTL)
	switch p.Channel {
	case "email":
		return s.startEmail(ctx, p, expires)
	case "sms":
		return s.startSMS(ctx, p, expires)
	default:
		return StartResult{}, ErrInvalidChannel
	}
}

func (s *OTPService) validateStart(p StartParams) error {
	switch p.Channel {
	case "email":
		if _, err := mail.ParseAddress(p.Identifier); err != nil {
			return fmt.Errorf("%w: %w", ErrInvalidIdentifier, err)
		}
	case "sms":
		if !phoneE164Re.MatchString(p.Identifier) {
			return fmt.Errorf("%w: phone must be E.164", ErrInvalidIdentifier)
		}
	default:
		return ErrInvalidChannel
	}
	return nil
}

func (s *OTPService) startEmail(ctx context.Context, p StartParams, expires time.Time) (StartResult, error) {
	code, err := GenerateOTP()
	if err != nil {
		return StartResult{}, fmt.Errorf("generate: %w", err)
	}
	hash, err := HashOTP(code)
	if err != nil {
		return StartResult{}, fmt.Errorf("hash: %w", err)
	}
	row, err := s.store.CreateEmailOTPChallenge(ctx, store.CreateEmailOTPChallengeParams{
		Identifier: p.Identifier,
		CodeHash:   &hash,
		ExpiresAt:  pgxTimestamptz(expires),
		Ip:         optStr(p.IP),
		Ua:         optStr(p.UA),
	})
	if err != nil {
		return StartResult{}, fmt.Errorf("create challenge: %w", err)
	}
	if err := s.email.SendOTP(ctx, p.Identifier, code); err != nil {
		return StartResult{}, fmt.Errorf("%w: %w", ErrProvider, err)
	}
	return StartResult{ChallengeID: row.ID, ExpiresAt: expires}, nil
}

func (s *OTPService) startSMS(ctx context.Context, p StartParams, expires time.Time) (StartResult, error) {
	sid, err := s.sms.Start(ctx, p.Identifier)
	if err != nil {
		return StartResult{}, fmt.Errorf("%w: %w", ErrProvider, err)
	}
	row, err := s.store.CreateSMSOTPChallenge(ctx, store.CreateSMSOTPChallengeParams{
		Identifier:  p.Identifier,
		ProviderRef: &sid,
		ExpiresAt:   pgxTimestamptz(expires),
		Ip:          optStr(p.IP),
		Ua:          optStr(p.UA),
	})
	if err != nil {
		return StartResult{}, fmt.Errorf("create challenge: %w", err)
	}
	return StartResult{ChallengeID: row.ID, ExpiresAt: expires}, nil
}

// VerifyResult is what Verify returns to the caller — the resolved user.
type VerifyResult struct {
	User store.User
}

// Verify checks the supplied code against the challenge, consumes the row
// on success, and returns the user (creating one on first-time login).
func (s *OTPService) Verify(ctx context.Context, challengeID uuid.UUID, code string) (VerifyResult, error) {
	ch, err := s.store.GetOTPChallengeByID(ctx, challengeID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return VerifyResult{}, ErrChallengeNotFound
		}
		return VerifyResult{}, fmt.Errorf("get challenge: %w", err)
	}
	if ch.ConsumedAt.Valid {
		return VerifyResult{}, ErrChallengeConsumed
	}
	if !s.now().Before(ch.ExpiresAt.Time) {
		return VerifyResult{}, ErrChallengeExpired
	}
	if int(ch.Attempts) >= s.cfg.MaxAttempts {
		return VerifyResult{}, ErrTooManyAttempts
	}

	switch ch.Channel {
	case "email":
		if ch.CodeHash == nil {
			return VerifyResult{}, fmt.Errorf("email challenge missing hash")
		}
		if err := VerifyOTP(*ch.CodeHash, code); err != nil {
			_, _ = s.store.IncrementOTPAttempts(ctx, ch.ID)
			if errors.Is(err, ErrOTPMismatch) {
				return VerifyResult{}, ErrOTPMismatch
			}
			return VerifyResult{}, err
		}
	case "sms":
		ok, err := s.sms.Check(ctx, ch.Identifier, code)
		if err != nil {
			return VerifyResult{}, fmt.Errorf("%w: %w", ErrProvider, err)
		}
		if !ok {
			_, _ = s.store.IncrementOTPAttempts(ctx, ch.ID)
			return VerifyResult{}, ErrOTPMismatch
		}
	default:
		return VerifyResult{}, ErrInvalidChannel
	}

	if err := s.store.ConsumeOTPChallenge(ctx, ch.ID); err != nil {
		return VerifyResult{}, fmt.Errorf("consume: %w", err)
	}

	user, err := s.findOrCreateUser(ctx, ch.Channel, ch.Identifier)
	if err != nil {
		return VerifyResult{}, err
	}
	if err := s.store.TouchUserLastLogin(ctx, user.ID); err != nil {
		return VerifyResult{}, fmt.Errorf("touch user: %w", err)
	}
	return VerifyResult{User: user}, nil
}

func (s *OTPService) findOrCreateUser(ctx context.Context, channel, identifier string) (store.User, error) {
	switch channel {
	case "email":
		u, err := s.store.GetUserByEmail(ctx, &identifier)
		if err == nil {
			return u, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return store.User{}, fmt.Errorf("get user: %w", err)
		}
		return s.store.CreateUser(ctx, store.CreateUserParams{Email: &identifier})
	case "sms":
		u, err := s.store.GetUserByPhone(ctx, &identifier)
		if err == nil {
			return u, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return store.User{}, fmt.Errorf("get user: %w", err)
		}
		return s.store.CreateUser(ctx, store.CreateUserParams{Phone: &identifier})
	default:
		return store.User{}, ErrInvalidChannel
	}
}
