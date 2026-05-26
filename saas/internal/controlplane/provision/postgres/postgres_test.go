package postgres

import (
	"errors"
	"strings"
	"testing"
)

// Unit tests for the pure helpers (validation, naming, password
// generation, DSN manipulation). The full Apply/Remove/VerifyRLS flow
// is covered by the integration test in postgres_integration_test.go;
// these tests run without Docker and complete in milliseconds.

func TestValidateApplyInput(t *testing.T) {
	t.Parallel()
	cases := []struct {
		name    string
		in      ApplyInput
		wantErr error
	}{
		{
			name: "happy",
			in: ApplyInput{
				DeploymentID:    "dep_01H",
				ProjectSlug:     "acme",
				EnvironmentSlug: "prod",
				AdminDSN:        "postgres://saas:saas@localhost:55432/saas",
			},
		},
		{
			name: "empty deployment_id",
			in: ApplyInput{
				ProjectSlug:     "acme",
				EnvironmentSlug: "prod",
				AdminDSN:        "postgres://x/y",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "unsafe deployment_id",
			in: ApplyInput{
				DeploymentID:    "dep_01H'; DROP",
				ProjectSlug:     "acme",
				EnvironmentSlug: "prod",
				AdminDSN:        "postgres://x/y",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "project_slug starts with digit",
			in: ApplyInput{
				DeploymentID:    "dep_01H",
				ProjectSlug:     "1acme",
				EnvironmentSlug: "prod",
				AdminDSN:        "postgres://x/y",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "project_slug has dash",
			in: ApplyInput{
				DeploymentID:    "dep_01H",
				ProjectSlug:     "ac-me",
				EnvironmentSlug: "prod",
				AdminDSN:        "postgres://x/y",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "combined name exceeds 63 chars",
			in: ApplyInput{
				DeploymentID:    "dep_01H",
				ProjectSlug:     strings.Repeat("a", 30),
				EnvironmentSlug: strings.Repeat("b", 30),
				AdminDSN:        "postgres://x/y",
			},
			// 5 (saas_) + 30 + 1 (_) + 30 + 4 (_app) = 70 > 63.
			wantErr: ErrInvalidName,
		},
		{
			name: "empty admin_dsn",
			in: ApplyInput{
				DeploymentID:    "dep_01H",
				ProjectSlug:     "acme",
				EnvironmentSlug: "prod",
			},
			wantErr: ErrInvalidInput,
		},
		{
			name: "reserved name",
			in: ApplyInput{
				DeploymentID:    "dep_01H",
				ProjectSlug:     "control",
				EnvironmentSlug: "plane",
				AdminDSN:        "postgres://x/y",
			},
			// saas_control_plane is not reserved; ensure plain
			// `saas` reserved check works via direct slug.
			// No-op assertion here; covered by direct test below.
			wantErr: nil,
		},
	}
	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			err := tc.in.Validate()
			if tc.wantErr == nil {
				if err != nil {
					t.Fatalf("Validate() = %v, want nil", err)
				}
				return
			}
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("Validate() = %v, want %v", err, tc.wantErr)
			}
		})
	}
}

func TestBuildDBNameReservedName(t *testing.T) {
	t.Parallel()
	// Force the buildDBName helper to compose a name that is in
	// reservedNames. The reserved list includes `saas_controlplane`,
	// produced by project=controlplane, env=<single-char>. We use
	// "x" so the slug passes the alphabet check.
	//
	// First, prove the happy buildDBName works against a non-reserved
	// composition.
	if _, err := buildDBName("acme", "prod"); err != nil {
		t.Fatalf("happy buildDBName failed: %v", err)
	}
	// Now force a reserved composition by patching reservedNames for
	// the duration of this test — exercising the catch path without
	// special-casing real names.
	const reserved = "saas_acme_prod"
	prev, was := reservedNames[reserved]
	reservedNames[reserved] = struct{}{}
	defer func() {
		if was {
			reservedNames[reserved] = prev
		} else {
			delete(reservedNames, reserved)
		}
	}()
	if _, err := buildDBName("acme", "prod"); !errors.Is(err, ErrInvalidName) {
		t.Fatalf("reserved buildDBName err = %v, want ErrInvalidName", err)
	}
}

func TestValidateRemoveInputRequiresConfirmation(t *testing.T) {
	t.Parallel()
	in := RemoveInput{
		DeploymentID:    "dep_01H",
		ProjectSlug:     "acme",
		EnvironmentSlug: "prod",
		AdminDSN:        "postgres://x/y",
		// ConfirmDropDatabase is intentionally false
	}
	err := in.Validate()
	if !errors.Is(err, ErrConfirmationRequired) {
		t.Fatalf("Validate() = %v, want ErrConfirmationRequired", err)
	}
}

func TestBuildNames(t *testing.T) {
	t.Parallel()
	db, err := buildDBName("acme", "prod")
	if err != nil {
		t.Fatalf("buildDBName: %v", err)
	}
	if db != "saas_acme_prod" {
		t.Fatalf("buildDBName = %q, want saas_acme_prod", db)
	}
	role, err := buildRoleName("acme", "prod")
	if err != nil {
		t.Fatalf("buildRoleName: %v", err)
	}
	if role != "saas_acme_prod_app" {
		t.Fatalf("buildRoleName = %q, want saas_acme_prod_app", role)
	}
}

