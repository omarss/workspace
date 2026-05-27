package workflows

import (
	"context"
	"fmt"
	"net"
	"strings"
	"time"

	cp "github.com/omarss/saas/sdk/go/controlplane"
	"github.com/omarss/saas/sdk/go/internal/idem"
)

// AttachCustomDomainInput targets POST /control/v1/deployments/{id}/domains.
// WaitForDNS controls whether the workflow polls DNS for the verification
// TXT record and then calls the verify endpoint. PollInterval / Timeout
// gate the loop; zero-values use sensible defaults (15s / 10m).
//
// DNSResolver is overridable for tests; nil falls back to net.DefaultResolver.
type AttachCustomDomainInput struct {
	DeploymentID string
	Domain       string

	WaitForDNS   bool
	PollInterval time.Duration
	Timeout      time.Duration
	DNSResolver  *net.Resolver
}

// AttachCustomDomain wraps Attach (and optionally Verify) into a single
// workflow. The Attach response carries the TXT record the caller must
// publish; if WaitForDNS is true, the workflow polls until the record
// appears in DNS, then calls Verify.
//
// Each HTTP call gets its OWN auto-generated Idempotency-Key — Attach and
// Verify are distinct state transitions per AGENTS.md §5.2.
func AttachCustomDomain(
	ctx context.Context,
	client *cp.ClientWithResponses,
	in AttachCustomDomainInput,
	opts ...Option,
) (cp.DeploymentDomain, error) {
	o := collect(opts)
	attachKey := o.idemKey
	if attachKey == "" {
		attachKey = idem.New()
	}

	attachRes, err := client.AttachDeploymentDomainWithResponse(ctx, in.DeploymentID,
		&cp.AttachDeploymentDomainParams{IdempotencyKey: attachKey},
		cp.AttachDomainRequest{Domain: in.Domain})
	if err != nil {
		return cp.DeploymentDomain{}, err
	}
	if attachRes.StatusCode() != 201 || attachRes.JSON201 == nil {
		return cp.DeploymentDomain{}, parseProblem(attachRes.StatusCode(), attachRes.Body)
	}
	domain := attachRes.JSON201.Data

	if !in.WaitForDNS {
		return domain, nil
	}

	resolver := in.DNSResolver
	if resolver == nil {
		resolver = net.DefaultResolver
	}
	if err := waitDNSTXT(ctx, resolver,
		domain.VerificationRecord.RecordName,
		domain.VerificationRecord.RecordValue,
		in.PollInterval, in.Timeout); err != nil {
		return domain, err
	}

	// Verify is a separate state transition: fresh idempotency key.
	verifyRes, err := client.VerifyDeploymentDomainWithResponse(ctx, in.DeploymentID, domain.Id,
		&cp.VerifyDeploymentDomainParams{IdempotencyKey: idem.New()})
	if err != nil {
		return domain, err
	}
	if verifyRes.StatusCode() != 200 || verifyRes.JSON200 == nil {
		return domain, parseProblem(verifyRes.StatusCode(), verifyRes.Body)
	}
	return verifyRes.JSON200.Data, nil
}

// waitDNSTXT blocks until the named TXT record contains the expected
// value, the ctx is cancelled, or the timeout elapses. The check uses the
// caller-supplied resolver so tests can stub it.
func waitDNSTXT(
	ctx context.Context,
	resolver *net.Resolver,
	recordName, recordValue string,
	pollInterval, timeout time.Duration,
) error {
	if pollInterval <= 0 {
		pollInterval = 15 * time.Second
	}
	if timeout <= 0 {
		timeout = 10 * time.Minute
	}
	deadline := time.Now().Add(timeout)
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	for {
		txts, err := resolver.LookupTXT(ctx, recordName)
		if err == nil {
			for _, t := range txts {
				if strings.TrimSpace(t) == strings.TrimSpace(recordValue) {
					return nil
				}
			}
		}
		// Ignore lookup errors (NXDOMAIN, temp failure) and keep polling
		// until deadline; surface only the deadline error.
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if time.Now().After(deadline) {
				return fmt.Errorf("dns TXT %s did not match %q within %s", recordName, recordValue, timeout)
			}
		}
	}
}
