package log

import (
	"log/slog"
	"reflect"
)

// piiTag and sensitiveTag mirror the struct tags emitted by oapi-codegen
// when an OpenAPI field carries `x-oapi-codegen-extra-tags: { pii: "true" }`
// or `{ sensitive: "true" }`. ADR 004 documents the codegen → struct-tag →
// reflection-redactor pipeline.
const (
	piiTag       = "pii"
	sensitiveTag = "sensitive"
)

// scrubStruct returns a slog.Value with any pii/sensitive-tagged fields
// replaced by "[REDACTED]". Returns ok=false when v is not a struct (or a
// pointer to one) — callers fall back to passing the value through.
//
// The walker only descends into structs to keep the hot path cheap; deeply
// nested maps / slices fall outside the codegen-tagging contract and are
// not relevant to PII enforcement.
func scrubStruct(v slog.Value) (slog.Value, bool) {
	rv := reflect.ValueOf(v.Any())
	for rv.Kind() == reflect.Pointer {
		if rv.IsNil() {
			return v, false
		}
		rv = rv.Elem()
	}
	if rv.Kind() != reflect.Struct {
		return v, false
	}
	t := rv.Type()
	attrs := make([]slog.Attr, 0, t.NumField())
	scrubbed := false
	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		if !f.IsExported() {
			continue
		}
		name := jsonNameOf(f)
		if IsRedactedKey(name) || f.Tag.Get(piiTag) == "true" || f.Tag.Get(sensitiveTag) == "true" {
			attrs = append(attrs, slog.String(name, "[REDACTED]"))
			scrubbed = true
			continue
		}
		attrs = append(attrs, slog.Any(name, rv.Field(i).Interface()))
	}
	if !scrubbed {
		return v, false
	}
	return slog.GroupValue(attrs...), true
}

// jsonNameOf returns the json tag name (before any comma options) or the
// field name when no json tag is present. Lowercased so the redactor lookup
// is consistent with HTTP-header-style keys.
func jsonNameOf(f reflect.StructField) string {
	jt := f.Tag.Get("json")
	if jt == "" || jt == "-" {
		return f.Name
	}
	if comma := indexByte(jt, ','); comma >= 0 {
		jt = jt[:comma]
	}
	if jt == "" {
		return f.Name
	}
	return jt
}

func indexByte(s string, b byte) int {
	for i := 0; i < len(s); i++ {
		if s[i] == b {
			return i
		}
	}
	return -1
}