func TestQuoteIdentifierDoublesQuotes(t *testing.T) {
	t.Parallel()
	// Pathological input — validateSlug rejects this before we get
	// here in production, but the quoter must still be safe.
	got := quoteIdentifier(`abc"def`)
	want := `"abc""def"`
	if got != want {
		t.Fatalf("quoteIdentifier(%q) = %q, want %q", `abc"def`, got, want)
	}
}

func TestQuoteLiteralEscapesQuotes(t *testing.T) {
	t.Parallel()
	got := quoteLiteral(`it's`)
	want := `'it''s'`
	if got != want {
		t.Fatalf("quoteLiteral(%q) = %q, want %q", `it's`, got, want)
	}
}

func TestGenerateRolePasswordCharset(t *testing.T) {
	t.Parallel()
	for i := 0; i < 64; i++ {
		p, err := generateRolePassword()
		if err != nil {
			t.Fatalf("generateRolePassword: %v", err)
		}
		if len(p) != 40 {
			t.Fatalf("password len = %d, want 40", len(p))
		}
		for _, r := range p {
			switch {
			case r >= 'a' && r <= 'z':
			case r >= 'A' && r <= 'Z':
			case r >= '0' && r <= '9':
			default:
				t.Fatalf("password %q contains unsafe char %q", p, r)
			}
		}
	}
}

func TestGenerateRolePasswordUnique(t *testing.T) {
	t.Parallel()
	// Generate a batch and assert no duplicates. The birthday bound
	// for 40 alphanumeric chars / ~238 bits is astronomical; we set
	// the bar low (16 samples) so the test is fast and the failure
	// would still indicate a CSPRNG bug rather than statistical
	// noise.
	seen := make(map[string]struct{}, 16)
	for i := 0; i < 16; i++ {
		p, err := generateRolePassword()
		if err != nil {
			t.Fatalf("generateRolePassword: %v", err)
		}
		if _, dup := seen[p]; dup {
			t.Fatalf("duplicate password %q", p)
		}
		seen[p] = struct{}{}
	}
}

func TestDSNSwitchDatabaseURL(t *testing.T) {
	t.Parallel()
	got, err := dsnSwitchDatabase("postgres://saas:saas@localhost:55432/postgres?sslmode=disable", "saas_acme_prod")
	if err != nil {
		t.Fatalf("dsnSwitchDatabase: %v", err)
	}
	// Order of query params is library-defined; assert substring.
	if !strings.Contains(got, "/saas_acme_prod?") {
		t.Fatalf("dsnSwitchDatabase = %q, want /saas_acme_prod? substring", got)
	}
	if !strings.Contains(got, "sslmode=disable") {
		t.Fatalf("dsnSwitchDatabase = %q, want sslmode=disable preserved", got)
	}
}

func TestDSNSwitchDatabaseKVForm(t *testing.T) {
	t.Parallel()
	got, err := dsnSwitchDatabase("host=localhost port=5432 user=saas password=saas dbname=postgres sslmode=disable", "saas_acme_prod")
	if err != nil {
		t.Fatalf("dsnSwitchDatabase: %v", err)
	}
	if !strings.Contains(got, "dbname=saas_acme_prod") {
		t.Fatalf("dsnSwitchDatabase = %q, want dbname=saas_acme_prod substring", got)
	}
}

func TestBuildDSN(t *testing.T) {
	t.Parallel()
	got, err := buildDSN("postgres://admin:adminpw@host.example:5432/postgres?sslmode=verify-full", "saas_acme_prod", "saas_acme_prod_app", "rolepw123", "")
	if err != nil {
		t.Fatalf("buildDSN: %v", err)
	}
	if !strings.HasPrefix(got, "postgres://saas_acme_prod_app:rolepw123@host.example:5432/saas_acme_prod?") {
		t.Fatalf("buildDSN = %q, missing expected prefix", got)
	}
	if !strings.Contains(got, "sslmode=verify-full") {
		t.Fatalf("buildDSN = %q, want sslmode=verify-full inherited", got)
	}
}

func TestBuildDSNHostOverride(t *testing.T) {
	t.Parallel()
	got, err := buildDSN("postgres://admin:adminpw@control.internal:5432/postgres?sslmode=disable", "saas_acme_prod", "saas_acme_prod_app", "rolepw123", "data.internal")
	if err != nil {
		t.Fatalf("buildDSN: %v", err)
	}
	if !strings.Contains(got, "@data.internal:5432/") {
		t.Fatalf("buildDSN = %q, want data.internal host", got)
	}
}

func TestAppendQueryParam(t *testing.T) {
	t.Parallel()
	got := appendQueryParam("postgres://x/y", "k", "v")
	if got != "postgres://x/y?k=v" {
		t.Fatalf("appendQueryParam (no q) = %q", got)
	}
	got = appendQueryParam("postgres://x/y?a=b", "k", "v")
	if got != "postgres://x/y?a=b&k=v" {
		t.Fatalf("appendQueryParam (with q) = %q", got)
	}
}

func TestApplyInputDBAndRoleNames(t *testing.T) {
	t.Parallel()
	in := ApplyInput{
		DeploymentID:    "dep_01H",
		ProjectSlug:     "acme",
		EnvironmentSlug: "prod",
		AdminDSN:        "postgres://x/y",
	}
	if err := in.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
	if in.DBName() != "saas_acme_prod" {
		t.Fatalf("DBName = %q", in.DBName())
	}
	if in.RoleName() != "saas_acme_prod_app" {
		t.Fatalf("RoleName = %q", in.RoleName())
	}
}
