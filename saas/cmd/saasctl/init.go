// Phase 15 — saasctl init wizard.
//
// Implements ADR 020: an 8-step bootstrap that takes an operator from
// `git clone` to a usable platform in one command. Each step is its own
// function in init_<step>.go so it is independently testable and the
// orchestrator stays simple. The wizard is idempotent: re-running picks
// up from the last successful step (each step detects existing state
// and reports "(already done)").
//
// The wizard orchestrates EXISTING tooling — it shells out to `make`
// targets (compose-up, openbao-init, migrate, operators-realm-import)
// rather than re-implementing OpenBao / Keycloak / Postgres bootstrap
// in Go. See ADR 020 §Decision for the rationale.

package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/spf13/cobra"
	"gopkg.in/yaml.v3"
)

// initConfig captures the wizard inputs. Defaults come from a YAML file
// (default path: ~/.saas/init.yaml); CLI flags override the file.
type initConfig struct {
	// Project + environment slugs for the first Deployment.
	Project     string `yaml:"project"`
	Environment string `yaml:"environment"`

	// Image_version for the first Deployment (must match a tag on the
	// data-plane image). Defaults to the env var SAAS_IMAGE_VERSION or
	// the literal "dev" when nothing is set.
	ImageVersion string `yaml:"image_version"`

	// Operator section is metadata stamped on the first operator the
	// wizard creates (when the operator-login step is run end-to-end).
	Operator struct {
		Email       string `yaml:"email"`
		DisplayName string `yaml:"display_name"`
	} `yaml:"operator"`

	// Wizard control flags (not part of the YAML schema).
	Yes             bool   `yaml:"-"`
	OperatorTokenFn string `yaml:"-"`
	WriteSecretFile string `yaml:"-"`
	ControlPlaneURL string `yaml:"-"`
	ConfigPath      string `yaml:"-"`
	ProjectDir      string `yaml:"-"`
	// makeRunner is overridable for tests so the wizard can be exercised
	// without invoking real `make`.
	makeRunner func(ctx context.Context, target string, env []string, stdout, stderr io.Writer) error `yaml:"-"`

	// composeChecker is overridable for tests; nil falls back to the
	// real `docker compose ps` runtime probe.
	composeChecker func(ctx context.Context, dir string) ([]composeService, error) `yaml:"-"`

	// lastProvision is stamped by runProvision and consumed by
	// printSummary so the summary banner can render the bootstrap
	// secret without re-fetching.
	lastProvision *provisionResult `yaml:"-"`
}

// initStep is one ordered phase of the wizard. The fn signature returns
// (string, error): the string is an optional human-readable status note
// (e.g. "already done", "skipped") which the orchestrator prints next
// to "OK".
type initStep struct {
	name string
	fn   func(ctx context.Context, cfg *initConfig) (string, error)
}

