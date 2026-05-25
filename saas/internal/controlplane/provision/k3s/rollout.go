package k3s

import (
	"context"
	"fmt"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/client-go/kubernetes"
)

// rolloutPollInterval is how often WaitReady asks the API server for
// the data-plane Deployment status. 2s matches kubectl's `rollout
// status` default and keeps the API server load negligible.
const rolloutPollInterval = 2 * time.Second

// defaultRolloutTimeout is the wall-clock cap on WaitReady. 5 min
// matches the plan §12b decision row "Rollout wait timeout". For
// CHECKPOINT 6 the operator can override via ApplyInput once we wire
// metadata.rollout_timeout_seconds in Phase 12e.
const defaultRolloutTimeout = 5 * time.Minute

// waitForRollout polls the data-plane Deployment in a namespace until:
//
//   - the controller has observed our latest generation (so we don't
//     read stale status), AND
//   - AvailableReplicas >= Spec.Replicas (so all replicas are healthy
//     under the deployment's RollingUpdate strategy), AND
//   - no condition reports ProgressDeadlineExceeded (which would mean
//     the rollout will never converge — bail with ErrRolloutFailed
//     so the caller does not wait the full timeout).
//
// The Deployment name is hard-coded to DataPlaneDeploymentName because
// every per-Deployment namespace ships exactly one Deployment. If a
// future phase adds a sidecar Deployment per namespace, lift the name
// to a parameter.
//
// If the context deadline expires while the rollout is still in
// progress, wait.PollUntilContextTimeout returns its own error which
// we wrap with ErrRolloutTimeout for downstream Is checks.
func waitForRollout(ctx context.Context, cs kubernetes.Interface, namespace string, timeout time.Duration) error {
	if timeout <= 0 {
		timeout = defaultRolloutTimeout
	}
	name := DataPlaneDeploymentName
	err := wait.PollUntilContextTimeout(ctx, rolloutPollInterval, timeout, true,
		func(ctx context.Context) (bool, error) {
			d, err := cs.AppsV1().Deployments(namespace).Get(ctx, name, metav1.GetOptions{})
			if err != nil {
				// A 404 right after Apply is normal — the API server
				// might not have propagated the apply yet. Retry.
				if apierrors.IsNotFound(err) {
					return false, nil
				}
				return false, err
			}
			if d.Generation != d.Status.ObservedGeneration {
				return false, nil
			}
			if d.Spec.Replicas == nil {
				// Defaults-to-1 per appsv1 conversion; if the API
				// server has not stamped it yet, retry rather than
				// risk a nil deref.
				return false, nil
			}
			for _, c := range d.Status.Conditions {
				if c.Type == appsv1.DeploymentProgressing && c.Reason == "ProgressDeadlineExceeded" {
					return false, fmt.Errorf("%w: %s/%s: %s", ErrRolloutFailed, namespace, name, c.Message)
				}
			}
			if d.Status.AvailableReplicas < *d.Spec.Replicas {
				return false, nil
			}
			return true, nil
		})
	if err == nil {
		return nil
	}
	if wait.Interrupted(err) {
		return fmt.Errorf("%w: %s/%s", ErrRolloutTimeout, namespace, name)
	}
	return err
}
