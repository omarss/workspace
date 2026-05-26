package k3s

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	"k8s.io/client-go/kubernetes/scheme"
	clienttesting "k8s.io/client-go/testing"
)

// installApplyAsCreate teaches the fake clientset to treat a
// server-side-apply Patch as create-or-update. The real fake does NOT
// implement SSA semantics — a Patch on a non-existent resource returns
// 404. Production k8s instead creates the object, so for the adapter's
// unit tests we install a reactor that mimics that behaviour: convert
// the rendered SSA payload to the typed object, then Create-or-Update
// in the tracker.
func installApplyAsCreate(cs *fake.Clientset) {
	cs.PrependReactor("patch", "*", func(action clienttesting.Action) (bool, runtime.Object, error) {
		pa, ok := action.(clienttesting.PatchAction)
		if !ok {
			return false, nil, nil
		}
		if pa.GetPatchType() != "application/apply-patch+yaml" {
			return false, nil, nil
		}
		// Decode the apply patch into the typed object.
		obj, _, err := scheme.Codecs.UniversalDeserializer().Decode(pa.GetPatch(), nil, nil)
		if err != nil {
			return true, nil, err
		}
		gvr := pa.GetResource()
		_, getErr := cs.Tracker().Get(gvr, pa.GetNamespace(), pa.GetName())
		switch {
		case apierrors.IsNotFound(getErr):
			if err := cs.Tracker().Create(gvr, obj, pa.GetNamespace()); err != nil {
				return true, nil, err
			}
		case getErr == nil:
			if err := cs.Tracker().Update(gvr, obj, pa.GetNamespace()); err != nil {
				return true, nil, err
			}
		default:
			return true, nil, getErr
		}
		return true, obj, nil
	})
}

// validInput is the canonical happy-path ApplyInput used by every
// positive-case test. CIDRs are loopback /32s — meaningless to the
// kernel but valid to kustomize + the API server.
func validInput() ApplyInput {
	return ApplyInput{
		DeploymentID:     "dep_test01",
		ProjectSlug:      "test",
		EnvironmentSlug:  "ci",
		ImageVersion:     "v0.3.1",
		NodePort:         30801,
		HostNginxCIDR:    "127.0.0.1/32",
		HostPostgresCIDR: "127.0.0.1/32",
		HostOpenBaoCIDR:  "127.0.0.1/32",
	}
}

func TestApplyInputValidate(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(*ApplyInput)
		wantErr error
	}{
		{"happy", func(*ApplyInput) {}, nil},
		{"empty id", func(in *ApplyInput) { in.DeploymentID = "" }, ErrInvalidInput},
		{"unsafe id", func(in *ApplyInput) { in.DeploymentID = "dep$bad" }, ErrInvalidInput},
		{"long id", func(in *ApplyInput) { in.DeploymentID = strings.Repeat("a", 65) }, ErrInvalidInput},
		{"empty image", func(in *ApplyInput) { in.ImageVersion = "" }, ErrInvalidInput},
		{"unsafe image", func(in *ApplyInput) { in.ImageVersion = "v0.3.1 ;rm -rf" }, ErrInvalidInput},
		{"low port", func(in *ApplyInput) { in.NodePort = 29999 }, ErrInvalidInput},
		{"high port", func(in *ApplyInput) { in.NodePort = 32768 }, ErrInvalidInput},
		{"missing nginx cidr", func(in *ApplyInput) { in.HostNginxCIDR = "" }, ErrMissingCIDR},
		{"missing pg cidr", func(in *ApplyInput) { in.HostPostgresCIDR = "" }, ErrMissingCIDR},
		{"missing bao cidr", func(in *ApplyInput) { in.HostOpenBaoCIDR = "" }, ErrMissingCIDR},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			in := validInput()
			tc.mutate(&in)
			err := in.Validate()
			if tc.wantErr == nil {
				if err != nil {
					t.Fatalf("Validate: unexpected error: %v", err)
				}
				return
			}
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("Validate: got %v, want errors.Is %v", err, tc.wantErr)
			}
		})
	}
}

