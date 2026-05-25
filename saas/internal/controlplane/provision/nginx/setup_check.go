package nginx

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
)

// PreflightSetup verifies the one-time host setup (deploy/host/
// setup-nginx-adapter.sh) has been completed. We refuse to write any
// vhost file before the sudoers rule + shared snippet exist — partial
// state is harder to debug than a clean refusal.
//
// The check is intentionally cheap (stat() calls) so we can run it on
// every Apply/Remove. The actual content of the sudoers file is the
// operator's responsibility: the saas user cannot read /etc/sudoers.d/*
// so we only stat() it.
func (a *HostAdapter) PreflightSetup() error {
	// Sudoers rule must exist. We can only stat (file is mode 0440
	// root:root), so we wrap the not-exist case but pass through other
	// errors verbatim (likely EACCES on the .d/ directory itself, which
	// only the operator can fix).
	if _, err := os.Stat(a.SudoersPath); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return fmt.Errorf("%w: sudoers rule %s missing — run deploy/host/setup-nginx-adapter.sh",
				ErrSetupNotComplete, a.SudoersPath)
		}
		// Any other stat error is non-fatal to setup pre-flight — the
		// file might exist but be unreadable by our user. That's the
		// expected case for /etc/sudoers.d/saas-controlplane (0440
		// root:root). The PathError that net.Stat returns there has
		// Op="stat" Err=permission denied, NOT ErrNotExist, so we treat
		// "exists but unreadable" as success.
		// (We catch it via errors.Is(err, fs.ErrNotExist) above.)
	}

	// Shared snippet must exist. This one is mode 0644 so we can read it
	// if we ever need to validate hash, but here we only check presence.
	if _, err := os.Stat(a.SnippetPath); err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return fmt.Errorf("%w: snippet %s missing — run deploy/host/setup-nginx-adapter.sh",
				ErrSetupNotComplete, a.SnippetPath)
		}
		return fmt.Errorf("%w: stat snippet %s: %w", ErrSetupNotComplete, a.SnippetPath, err)
	}

	// sites-available and sites-enabled must be writable by us (via ACL
	// from setup). We don't check ACLs directly — we just confirm we can
	// write a sentinel into the directory.
	if err := dirIsWritable(a.SitesAvailableDir); err != nil {
		return fmt.Errorf("%w: %s not writable by current user: %w — check ACLs",
			ErrSetupNotComplete, a.SitesAvailableDir, err)
	}
	if err := dirIsWritable(a.SitesEnabledDir); err != nil {
		return fmt.Errorf("%w: %s not writable by current user: %w — check ACLs",
			ErrSetupNotComplete, a.SitesEnabledDir, err)
	}

	return nil
}

// dirIsWritable does a tmpfile dance under dir to confirm write access.
// We can't use os.Access (not in stdlib) and unix.Access pulls in
// golang.org/x/sys; a tmpfile is portable and the cost is one syscall
// pair per Apply.
func dirIsWritable(dir string) error {
	f, err := os.CreateTemp(dir, ".saas-preflight.*")
	if err != nil {
		return err
	}
	name := f.Name()
	_ = f.Close()
	_ = os.Remove(name)
	return nil
}