// initCommand builds the `saasctl init` cobra command. Wired into main()
// in place of the Phase-2 placeholder.
func initCommand() *cobra.Command {
	cfg := &initConfig{}
	c := &cobra.Command{
		Use:   "init",
		Short: "Bootstrap a local SaaS stack end-to-end.",
		Long: `Bootstrap a local SaaS stack end-to-end.

Runs an 8-step idempotent wizard:
  1. compose-up      bring up postgres, openbao, keycloak, mailhog, novu, prism
  2. wait-healthy    poll docker compose health until services are ready
  3. openbao-init    enable transit + kv + approle + kubernetes auth
  4. realm-import    import the operators realm into Keycloak
  5. migrate         apply control-plane + data-plane migrations
  6. operator-login  obtain an operator bearer token (PKCE — see flag)
  7. provision       create the first Deployment ($project/$env)
  8. summary         print the bootstrap API key + URLs

Re-running is idempotent: each step detects existing state and is a no-op.

The PKCE login flow is deferred until the operators-realm gocloak client is
wired (see ADR 020). Use --operator-token-file to skip step 6 in the
interim: the wizard treats the contents of that file as the operator
bearer token for the provision step.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			if err := loadInitConfig(cfg); err != nil {
				return err
			}
			return runInit(cmd.Context(), cfg)
		},
	}
	flags := c.Flags()
	flags.StringVar(&cfg.ConfigPath, "config", "", "Path to init.yaml (default: ~/.saas/init.yaml; falls back to ./init.yaml).")
	flags.StringVar(&cfg.Project, "project", "", "Project slug for the first Deployment (default: from config or 'default').")
	flags.StringVar(&cfg.Environment, "environment", "", "Environment slug (default: from config or 'dev').")
	flags.StringVar(&cfg.ImageVersion, "image", "", "Image version (default: from config or $SAAS_IMAGE_VERSION or 'dev').")
	flags.StringVar(&cfg.OperatorTokenFn, "operator-token-file", "", "Path to a file containing the operator bearer token (skips the PKCE login step).")
	flags.StringVar(&cfg.WriteSecretFile, "write-secret-file", "", "If set, append the bootstrap secret to this file (instead of STDOUT only).")
	flags.StringVar(&cfg.ControlPlaneURL, "control-plane-url", controlPlaneURL, "Control plane base URL for the provision step.")
	flags.StringVar(&cfg.ProjectDir, "project-dir", "", "Directory containing the saas/ Makefile (default: walk up from cwd until a Makefile is found).")
	flags.BoolVar(&cfg.Yes, "yes", false, "Run unattended (no prompts).")
	return c
}

// runInit dispatches the 8 steps in order. The first failure aborts;
// successful steps stay applied so the next run picks up where this
// one stopped.
func runInit(ctx context.Context, cfg *initConfig) error {
	if cfg.makeRunner == nil {
		cfg.makeRunner = realMakeRunner
	}
	steps := []initStep{
		{"compose-up", runComposeUp},
		{"wait-healthy", waitHealthy},
		{"openbao-init", runOpenBaoInit},
		{"realm-import", runRealmImport},
		{"migrate", runMigrate},
		{"operator-login", runOperatorLogin},
		{"provision", runProvision},
		{"summary", printSummary},
	}
	for _, s := range steps {
		fmt.Printf("==> %-16s ... ", s.name)
		note, err := s.fn(ctx, cfg)
		if err != nil {
			fmt.Println("FAIL")
			return fmt.Errorf("%s: %w", s.name, err)
		}
		if note == "" {
			fmt.Println("OK")
		} else {
			fmt.Printf("OK (%s)\n", note)
		}
	}
	return nil
}

// loadInitConfig hydrates the config from (a) the YAML file at the
// resolved path (if present) and (b) CLI flag overrides. The CLI
// flags take precedence over the file. Defaults fill in anything still
// blank after both.
func loadInitConfig(cfg *initConfig) error {
	path := cfg.ConfigPath
	if path == "" {
		home, _ := os.UserHomeDir()
		if home != "" {
			candidate := filepath.Join(home, ".saas", "init.yaml")
			if _, err := os.Stat(candidate); err == nil {
				path = candidate
			}
		}
		if path == "" {
			if _, err := os.Stat("init.yaml"); err == nil {
				path = "init.yaml"
			}
		}
	}
	if path != "" {
		raw, err := os.ReadFile(path) // #nosec G304 — operator-supplied config path
		if err != nil {
			return fmt.Errorf("read init config %q: %w", path, err)
		}
		// Decode into a temporary so CLI overrides (already on cfg)
		// are not stomped by the YAML defaults.
		var file initConfig
		if err := yaml.Unmarshal(raw, &file); err != nil {
			return fmt.Errorf("parse init config %q: %w", path, err)
		}
		if cfg.Project == "" {
			cfg.Project = file.Project
		}
		if cfg.Environment == "" {
			cfg.Environment = file.Environment
		}
		if cfg.ImageVersion == "" {
			cfg.ImageVersion = file.ImageVersion
		}
		if cfg.Operator.Email == "" {
			cfg.Operator.Email = file.Operator.Email
		}
		if cfg.Operator.DisplayName == "" {
			cfg.Operator.DisplayName = file.Operator.DisplayName
		}
	}
	// Final defaults.
	if cfg.Project == "" {
		cfg.Project = "default"
	}
	if cfg.Environment == "" {
		cfg.Environment = "dev"
	}
	if cfg.ImageVersion == "" {
		if env := os.Getenv("SAAS_IMAGE_VERSION"); env != "" {
			cfg.ImageVersion = env
		} else {
			cfg.ImageVersion = "dev"
		}
	}
	if cfg.Operator.Email == "" {
		cfg.Operator.Email = "admin@localhost"
	}
	if cfg.Operator.DisplayName == "" {
		cfg.Operator.DisplayName = "Admin"
	}
	if cfg.ControlPlaneURL == "" {
		cfg.ControlPlaneURL = controlPlaneURL
	}
	if cfg.ProjectDir == "" {
		dir, err := findProjectDir()
		if err != nil {
			return err
		}
		cfg.ProjectDir = dir
	}
	return nil
}

// findProjectDir walks up from cwd looking for a Makefile. The wizard
// invokes `make -C <dir>` from this path so it can run from any
// subdirectory of the repo.
func findProjectDir() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("getwd: %w", err)
	}
	d := cwd
	for {
		if _, err := os.Stat(filepath.Join(d, "Makefile")); err == nil {
			// Also verify it's the saas Makefile, not a sibling one.
			if _, err := os.Stat(filepath.Join(d, "openapi")); err == nil {
				return d, nil
			}
		}
		parent := filepath.Dir(d)
		if parent == d {
			return cwd, fmt.Errorf("no saas Makefile found walking up from %q", cwd)
		}
		d = parent
	}
}

// secretBanner emits a fenced "COPY THIS NOW" block around a secret.
// Centralised so every step that surfaces a one-time secret renders
// identically — and so the test suite can grep for the banner shape.
func secretBanner(label, secret string) string {
	bar := strings.Repeat("=", 70)
	return strings.Join([]string{
		bar,
		fmt.Sprintf("COPY THIS NOW — %s", label),
		bar,
		secret,
		bar,
	}, "\n")
}

// nowUTC is a swap point for deterministic testing.
var nowUTC = func() time.Time { return time.Now().UTC() }
