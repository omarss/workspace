package id_test

import (
	"strings"
	"testing"

	"github.com/omarss/saas/internal/platform/id"
)

func TestNew_HasPrefix(t *testing.T) {
	got := id.New(id.PrefixTenant)
	if !strings.HasPrefix(got, "tenant_") {
		t.Fatalf("expected tenant_ prefix, got %q", got)
	}
	if len(got) != len("tenant_")+26 {
		t.Fatalf("expected 26-char ulid, got len=%d (%q)", len(got), got)
	}
}

func TestNew_Unique(t *testing.T) {
	seen := map[string]struct{}{}
	for i := 0; i < 100; i++ {
		got := id.New(id.PrefixOrg)
		if _, dup := seen[got]; dup {
			t.Fatalf("duplicate ulid: %q", got)
		}
		seen[got] = struct{}{}
	}
}
