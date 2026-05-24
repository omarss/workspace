// Package otel centralises OpenTelemetry boot for the platform binaries.
//
// Phase 3 ships only the skeleton: a no-op Init returning a no-op shutdown
// fn. The OTLP gRPC exporter, resource attributes, and propagator wiring
// land in Phase 15 (DX polish) alongside the SigNoz container in compose.
// Centralising this now keeps cmd/* binaries identical even before the real
// pipeline lands — they all call otel.Init(ctx, "saas-<service>") at boot
// and defer the returned shutdown fn.
package otel

import "context"

// ShutdownFunc flushes pending spans and shuts down the tracer provider.
// Returns a context error if the deadline elapses before flushing.
type ShutdownFunc func(context.Context) error

// Init wires the OpenTelemetry tracer provider for the named service. It
// reads OTEL_EXPORTER_OTLP_ENDPOINT and, when set, installs an OTLP/gRPC
// exporter; otherwise it is a no-op.
//
// Phase 3 ships the no-op variant. Phase 15 swaps in the real exporter
// using go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc
// (currently only an indirect dependency).
func Init(_ context.Context, _ string) (ShutdownFunc, error) {
	return func(context.Context) error { return nil }, nil
}
