package nginx

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
)

// Runner abstracts the privileged command surface (nginx -t / -s reload,
// certbot) so unit tests can swap in a fake that just records argv. The
// real implementation shells out via sudo with a hard-coded list of
// allowed binaries that match the sudoers Cmnd_Alias.
type Runner interface {
	Run(ctx context.Context, name string, args ...string) error
}

// SudoRunner is the production Runner. It refuses to invoke any binary
// outside the sudoers allow-list (defence in depth — sudoers is the real
// gate, but a typo here should fail loudly rather than try `sudo rm`).
type SudoRunner struct {
	// SudoPath defaults to /usr/bin/sudo. Only set for tests.
	SudoPath string
}

// Allowed binaries — keep in sync with deploy/sudoers/saas-controlplane.
var allowedSudoBinaries = map[string]struct{}{
	"/usr/sbin/nginx":    {},
	"/usr/bin/systemctl": {}, // for systemctl reload nginx
	"/usr/bin/certbot":   {},
}

// Run shells out via sudo. The named binary must be in the allow-list
// above; everything else fails with ErrInvalidInput.
func (r *SudoRunner) Run(ctx context.Context, name string, args ...string) error {
	if _, ok := allowedSudoBinaries[name]; !ok {
		return fmt.Errorf("%w: %q not in sudo allow-list", ErrInvalidInput, name)
	}
	sudo := r.SudoPath
	if sudo == "" {
		sudo = "/usr/bin/sudo"
	}
	full := append([]string{"-n", name}, args...)
	// G204 (subprocess from variable) is the whole point of this adapter:
	// we shell out to nginx/certbot. The variable `name` is constrained
	// by the allowedSudoBinaries map above and the kernel-level sudoers
	// allow-list; argv values come from validated ApplyInput / RemoveInput.
	cmd := exec.CommandContext(ctx, sudo, full...) //nolint:gosec
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("sudo %s %v failed: %w: %s", name, args, err, string(out))
	}
	return nil
}

// HostAdapter is the production Adapter. It performs real filesystem
// writes under /etc/nginx and shells out to sudo nginx / certbot. All
// configuration is injectable so the integration tests can point it at a
// tmpfs sandbox + a fake nginx binary.
type HostAdapter struct {
	// SitesAvailableDir is typically /etc/nginx/sites-available. Tests
	// override with t.TempDir().
	SitesAvailableDir string
	// SitesEnabledDir is typically /etc/nginx/sites-enabled.
	SitesEnabledDir string
	// SnippetPath is where the security-headers snippet must live for
	// pre-flight to consider setup complete. Default
	// /etc/nginx/snippets/saas-security-headers.conf.
	SnippetPath string
	// SudoersPath is /etc/sudoers.d/saas-controlplane. Pre-flight checks
	// the file exists; we cannot read it as the saas user, so we only
	// stat() — the actual content is the operator's responsibility.
	SudoersPath string
	// NginxBin is /usr/sbin/nginx. Tests override.
	NginxBin string
	// CertbotBin is /usr/bin/certbot. Tests override.
	CertbotBin string
	// Runner is the sudo-shell-out adapter. Tests inject a recorder.
	Runner Runner

	renderer *renderer
}

// NewHostAdapter returns the production adapter configured for the
// homelab host. Override the exported fields after construction in tests.
func NewHostAdapter() (*HostAdapter, error) {
	r, err := newRenderer()
	if err != nil {
		return nil, err
	}
	return &HostAdapter{
		SitesAvailableDir: "/etc/nginx/sites-available",
		SitesEnabledDir:   "/etc/nginx/sites-enabled",
		SnippetPath:       "/etc/nginx/snippets/saas-security-headers.conf",
		SudoersPath:       "/etc/sudoers.d/saas-controlplane",
		NginxBin:          "/usr/sbin/nginx",
		CertbotBin:        "/usr/bin/certbot",
		Runner:            &SudoRunner{},
		renderer:          r,
	}, nil
}

// vhostPath is the canonical on-disk location of the vhost file for a
// given deployment.
func (a *HostAdapter) vhostPath(deploymentID string) string {
	return filepath.Join(a.SitesAvailableDir, "saas-"+deploymentID+".conf")
}

// symlinkPath is the sites-enabled symlink target.
func (a *HostAdapter) symlinkPath(deploymentID string) string {
	return filepath.Join(a.SitesEnabledDir, "saas-"+deploymentID+".conf")
}

