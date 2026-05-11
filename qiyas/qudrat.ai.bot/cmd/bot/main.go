// Command bot runs the qudrat Telegram + WhatsApp bot.
//
// Two transports run in parallel:
//
//   - Telegram: long-poll loop in a goroutine. No inbound HTTP needed.
//   - WhatsApp via Twilio: inbound POST /webhooks/twilio/whatsapp routed
//     to the same handler. host nginx proxies the public URL through.
//
// Both are config-gated. Empty Telegram token disables long-poll; empty
// Twilio creds disable the webhook (route returns 503).
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/omarss/qudrat-bot/internal/config"
	"github.com/omarss/qudrat-bot/internal/handler"
	"github.com/omarss/qudrat-bot/internal/qudrat"
	"github.com/omarss/qudrat-bot/internal/server"
	"github.com/omarss/qudrat-bot/internal/state"
	"github.com/omarss/qudrat-bot/internal/transport/telegram"
	"github.com/omarss/qudrat-bot/internal/transport/whatsapp"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)
	if err := run(logger); err != nil {
		logger.Error("bot fatal", "err", err)
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	if cfg.BotAuthToken == "" {
		logger.Warn("QUDRAT_BOT_AUTH_TOKEN empty — /api/auth/external will reject every call. Bot will fail at runtime.")
	}

	st := state.NewStore()
	apiClient := qudrat.New(cfg.QudratAPIURL, cfg.BotAuthToken, nil)

	var tgClient *telegram.Client
	if cfg.TelegramToken != "" {
		tgClient = telegram.New(cfg.TelegramToken, nil)
		logger.Info("telegram transport enabled")
	} else {
		logger.Info("telegram transport disabled (no token)")
	}

	var waClient *whatsapp.Client
	if cfg.TwilioAccountSID != "" {
		waClient = whatsapp.New(cfg.TwilioAccountSID, cfg.TwilioAuthToken, cfg.TwilioFrom, nil)
		logger.Info("whatsapp transport enabled", "from", cfg.TwilioFrom)
	} else {
		logger.Info("whatsapp transport disabled (no twilio creds)")
	}

	h := handler.New(apiClient, tgClient, st, logger)

	r := server.New(server.Config{
		Version: cfg.Version,
		Handler: h,
		WA:      waClient,
		Logger:  logger,
	})
	srv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           r,
		ReadHeaderTimeout: cfg.ReadHeaderTimeout,
		IdleTimeout:       60 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	httpErr := make(chan error, 1)
	go func() {
		logger.Info("http listening", "addr", cfg.HTTPAddr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			httpErr <- err
		}
		httpErr <- nil
	}()

	if tgClient != nil {
		go runTelegramLoop(ctx, logger, tgClient, h)
	}

	select {
	case err := <-httpErr:
		return err
	case <-ctx.Done():
		logger.Info("shutting down")
	}
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	return srv.Shutdown(shutdownCtx)
}

// runTelegramLoop runs the long-poll consumer. Failures back off + retry
// — Telegram occasionally 429s if you hammer it during a flap.
func runTelegramLoop(ctx context.Context, logger *slog.Logger, tg *telegram.Client, h *handler.Handler) {
	var offset int64
	backoff := 1 * time.Second
	const maxBackoff = 30 * time.Second
	for {
		if ctx.Err() != nil {
			return
		}
		updates, err := tg.GetUpdates(ctx, offset, 25)
		if err != nil {
			if ctx.Err() != nil {
				return
			}
			logger.Warn("getUpdates", "err", err, "backoff", backoff)
			select {
			case <-ctx.Done():
				return
			case <-time.After(backoff):
			}
			if backoff < maxBackoff {
				backoff *= 2
			}
			continue
		}
		backoff = 1 * time.Second
		for _, u := range updates {
			if u.UpdateID >= offset {
				offset = u.UpdateID + 1
			}
			// Each update gets its own context with a generous deadline
			// so a slow upstream doesn't stall the poll loop.
			uCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
			h.HandleTelegramUpdate(uCtx, u)
			cancel()
		}
	}
}
