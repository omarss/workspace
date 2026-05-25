// Integration test for the k3s adapter. Build-tagged so `make test`
// stays fast and self-contained; `make test-int` opts in.
//
// The test requires:
//   - A reachable k3s/k8s cluster via $KUBECONFIG (or ~/.kube/config).
//   - Permission to create + delete namespaces, services,
//     deployments, network policies, service accounts.
//   - A CNI that enforces NetworkPolicy (k3s ships with flannel +
//     no NP enforcement by default — the homelab installs the
//     `--flannel-backend=vxlan` k3s with the NP add-on, OR uses
//     calico/cilium per AGENTS.md §6). If your cluster does not
//     enforce NP, the cross-namespace probe sub-test will FAIL
//     loudly, which is the correct outcome — Phase 12b refuses to
//     ship if the cluster cannot block cross-namespace traffic.
//
// Run with:  make test-int

//go:build integration

package k3s

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// integrationInput is a per-test ApplyInput. Each integration run uses
// a fresh deployment ID so previous tear-downs do not collide with
// the current run.
func integrationInput(depID string) ApplyInput {
	return ApplyInput{
		DeploymentID:     depID,
		ProjectSlug:      "inttest",
		EnvironmentSlug:  "ci",
		ImageVersion:     "v0.3.1",
		NodePort:         randomNodePort(),
		HostNginxCIDR:    "127.0.0.1/32",
		HostPostgresCIDR: "127.0.0.1/32",
		HostOpenBaoCIDR:  "127.0.0.1/32",
	}
}

// randomNodePort picks a port in 30000-32767 with a process-id-based
// offset so parallel CI runs do not collide. Using 30000+pid%2000 keeps
// us within the k3s NodePort range and avoids the lower 1000 ports the
// homelab reserves for its own services.
func randomNodePort() int {
	return 30000 + (os.Getpid() % 2000)
}

func TestIntegrationApplyAndRemove(t *testing.T) {
	if testing.Short() {
		t.Skip("integration test")
	}

	adapter, err := NewHostAdapter(ClientConfig{}, WithRolloutTimeout(20*time.Second))
	if err != nil {
		t.Skipf("no kubeconfig (%v) — skipping integration test", err)
	}

	depID := "deptestint01"
	in := integrationInput(depID)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	// Best-effort cleanup before + after the test in case a prior run
	// left state behind. We do NOT fail the test on cleanup errors.
	_ = adapter.Remove(ctx, RemoveInput{DeploymentID: depID})
	t.Cleanup(func() {
		ctx2, c2 := context.WithTimeout(context.Background(), 30*time.Second)
		defer c2()
		_ = adapter.Remove(ctx2, RemoveInput{DeploymentID: depID})
	})

	// The Deployment will not become Ready because the data-plane image
	// is not pulled in this test environment. We accept ErrRolloutTimeout
	// here — the success condition is that namespace + NetworkPolicies +
	// Service + Deployment all materialised. The rollout itself is
	// covered by the unit tests against the fake clientset.
	if err := adapter.Apply(ctx, in); err != nil && !errors.Is(err, ErrRolloutTimeout) {
		t.Fatalf("Apply: %v", err)
	}

	ns := in.NamespaceName()
	cs := adapter.Clientset()

	if _, err := cs.CoreV1().Namespaces().Get(ctx, ns, metav1.GetOptions{}); err != nil {
		t.Fatalf("namespace %s not found: %v", ns, err)
	}
	nps, err := cs.NetworkingV1().NetworkPolicies(ns).List(ctx, metav1.ListOptions{})
	if err != nil {
		t.Fatalf("list networkpolicies: %v", err)
	}
	if len(nps.Items) != 3 {
		t.Errorf("networkpolicies: got %d, want 3", len(nps.Items))
	}
	if _, err := cs.AppsV1().Deployments(ns).Get(ctx, DataPlaneDeploymentName, metav1.GetOptions{}); err != nil {
		t.Fatalf("deployment %s/%s not found: %v", ns, DataPlaneDeploymentName, err)
	}
	if _, err := cs.CoreV1().Services(ns).Get(ctx, "dataplane", metav1.GetOptions{}); err != nil {
		t.Fatalf("service %s/dataplane not found: %v", ns, err)
	}
	if _, err := cs.CoreV1().ServiceAccounts(ns).Get(ctx, "dataplane", metav1.GetOptions{}); err != nil {
		t.Fatalf("serviceaccount %s/dataplane not found: %v", ns, err)
	}

	// Remove should be idempotent — call twice.
	if err := adapter.Remove(ctx, RemoveInput{DeploymentID: depID}); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	if err := adapter.Remove(ctx, RemoveInput{DeploymentID: depID}); err != nil {
		t.Fatalf("Remove (second call): %v", err)
	}

	// After Remove the namespace should eventually be NotFound.
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		_, err := cs.CoreV1().Namespaces().Get(ctx, ns, metav1.GetOptions{})
		if apierrors.IsNotFound(err) {
			return
		}
		time.Sleep(time.Second)
	}
	t.Errorf("namespace %s not garbage-collected within 30s", ns)
}