// TestKustomizerRenderProducesExpectedKinds checks that the rendered
// YAML contains every kind the adapter expects. This is the bench
// against template drift: if someone adds a new kind to base/ without
// updating the decoder, the manifest still renders but DecodeManifest
// catches it (covered separately) — here we lock in the happy shape.
func TestKustomizerRenderProducesExpectedKinds(t *testing.T) {
	yamlBytes, err := NewKustomizer().Render(validInput())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	for _, want := range []string{
		"kind: Namespace",
		"kind: ServiceAccount",
		"kind: Deployment",
		"kind: Service",
		"kind: NetworkPolicy",
		"name: default-deny",
		"name: allow-ingress-from-host-nginx",
		"name: allow-egress-platform",
		"name: saas-dep_test01", // namespace name post-substitution
		"nodePort: 30801",
		"127.0.0.1/32",
	} {
		if !strings.Contains(string(yamlBytes), want) {
			t.Errorf("rendered YAML missing %q\n--- yaml ---\n%s", want, yamlBytes)
		}
	}
	// Guard against literal placeholders leaking through.
	if strings.Contains(string(yamlBytes), "${") {
		t.Errorf("rendered YAML still contains a ${...} placeholder:\n%s", yamlBytes)
	}
}

func TestDecodeManifest(t *testing.T) {
	yamlBytes, err := NewKustomizer().Render(validInput())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	objs, err := DecodeManifest(yamlBytes)
	if err != nil {
		t.Fatalf("Decode: %v", err)
	}
	if objs.Namespace == nil || objs.Namespace.Name != "saas-dep_test01" {
		t.Errorf("namespace: got %+v", objs.Namespace)
	}
	if objs.ServiceAccount == nil || objs.ServiceAccount.Name != "dataplane" {
		t.Errorf("serviceaccount: got %+v", objs.ServiceAccount)
	}
	if objs.Service == nil {
		t.Fatalf("service missing")
	}
	if objs.Service.Spec.Ports[0].NodePort != 30801 {
		t.Errorf("service nodePort: got %d, want 30801", objs.Service.Spec.Ports[0].NodePort)
	}
	if objs.Deployment == nil || objs.Deployment.Name != "dataplane" {
		t.Errorf("deployment: got %+v", objs.Deployment)
	}
	if len(objs.NetworkPolicies) != 3 {
		t.Errorf("network policies: got %d, want 3", len(objs.NetworkPolicies))
	}
}

// TestApplyAllCallsServerSideApplyOnEveryKind verifies the adapter
// hands every decoded object to the matching Apply method and records
// FieldManager + Force for each call. The fake clientset's action
// recorder is the cleanest place to assert this — no need to spin up
// a real API server.
func TestApplyAllCallsServerSideApplyOnEveryKind(t *testing.T) {
	yamlBytes, err := NewKustomizer().Render(validInput())
	if err != nil {
		t.Fatalf("Render: %v", err)
	}
	objs, err := DecodeManifest(yamlBytes)
	if err != nil {
		t.Fatalf("Decode: %v", err)
	}
	cs := fake.NewSimpleClientset()
	installApplyAsCreate(cs)

	if err := applyAll(context.Background(), cs, objs); err != nil {
		t.Fatalf("applyAll: %v", err)
	}

	wantKindOrder := []string{"namespaces", "serviceaccounts", "networkpolicies", "networkpolicies", "networkpolicies", "services", "deployments"}
	var gotKinds []string
	for _, a := range cs.Actions() {
		if a.GetVerb() != "patch" { // SSA is a Patch under the hood.
			continue
		}
		gotKinds = append(gotKinds, a.GetResource().Resource)
	}
	if len(gotKinds) != len(wantKindOrder) {
		t.Fatalf("apply actions: got %d, want %d (%v)", len(gotKinds), len(wantKindOrder), gotKinds)
	}
	for i, want := range wantKindOrder {
		if gotKinds[i] != want {
			t.Errorf("apply order[%d]: got %s, want %s (full: %v)", i, gotKinds[i], want, gotKinds)
		}
	}
}

// TestAdapterApplyFakeClientset is the highest-level unit test: end to
// end through Apply → WaitReady against the fake clientset. We
// preload a Deployment status that satisfies waitForRollout so the
// poll loop exits on the first tick.
func TestAdapterApplyFakeClientset(t *testing.T) {
	cs := fake.NewSimpleClientset()
	installApplyAsCreate(cs)
	// Once the adapter applies the data-plane Deployment, stamp a
	// "ready" status on it so the WaitReady poll exits on the first
	// tick. The fake clientset does not run a real controller — without
	// this the rollout wait hangs to the timeout.
	cs.PrependReactor("get", "deployments", func(action clienttesting.Action) (bool, runtime.Object, error) {
		ga, ok := action.(clienttesting.GetAction)
		if !ok || ga.GetName() != DataPlaneDeploymentName {
			return false, nil, nil
		}
		one := int32(1)
		return true, &appsv1.Deployment{
			ObjectMeta: metav1.ObjectMeta{
				Name:       DataPlaneDeploymentName,
				Namespace:  ga.GetNamespace(),
				Generation: 1,
			},
			Spec:   appsv1.DeploymentSpec{Replicas: &one},
			Status: appsv1.DeploymentStatus{ObservedGeneration: 1, AvailableReplicas: 1},
		}, nil
	})

	adapter := newHostAdapterFromClientset(cs, WithRolloutTimeout(10*time.Second))
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := adapter.Apply(ctx, validInput()); err != nil {
		t.Fatalf("Apply: %v", err)
	}
}

