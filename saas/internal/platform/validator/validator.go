// Package validator centralises the platform's struct-validation policy.
// Phase 3 ships the package skeleton; the go-playground/validator/v10 wiring
// lands when the first non-trivial consumer arrives (Phase 5 Identity, where
// User/Email/Phone validation needs more than a regex).
//
// The skeleton is here NOW because CONVENTIONS.md tells every new module to
// import "github.com/omarss/saas/internal/platform/validator" rather than
// reach for validator.New() ad hoc. Centralising the constructor lets us
// add custom tags (e.g. "ulid_prefix") once and have every module pick
// them up.
//
// Until the v10 dependency is added, Struct returns nil and consumers stick
// to handcrafted validation in their domain.go. Foundations §1 pins
// validator/v10 (WithRequiredStructEnabled is the v11 default) — we adopt
// the dep on first real usage.
package validator

// Struct is the future entry point. Today it returns nil so call sites can
// be written defensively (`if err := validator.Struct(req); err != nil`).
// When the v10 wiring lands, this signature is preserved.
func Struct(_ any) error {
	return nil
}
