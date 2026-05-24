package log

import (
	"io"
	"log/slog"
	"os"
)

// Options configures New. The defaults match AGENTS.md §20 (JSON output,
// info-level minimum, source omitted to keep records compact).
type Options struct {
	// Level controls the minimum record level. Default LevelInfo.
	Level slog.Level
	// AddSource emits the originating file:line. Off by default for
	// production; flip on for noisy debug sessions.
	AddSource bool
	// Output overrides the default writer (os.Stdout). Tests use a bytes.Buffer.
	Output io.Writer
}

// New returns a slog.Logger with the platform's PII-redacting JSON handler.
// Every cmd/* binary's run() function should call this at boot and then
// `slog.SetDefault(logger)` so downstream callers' slog.Default() picks up
// the redactor.
func New(opts Options) *slog.Logger {
	if opts.Output == nil {
		opts.Output = os.Stdout
	}
	if opts.Level == 0 {
		opts.Level = slog.LevelInfo
	}
	h := slog.NewJSONHandler(opts.Output, &slog.HandlerOptions{
		AddSource:   opts.AddSource,
		Level:       opts.Level,
		ReplaceAttr: replaceAttr,
	})
	return slog.New(h)
}

// replaceAttr is the slog ReplaceAttr hook. It applies the redactor and the
// struct walker; everything else passes through unmodified.
func replaceAttr(_ []string, a slog.Attr) slog.Attr {
	// Time / level / source / msg attrs come in with predefined keys; do
	// NOT redact them. The slog spec passes them through the hook anyway.
	if a.Key == slog.TimeKey || a.Key == slog.LevelKey || a.Key == slog.SourceKey || a.Key == slog.MessageKey {
		return a
	}
	if IsRedactedKey(a.Key) {
		return slog.String(a.Key, "[REDACTED]")
	}
	if scrubbed, ok := scrubStruct(a.Value); ok {
		return slog.Attr{Key: a.Key, Value: scrubbed}
	}
	return a
}