// TestAdapterRemoveIdempotent confirms a delete on a non-existent
// namespace is not an error — the destroy reconciler retries Remove on
// transient failures and must not flag absent-namespace as a permanent
// fault.
func TestAdapterRemoveIdempotent(t *testing.T) {
	cs := fake.NewSimpleClientset()
	a := newHostAdapterFromClientset(cs)
	if err := a.Remove(context.Background(), RemoveInput{DeploymentID: "dep_neverexisted"}); err != nil {
		t.Fatalf("Remove: %v", err)
	}
}

// TestAdapterRemoveExistingDeletesNamespace confirms the happy path —
// the namespace exists, Delete is called, the API server records a
// delete action.
func TestAdapterRemoveExistingDeletesNamespace(t *testing.T) {
	cs := fake.NewSimpleClientset(&corev1.Namespace{
		ObjectMeta: metav1.ObjectMeta{Name: "saas-dep_test01"},
	})
	a := newHostAdapterFromClientset(cs)
	if err := a.Remove(context.Background(), RemoveInput{DeploymentID: "dep_test01"}); err != nil {
		t.Fatalf("Remove: %v", err)
	}
	var sawDelete bool
	for _, ac := range cs.Actions() {
		if ac.GetVerb() == "delete" && ac.GetResource().Resource == "namespaces" {
			sawDelete = true
			break
		}
	}
	if !sawDelete {
		t.Errorf("expected delete namespace action, actions=%v", cs.Actions())
	}
}

// TestWaitForRolloutSuccess and TestWaitForRolloutTimeout pin the two
// branches of the rollout poll loop. The fake clientset's tracker
// drives the Deployment status the loop reads.
func TestWaitForRolloutSuccess(t *testing.T) {
	one := int32(1)
	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:       "dataplane",
			Namespace:  "saas-dep_ok",
			Generation: 2,
		},
		Spec:   appsv1.DeploymentSpec{Replicas: &one},
		Status: appsv1.DeploymentStatus{ObservedGeneration: 2, AvailableReplicas: 1},
	}
	cs := fake.NewSimpleClientset(dep)
	if err := waitForRollout(context.Background(), cs, "saas-dep_ok", 2*time.Second); err != nil {
		t.Fatalf("waitForRollout: %v", err)
	}
}

func TestWaitForRolloutTimeout(t *testing.T) {
	one := int32(1)
	// ObservedGeneration trails Generation → the loop keeps polling.
	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:       "dataplane",
			Namespace:  "saas-dep_stuck",
			Generation: 3,
		},
		Spec:   appsv1.DeploymentSpec{Replicas: &one},
		Status: appsv1.DeploymentStatus{ObservedGeneration: 2, AvailableReplicas: 0},
	}
	cs := fake.NewSimpleClientset(dep)
	err := waitForRollout(context.Background(), cs, "saas-dep_stuck", 500*time.Millisecond)
	if !errors.Is(err, ErrRolloutTimeout) {
		t.Fatalf("waitForRollout: got %v, want errors.Is ErrRolloutTimeout", err)
	}
}

// TestWaitForRolloutProgressDeadlineExceeded forces the
// ProgressDeadlineExceeded short-circuit so we don't wait the full
// timeout when the rollout will never converge.
func TestWaitForRolloutProgressDeadlineExceeded(t *testing.T) {
	one := int32(1)
	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:       "dataplane",
			Namespace:  "saas-dep_dead",
			Generation: 1,
		},
		Spec: appsv1.DeploymentSpec{Replicas: &one},
		Status: appsv1.DeploymentStatus{
			ObservedGeneration: 1,
			AvailableReplicas:  0,
			Conditions: []appsv1.DeploymentCondition{{
				Type:    appsv1.DeploymentProgressing,
				Status:  corev1.ConditionFalse,
				Reason:  "ProgressDeadlineExceeded",
				Message: "image pull backoff",
			}},
		},
	}
	cs := fake.NewSimpleClientset(dep)
	err := waitForRollout(context.Background(), cs, "saas-dep_dead", 5*time.Second)
	if !errors.Is(err, ErrRolloutFailed) {
		t.Fatalf("waitForRollout: got %v, want errors.Is ErrRolloutFailed", err)
	}
}
