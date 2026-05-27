// Phase 15 — status command tests.
//
// Two unit-level checks:
//
//   - parseComposeJSON tolerates both NDJSON and JSON-array shapes that
//     docker / podman compose may emit in different versions.
//   - isHealthy maps the State + Health combo to the expected boolean.
//
// printStatus's full pipeline (compose + control-plane HTTP) is
// covered indirectly by init_test.go's testControlPlane helper; we
// keep this file focused on the pure parsing logic.

package main

import "testing"

func TestParseComposeJSON_NDJSON(t *testing.T) {
	raw := []byte(`{"Name":"saas-postgres","Service":"postgres","State":"running","Health":"healthy"}
{"Name":"saas-keycloak","Service":"keycloak","State":"running","Health":"healthy"}`)
	got, err := parseComposeJSON(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(got) != 2 {
		t.Fatalf("expected 2 services, got %d", len(got))
	}
	if got[0].Service != "postgres" || got[1].Service != "keycloak" {
		t.Errorf("services mis-parsed: %+v", got)
	}
}

func TestParseComposeJSON_Array(t *testing.T) {
	raw := []byte(`[{"Name":"a","Service":"a","State":"running","Health":"healthy"}]`)
	got, err := parseComposeJSON(raw)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(got) != 1 || got[0].Service != "a" {
		t.Errorf("array parse failed: %+v", got)
	}
}

func TestParseComposeJSON_Empty(t *testing.T) {
	got, err := parseComposeJSON([]byte("   "))
	if err != nil {
		t.Fatalf("empty parse: %v", err)
	}
	if len(got) != 0 {
		t.Errorf("empty input should yield zero rows, got %d", len(got))
	}
}

func TestIsHealthy(t *testing.T) {
	cases := []struct {
		name    string
		svc     composeService
		healthy bool
	}{
		{"running+healthy", composeService{State: "running", Health: "healthy"}, true},
		{"running+no-health", composeService{State: "running", Health: ""}, true},
		{"running+starting", composeService{State: "running", Health: "starting"}, false},
		{"exited", composeService{State: "exited"}, false},
		{"running+unhealthy", composeService{State: "running", Health: "unhealthy"}, false},
	}
	for _, c := range cases {
		if got := isHealthy(c.svc); got != c.healthy {
			t.Errorf("%s: got %v want %v", c.name, got, c.healthy)
		}
	}
}

func TestTruncate(t *testing.T) {
	cases := []struct {
		in   string
		n    int
		want string
	}{
		{"short", 10, "short"},
		{"exactly10x", 10, "exactly10x"},
		{"longerstring", 8, "longe..."},
		{"ab", 1, "a"},
	}
	for _, c := range cases {
		if got := truncate(c.in, c.n); got != c.want {
			t.Errorf("truncate(%q,%d)=%q want %q", c.in, c.n, got, c.want)
		}
	}
}