// Apply implements Adapter. The flow is:
//
//  1. Validate input.
//  2. Pre-flight host setup (sudoers + snippet present).
//  3. Render template.
//  4. Backup existing vhost (if any) to a sibling .bak file — so we can
//     restore it on `nginx -t` failure.
//  5. Atomic write of the rendered content (tmp + fsync + rename).
//  6. Idempotent symlink into sites-enabled.
//  7. `sudo nginx -t` to validate combined config.
//     - On failure: restore the backup (or unlink) and return.
//  8. `sudo nginx -s reload`.
//  9. Remove the backup file (success).
func (a *HostAdapter) Apply(ctx context.Context, in ApplyInput) error {
	if err := in.Validate(); err != nil {
		return err
	}
	if err := a.PreflightSetup(); err != nil {
		return err
	}
	if a.renderer == nil {
		r, err := newRenderer()
		if err != nil {
			return err
		}
		a.renderer = r
	}
	content, err := a.renderer.render(in)
	if err != nil {
		return err
	}

	vhost := a.vhostPath(in.DeploymentID)
	backup := vhost + ".bak"
	hadExisting, err := backupExisting(vhost, backup)
	if err != nil {
		return fmt.Errorf("backup existing vhost: %w", err)
	}

	if err := atomicWrite(vhost, content, 0o644); err != nil {
		// Roll back: restore the backup so we don't lose the prior file.
		if hadExisting {
			_ = os.Rename(backup, vhost)
		}
		return fmt.Errorf("write vhost: %w", err)
	}

	if err := ensureSymlink(vhost, a.symlinkPath(in.DeploymentID)); err != nil {
		// Clean up the file we just wrote so we don't leave a dangling
		// sites-available entry the next reload will pick up anyway.
		if hadExisting {
			_ = os.Rename(backup, vhost)
		} else {
			_ = os.Remove(vhost)
		}
		return fmt.Errorf("ensure symlink: %w", err)
	}

	if err := a.Runner.Run(ctx, a.NginxBin, "-t"); err != nil {
		// `nginx -t` failed; the host's current config is still valid
		// (nginx never reloaded the broken file). Restore the prior
		// vhost (or unlink) so the next operator-triggered reload picks
		// up the known-good state.
		if hadExisting {
			_ = os.Rename(backup, vhost)
		} else {
			_ = os.Remove(a.symlinkPath(in.DeploymentID))
			_ = os.Remove(vhost)
		}
		return fmt.Errorf("%w: %w", ErrConfigTestFailed, err)
	}

	if err := a.Runner.Run(ctx, a.NginxBin, "-s", "reload"); err != nil {
		// `-t` passed; do NOT roll back the file — it is valid, just
		// not yet reloaded. Operator can re-reload manually.
		return fmt.Errorf("%w: %w", ErrReloadFailed, err)
	}

	// Success — drop the backup.
	if hadExisting {
		_ = os.Remove(backup)
	}
	return nil
}

// Remove implements Adapter. Symmetric to Apply: unlink the symlink, then
// remove the vhost file, then validate + reload. We do NOT delete the
// cert — Phase 12e composes destroy and decides when retention expires.
func (a *HostAdapter) Remove(ctx context.Context, in RemoveInput) error {
	if err := in.Validate(); err != nil {
		return err
	}
	if err := a.PreflightSetup(); err != nil {
		return err
	}

	link := a.symlinkPath(in.DeploymentID)
	vhost := a.vhostPath(in.DeploymentID)

	// Idempotent: missing files are fine — destroy may run twice.
	if err := os.Remove(link); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("remove symlink: %w", err)
	}
	if err := os.Remove(vhost); err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("remove vhost: %w", err)
	}

	if err := a.Runner.Run(ctx, a.NginxBin, "-t"); err != nil {
		return fmt.Errorf("%w: %w", ErrConfigTestFailed, err)
	}
	if err := a.Runner.Run(ctx, a.NginxBin, "-s", "reload"); err != nil {
		return fmt.Errorf("%w: %w", ErrReloadFailed, err)
	}
	return nil
}

// atomicWrite writes content to path via a sibling tmp file + fsync +
// rename. The mode is applied to the tmp file BEFORE rename so the
// destination never appears with a wider mode.
//
// We also verify the post-rename mode in case the operator's umask is
// being weird (workspace_personal/CLAUDE.md gotcha #3: `sudo mkdir`
// inherits 077 here). The vhost file MUST end up 0644 or the
// post-certbot edit step will refuse.
func atomicWrite(path string, content []byte, mode fs.FileMode) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, filepath.Base(path)+".tmp.*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	// Ensure cleanup if anything below fails before the final rename.
	defer func() {
		_ = os.Remove(tmpName)
	}()
	if _, err := tmp.Write(content); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Chmod(mode); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		return err
	}
	// fsync the parent directory so the rename is durable across crashes.
	// G304: `dir` here is filepath.Dir of the caller-controlled path; the
	// adapter's only caller passes paths under SitesAvailableDir which is
	// itself a configured (not user-supplied) directory.
	if d, err := os.Open(dir); err == nil { //nolint:gosec
		_ = d.Sync()
		_ = d.Close()
	}

	// Defensive post-condition check (gotcha #3 above).
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	if info.Mode().Perm() != mode {
		return fmt.Errorf("post-rename mode = %v, want %v (umask issue?)", info.Mode().Perm(), mode)
	}
	return nil
}

// backupExisting renames an existing file to .bak in place. Returns
// (true, nil) if a backup was made, (false, nil) if no source existed.
func backupExisting(src, dst string) (bool, error) {
	if _, err := os.Stat(src); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return false, nil
		}
		return false, err
	}
	if err := os.Rename(src, dst); err != nil {
		return false, err
	}
	return true, nil
}

// ensureSymlink makes the link idempotently. If the link already points at
// target, we leave it alone (preserves the inode + mtime so nginx reload
// scanning skips). If the link points somewhere else, we replace it.
func ensureSymlink(target, link string) error {
	if existing, err := os.Readlink(link); err == nil {
		if existing == target {
			return nil
		}
		if err := os.Remove(link); err != nil {
			return err
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		// If it exists but is not a symlink, that's a hard fail — the
		// operator put something there by hand.
		return fmt.Errorf("symlink target %s is not a symlink: %w", link, err)
	}
	return os.Symlink(target, link)
}
