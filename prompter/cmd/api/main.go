// Command api serves the prompter HTTP API.
//
// The binary stays small on purpose: it loads config, opens the Postgres
// pool, builds the auth and session services, and runs an http.Server with
// production-sane timeouts. All routing and business logic lives in
// internal/.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/omarss/prompter/internal/api/server"
	"github.com/omarss/prompter/internal/auth"
	"github.com/omarss/prompter/internal/config"
	"github.com/omarss/prompter/internal/store"
	"github.com/omarss/prompter/pkg/notifier"
	"github.com/omarss/prompter/pkg/notifier/devlog"
	"github.com/omarss/prompter/pkg/notifier/resend"
	"github.com/omarss/prompter/pkg/notifier/twilio"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	if err := run(logger); err != nil {
		logger.Error("api fatal", "err", err)
		os.Exit(1)
	}
}

// run holds main's logic so deferred cleanups still fire on any error path.
// main() must remain os.Exit-only.
func run(logger *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	bootCtx, bootCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer bootCancel()

	pool, err := pgxpool.New(bootCtx, cfg.DatabaseDSN)
	if err != nil {
		return fmt.Errorf("pgxpool: %w", err)
	}
	defer pool.Close()
	if err := pool.Ping(bootCtx); err != nil {
		return fmt.Errorf("pg ping: %w", err)
	}

	q := store.New(pool)
	emailer := buildEmailSender(cfg, logger)
	smser := buildSMSVerifier(cfg, logger)

	otp := auth.NewOTPService(q, emailer, smser, auth.OTPConfig{TTL: cfg.OTPTTL}, nil)
	sess := auth.NewSessionService(q, auth.SessionConfig{TTL: cfg.SessionTTL}, nil)

	cookie := auth.CookieConfig{
		Name:     cfg.CookieName,
		Path:     "/",
		Domain:   cfg.CookieDomain,
		Secure:   cfg.CookieSecure,
		SameSite: cfg.CookieSameSite,
		HTTPOnly: true,
	}
	authH := auth.NewHandler(otp, sess, cookie, logger)

	r := server.New(server.Config{Version: cfg.Version})
	r.Route("/api", authH.Mount)

	srv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           r,
		ReadHeaderTimeout: cfg.ReadHeaderTimeout,
		// IdleTimeout tames keep-alive connections hanging on through pod
		// restarts; matches the nginx upstream keepalive window.
		IdleTimeout: 60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	listenErr := make(chan error, 1)
	go func() {
		logger.Info("api listening", "addr", cfg.HTTPAddr, "version", cfg.Version)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			listenErr <- err
			return
		}
		listenErr <- nil
	}()

	select {
	case err := <-listenErr:
		return err
	case <-ctx.Done():
		logger.Info("shutting down")
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(shutdownCtx)
}

// buildEmailSender returns the production Resend client when an API key is
// configured; otherwise a dev logger that prints OTP codes. The dev path
// must NEVER reach production: it leaks secrets.
func buildEmailSender(cfg config.Config, logger *slog.Logger) notifier.EmailSender {
	if cfg.ResendAPIKey != "" {
		logger.Info("email sender", "provider", "resend", "from", cfg.ResendFrom)
		return resend.New(cfg.ResendAPIKey, cfg.ResendFrom)
	}
	logger.Warn("email sender", "provider", "devlog", "warning", "OTP codes will appear in logs — dev only")
	return devlog.NewEmailSender(logger)
}

func buildSMSVerifier(cfg config.Config, logger *slog.Logger) notifier.SMSVerifier {
	if cfg.TwilioAccountSID != "" {
		logger.Info("sms verifier", "provider", "twilio", "service_sid", cfg.TwilioVerifyServiceSID)
		return twilio.NewVerifyClient(cfg.TwilioAccountSID, cfg.TwilioAuthToken, cfg.TwilioVerifyServiceSID)
	}
	logger.Warn("sms verifier", "provider", "devlog", "warning", "any code matching the dev fixture is accepted")
	return devlog.NewSMSVerifier(logger, "")
}
