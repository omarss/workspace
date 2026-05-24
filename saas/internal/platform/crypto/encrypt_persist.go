package crypto

import (
	"context"
	"errors"
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
	return walkEncrypt(ctx, enc, kid, rv)
}

// walkEncrypt is split out so future callers (e.g. nested struct support)
// can recurse without duplicating the pointer-unwrap dance.
func walkEncrypt(ctx context.Context, enc Encryptor, kid string, rv reflect.Value) error {
	t := rv.Type()
	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		if !f.IsExported() {
			continue
		}
		if f.Tag.Get("pii") != "true" && f.Tag.Get("sensitive") != "true" {
			continue
		}
		fv := rv.Field(i)
		// Phase 3 only supports string fields — that covers email / phone /
		// SSN / card numbers. Phase 4 keeps the same shape; []byte support
		// lands when the first byte-typed PII field is introduced.
		if fv.Kind() != reflect.String {
			continue
		}
		plaintext := fv.String()
		if plaintext == "" {
			continue
		}
		env, err := enc.EncryptField(ctx, kid, []byte(plaintext), []byte(f.Name))
		if err != nil {
			return err
		}
		// Phase 4: populate the sibling <FieldName>Envelope field when one
		// exists. Falling back to a no-op when the sibling is missing keeps
		// the Phase 3 tests green and lets modules adopt the new shape
		// incrementally rather than in a single big bang.
		if envField := rv.FieldByName(f.Name + "Envelope"); envField.IsValid() && envField.CanSet() && envField.Type() == reflect.TypeOf(Envelope{}) {
			envField.Set(reflect.ValueOf(env))
		}
		// Clear the plaintext after wrapping so the row never carries it
		// past the persistence boundary.
		fv.SetString("")
	}
	return nil
}

// ErrEnvelopeFieldWrongType is returned when the sibling Envelope field
// exists but has the wrong type. Today this is silently treated as "no
// sibling field" — callers wanting strict checks can branch on it once we
// switch the walker to mandatory-sibling mode (Phase 4 ships permissive).
var ErrEnvelopeFieldWrongType = errors.New("crypto: sibling envelope field is not crypto.Envelope")
