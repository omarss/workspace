package k3s

import "errors"

// Sentinel errors the adapter returns. Callers compare with errors.Is —
// the wrapping in Validate / Apply / WaitReady always uses %w so the
// chain stays intact.
var (
	// ErrInvalidInput signals a caller-side bug: a malformed deployment
	// ID, an out-of-range node port, etc. Treat as a permanent failure
	// — never retried by the destroy reconciler.
	ErrInvalidInput = errors.New("k3s: invalid input")

	// ErrMissingCIDR signals one of the three host CIDR inputs is empty.
	// Separated from ErrInvalidInput because the operator-facing
	// remediation differs: missing CIDRs mean the host network config
	// is incomplete, not that the deployment row is malformed.
	ErrMissingCIDR = errors.New("k3s: host CIDR is required")

	// ErrRender wraps any failure inside the kustomize render pipeline
	// (template parse, in-memory FS write, krusty.Run, AsYaml).
	ErrRender = errors.New("k3s: render kustomize overlay")

	// ErrDecode wraps any failure in the multi-doc YAML decoder. Almost
	// always means a base manifest drift from what the typed decoder
	// expects (e.g. someone hand-edited base/*.yaml to use a kind the
	// adapter does not know).
	ErrDecode = errors.New("k3s: decode rendered manifest")

	// ErrApply wraps any server-side-apply failure. The wrapped error
	// from client-go carries the kind + name; we keep ErrApply as the
	// sentinel so callers can distinguish "transport or API server
	// returned an error" from validation / render failures.
	ErrApply = errors.New("k3s: server-side apply failed")

	// ErrRolloutTimeout signals WaitReady's context deadline expired
	// before the data-plane Deployment reached AvailableReplicas >=
	// Spec.Replicas with matching observed generation.
	ErrRolloutTimeout = errors.New("k3s: rollout did not complete before timeout")

	// ErrRolloutFailed signals the data-plane Deployment hit
	// ProgressDeadlineExceeded — the rollout will never converge
	// without operator intervention (e.g. image pull failure).
	ErrRolloutFailed = errors.New("k3s: rollout failed (ProgressDeadlineExceeded)")

	// ErrNoKubeconfig signals the adapter could not find an
	// in-cluster service-account token AND no kubeconfig file at the
	// resolved path. The CLI maps this to a clear remediation message.
	ErrNoKubeconfig = errors.New("k3s: no in-cluster credentials and no kubeconfig found")
)
