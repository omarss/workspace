package crypto

import (
	"context"
	"errors"
	"fmt"
	"reflect"
)

// Encryptor is the persistence-side abstraction implemented by Phase 4's
// OpenBao envelope-encryption code (see internal/platform/crypto/envelope).
// The interface lives here so module authors can write the call-site idiom
// without importing the bao client.
type Encryptor interface {
	// EncryptField returns an Envelope wrapping plaintext for the given
	// deployment-bound key id. aad is additional authenticated data
	// (typically the row id + column name) — authenticated but not encrypted.
	EncryptField(ctx context.Context, kid string, plaintext []byte, aad []byte) (Envelope, error)
}

// Decryptor is the symmetric read-path abstraction. Repository code that
// hydrates a row from envelope columns reads via this interface so it does
// not transitively import the bao client. expectedKid MUST equal the
// deployment_id; the implementation refuses with envelope.ErrKidMismatch
// when env.KID != expectedKid (layer 5 of tenant isolation).
type Decryptor interface {
	DecryptField(ctx context.Context, env Envelope, expectedKid string, aad []byte) ([]byte, error)
}

// WalkMode selects between the permissive and strict envelope walkers.
//
// PermissiveMode silently drops the encrypted Envelope when no sibling
// <FieldName>Envelope exists on the struct. This is the Phase 3 / Phase 4
// behaviour kept so existing modules that adopted the walker incrementally
// keep working unchanged.
//
// StrictMode returns ErrEnvelopeFieldMissing if any tagged field lacks a
// matching sibling Envelope field. Identity (Phase 5) is the first consumer
// — silently dropping the envelope on a PII column would be a data-loss
// security incident. New PII modules SHOULD adopt strict mode by calling
// EncryptPIIFieldsStrict instead of EncryptPIIFields.
type WalkMode int

const (
	// PermissiveMode keeps the Phase 3 behaviour: missing sibling Envelope
	// field is a no-op (plaintext still cleared).
	PermissiveMode WalkMode = iota
	// StrictMode requires every tagged field to have a sibling Envelope.
	// Missing sibling returns ErrEnvelopeFieldMissing.
	StrictMode
)

// EncryptPIIFields walks v (must be a non-nil pointer to a struct) and
// invokes enc.EncryptField on every field tagged pii:"true" or
// sensitive:"true". The encrypted Envelope is written to the sibling field
// named <FieldName>Envelope when one exists; the plaintext field is then
// cleared so logs / downstream serialisers cannot leak it.
//
// Convention (CONVENTIONS.md §10.x):
//
//	type User struct {
//	    Email         string          `pii:"true"`
//	    EmailEnvelope crypto.Envelope // populated by the walker
//	}
//
// The walker treats the sibling Envelope field as optional: Phase 3 tests
// rely on the legacy behaviour (zero the plaintext, drop the envelope).
// Phase 4+ migrations declare the sibling field; the walker populates it
// when present.
//
// ADR 004 documents the codegen → struct-tag → walker pipeline.
func EncryptPIIFields(ctx context.Context, enc Encryptor, kid string, v any) error {
	return encryptPIIFields(ctx, enc, kid, v, PermissiveMode)
}

// EncryptPIIFieldsStrict is the Phase 5 PII persistence helper. It walks v
// the same way as EncryptPIIFields but refuses to silently drop an
// envelope: every field tagged pii:"true" / sensitive:"true" MUST have a
// matching <FieldName>Envelope sibling of type crypto.Envelope. Missing
// sibling returns ErrEnvelopeFieldMissing — the caller fails closed.
//
// New modules that persist PII SHOULD use this variant; the permissive
// walker remains for Phase 3 callers that have not yet declared sibling
// fields. See Phase 5 docs/plans/mvp/06-identity-keycloak.md for the
// rationale (silent drop on Identity would leak PII through the read path).
func EncryptPIIFieldsStrict(ctx context.Context, enc Encryptor, kid string, v any) error {
	return encryptPIIFields(ctx, enc, kid, v, StrictMode)
}

func encryptPIIFields(ctx context.Context, enc Encryptor, kid string, v any, mode WalkMode) error {
	if enc == nil {
		return ErrNoEncryptor
	}
	rv := reflect.ValueOf(v)
	if rv.Kind() != reflect.Pointer || rv.IsNil() {
		return ErrNotPointer
	}
	rv = rv.Elem()
	if rv.Kind() != reflect.Struct {
		return ErrNotPointer
	}
	return walkEncrypt(ctx, enc, kid, rv, mode)
}

// walkEncrypt is split out so future callers (e.g. nested struct support)
// can recurse without duplicating the pointer-unwrap dance.
func walkEncrypt(ctx context.Context, enc Encryptor, kid string, rv reflect.Value, mode WalkMode) error {
	t := rv.Type()
	envelopeType := reflect.TypeOf(Envelope{})
	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		if !f.IsExported() {
			continue
		}
		if f.Tag.Get("pii") != "true" && f.Tag.Get("sensitive") != "true" {
			continue
		}
		fv := rv.Field(i)
		// Supported field kinds: string and *string. *string is the patch
		// shape (nil = unchanged; non-nil empty = no-op since plaintext is
		// empty; non-nil non-empty = encrypt + zero). Phase 3 only handled
		// string; Phase 5 added *string to support UpdatePatch on Identity.
		var plaintext string
		var setEmpty func()
		switch fv.Kind() {
		case reflect.String:
			plaintext = fv.String()
			setEmpty = func() { fv.SetString("") }
		case reflect.Pointer:
			if fv.IsNil() {
				continue
			}
			if fv.Elem().Kind() != reflect.String {
				continue
			}
			plaintext = fv.Elem().String()
			setEmpty = func() { fv.Elem().SetString("") }
		default:
			continue
		}
		// Validate sibling presence up-front so strict mode never silently
		// proceeds on an unencryptable column. The check covers the empty
		// plaintext path too — a missing sibling on a tagged field is a
		// schema bug, not data-dependent.
		envField := rv.FieldByName(f.Name + "Envelope")
		siblingValid := envField.IsValid() && envField.CanSet() && envField.Type() == envelopeType
		if mode == StrictMode && !siblingValid {
			return fmt.Errorf("%w: field %q is tagged PII but has no sibling %q of type crypto.Envelope", ErrEnvelopeFieldMissing, f.Name, f.Name+"Envelope")
		}
		if plaintext == "" {
			continue
		}
		env, err := enc.EncryptField(ctx, kid, []byte(plaintext), []byte(f.Name))
		if err != nil {
			return err
		}
		if siblingValid {
			envField.Set(reflect.ValueOf(env))
		}
		// Clear the plaintext after wrapping so the row never carries it
		// past the persistence boundary.
		setEmpty()
	}
	return nil
}

// ErrEnvelopeFieldWrongType is returned when the sibling Envelope field
// exists but has the wrong type. Today this is silently treated as "no
// sibling field" — callers wanting strict checks can branch on it once we
// switch the walker to mandatory-sibling mode (Phase 4 ships permissive).
var ErrEnvelopeFieldWrongType = errors.New("crypto: sibling envelope field is not crypto.Envelope")

// ErrEnvelopeFieldMissing is the strict-mode sentinel returned when a
// pii/sensitive-tagged field has no <FieldName>Envelope sibling of type
// crypto.Envelope. New modules adopting EncryptPIIFieldsStrict surface
// this as a fail-closed schema bug.
var ErrEnvelopeFieldMissing = errors.New("crypto: sibling envelope field is missing")
