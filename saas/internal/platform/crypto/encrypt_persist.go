package crypto

import (
	"context"
	"reflect"
)

// Encryptor is the persistence-side abstraction implemented by Phase 4's
// OpenBao envelope-encryption code (`internal/platform/crypto/envelope/`,
// to be added in Phase 4). The interface lives here so module authors can
// write the call-site idiom today.
type Encryptor interface {
	// EncryptField returns an Envelope wrapping plaintext for the given
	// deployment-bound key id. aad is the additional authenticated data
	// (typically the row id + column name) and is authenticated but not
	// encrypted.
	EncryptField(ctx context.Context, kid string, plaintext []byte, aad []byte) (Envelope, error)
}

// EncryptPIIFields walks v (must be a non-nil pointer to a struct) and
// invokes enc.EncryptField on every field tagged pii:"true" or
// sensitive:"true". ADR 004 documents the codegen → struct-tag → walker
// pipeline.
//
// The walker is intentionally shallow: it does not recurse into nested
// structs / slices / maps because the OpenAPI tagging contract only
// applies to top-level field shapes. Modules that compose PII-tagged
// child structs into a parent must walk each level explicitly.
//
// Phase 3 ships the walker but the Encryptor implementation lands in
// Phase 4; until then this function is reachable only from test code,
// where a stub Encryptor stands in.
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
		// Today we only support string fields — that covers email / phone /
		// SSN / card numbers. Phase 4 may extend to []byte for raw secrets.
		if fv.Kind() != reflect.String {
			continue
		}
		plaintext := fv.String()
		if plaintext == "" {
			continue
		}
		_, err := enc.EncryptField(ctx, kid, []byte(plaintext), []byte(f.Name))
		if err != nil {
			return err
		}
		// Phase 4 will persist the envelope alongside the row; here we
		// simply zero the plaintext so logs / downstream serialisers
		// cannot leak it.
		fv.SetString("")
	}
	return nil
}
