package scrape

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadCredentials_Valid(t *testing.T) {
	path := filepath.Join(t.TempDir(), "cookies.json")
	if err := os.WriteFile(path, []byte(`{"auth_token":"abc","ct0":"def"}`), 0o600); err != nil {
		t.Fatalf("seed: %v", err)
	}
	creds, err := LoadCredentials(path)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if creds.AuthToken != "abc" || creds.CT0 != "def" {
		t.Errorf("expected abc/def, got %+v", creds)
	}
}

func TestLoadCredentials_MissingFile(t *testing.T) {
	_, err := LoadCredentials(filepath.Join(t.TempDir(), "nope.json"))
	if err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestLoadCredentials_EmptyFields(t *testing.T) {
	for _, body := range []string{
		`{"auth_token":"","ct0":"x"}`,
		`{"auth_token":"x","ct0":""}`,
		`{"auth_token":"","ct0":""}`,
		`{}`,
	} {
		path := filepath.Join(t.TempDir(), "cookies.json")
		_ = os.WriteFile(path, []byte(body), 0o600)
		if _, err := LoadCredentials(path); err == nil {
			t.Errorf("expected error for %q, got nil", body)
		}
	}
}

func TestLoadCredentials_Garbage(t *testing.T) {
	path := filepath.Join(t.TempDir(), "cookies.json")
	_ = os.WriteFile(path, []byte("not json"), 0o600)
	if _, err := LoadCredentials(path); err == nil {
		t.Fatal("expected parse error")
	}
}
