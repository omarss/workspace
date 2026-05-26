package k3s

import (
	"context"
	"fmt"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

// HostAdapter is the concrete Adapter the saasctl debug subcommand and
// (eventually) the Phase 12e composite provisioner use. It holds the
// client-go clientset, the kustomize renderer, and the rollout timeout.
// All fields are immutable after construction; the type is safe to
// share across goroutines.
type HostAdapter struct {
	cs             kubernetes.Interface
	kustomizer     *Kustomizer
	rolloutTimeout time.Duration
}

// Option is the functional-options pattern for NewHostAdapter — keeps
// the constructor signature stable as Phase 12e adds knobs (metrics,
// tracing, retry policy).
type Option func(*HostAdapter)

// WithRolloutTimeout overrides the default 5-minute Deployment rollout
// wait. The composite provisioner uses this to respect a Deployment's
// metadata.rollout_timeout_seconds override (Phase 12e).
func WithRolloutTimeout(d time.Duration) Option {
	return func(a *HostAdapter) {
		if d > 0 {
			a.rolloutTimeout = d
		}
	}
}

// NewHostAdapter returns a HostAdapter wired against the kubeconfig
// the ClientConfig resolves to. The clientset construction error
// surfaces fast (before any Apply) so the saasctl debug helper can
// print a clean remediation when the operator forgot to export
// KUBECONFIG.
func NewHostAdapter(cfg ClientConfig, opts ...Option) (*HostAdapter, error) {
	cs, _, err := LoadClientset(cfg)
	if err != nil {
		return nil, err
	}
	return newHostAdapterFromClientset(cs, opts...), nil
}

// newHostAdapterFromClientset is the seam unit tests use to inject a
// fake clientset (k8s.io/client-go/kubernetes/fake). Unexported so
// production callers go through the kubeconfig-resolving constructor.
func newHostAdapterFromClientset(cs kubernetes.Interface, opts ...Option) *HostAdapter {
	a := &HostAdapter{
		cs:             cs,
		kustomizer:     NewKustomizer(),
		rolloutTimeout: defaultRolloutTimeout,
	}
	for _, opt := range opts {
		opt(a)
	}
	return a
}

// Apply renders + applies the manifest set for one Deployment, then
// blocks on the data-plane Deployment rollout. Idempotent: re-running
// with the same input is a no-op modulo SSA `Force` overwriting any
// drift the operator introduced via direct kubectl edits.
func (a *HostAdapter) Apply(ctx context.Context, in ApplyInput) error {
	if err := in.Validate(); err != nil {
		return err
	}
	yamlBytes, err := a.kustomizer.Render(in)
	if err != nil {
		return err
	}
	objs, err := DecodeManifest(yamlBytes)
	if err != nil {
		return err
	}
	if err := applyAll(ctx, a.cs, objs); err != nil {
		return err
	}
	return waitForRollout(ctx, a.cs, in.NamespaceName(), a.rolloutTimeout)
}

// Remove deletes the Deployment's namespace, which cascades to all
// namespaced resources inside (pods, services, network policies,
// service accounts). Idempotent: deleting a namespace that does not
// exist returns nil so retry-on-failure flows do not have to
// special-case the first call.
func (a *HostAdapter) Remove(ctx context.Context, in RemoveInput) error {
	if err := in.Validate(); err != nil {
		return err
	}
	ns := in.NamespaceName()
	if err := a.cs.CoreV1().Namespaces().Delete(ctx, ns, metav1.DeleteOptions{}); err != nil {
		if apierrors.IsNotFound(err) {
			return nil
		}
		return fmt.Errorf("delete namespace %s: %w", ns, err)
	}
	return nil
}

// WaitReady blocks until the data-plane Deployment in the named
// Deployment's namespace finishes rolling out. Exposed so the operator
// can wait on a previously-applied deployment without re-running Apply.
func (a *HostAdapter) WaitReady(ctx context.Context, deploymentID string) error {
	if deploymentID == "" || !isSafeDeploymentID(deploymentID) {
		return fmt.Errorf("%w: deployment_id %q", ErrInvalidInput, deploymentID)
	}
	return waitForRollout(ctx, a.cs, NamespacePrefix+deploymentID, a.rolloutTimeout)
}

// Clientset exposes the underlying clientset for the integration test
// — kept package-public-but-undocumented (no doc comment for godoc)
// so production callers do not accidentally couple to it.
func (a *HostAdapter) Clientset() kubernetes.Interface { return a.cs }
