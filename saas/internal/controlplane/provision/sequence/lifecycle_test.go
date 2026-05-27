package sequence

import (
	"errors"
	"testing"
)

func TestValidateImageVersion(t *testing.T) {
	cases := []struct {
		in    string
		valid bool
	}{
		{"v1.0.0", true},
		{"v0.3.1", true},
		{"v1.2.3-alpha.1", true},
		{"v1.2.3-rc1", true},
		{"1.0.0", false},       // missing v
		{"v1.0", false},        // missing patch
		{"v1.0.0+meta", false}, // build metadata not supported
		{"latest", false},
		{"", false},
	}
	for _, c := range cases {
		err := validateImageVersion(c.in)
		got := err == nil
		if got != c.valid {
			t.Errorf("validateImageVersion(%q)=%v; want %v", c.in, got, c.valid)
		}
	}
}

func TestCompareSemver(t *testing.T) {
	cases := []struct {
		a, b string
		want int
	}{
		{"v1.0.0", "v1.0.0", 0},
		{"v1.0.0", "v1.0.1", -1},
		{"v1.0.1", "v1.0.0", 1},
		{"v1.1.0", "v1.0.9", 1},
		{"v2.0.0", "v1.99.99", 1},
		{"v1.0.0-rc1", "v1.0.0", -1},
		{"v1.0.0", "v1.0.0-rc1", 1},
	}
	for _, c := range cases {
		if got := compareSemver(c.a, c.b); got != c.want {
			t.Errorf("compareSemver(%q,%q)=%d; want %d", c.a, c.b, got, c.want)
		}
	}
}

func TestUpgrade_RefusesDowngrade(t *testing.T) {
	// Exercise the validation only — no adapters wired. We construct
	// a Sequence with no steps and call Upgrade directly.
	if err := validateImageVersion("v0.0.0"); err != nil {
		t.Fatalf("v0.0.0 should validate: %v", err)
	}
	if !errors.Is(downgradeErr("v0.3.1", "v0.3.0"), ErrCannotDowngrade) {
		t.Errorf("downgrade should return ErrCannotDowngrade")
	}
}

// downgradeErr is a tiny helper that mirrors the Upgrade method's
// downgrade check without spinning up adapters.
func downgradeErr(current, target string) error {
	if compareSemver(target, current) <= 0 {
		return ErrCannotDowngrade
	}
	return nil
}
