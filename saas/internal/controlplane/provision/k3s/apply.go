package k3s

import (
	"context"
	"encoding/json"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	netv1 "k8s.io/api/networking/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	appsv1ac "k8s.io/client-go/applyconfigurations/apps/v1"
	corev1ac "k8s.io/client-go/applyconfigurations/core/v1"
	netv1ac "k8s.io/client-go/applyconfigurations/networking/v1"
	"k8s.io/client-go/kubernetes"
)

// applyOptions is the single ApplyOptions value every Apply call uses.
// The field manager identifies us as the sole owner of the fields we
// set (server-side apply contract), and Force=true ensures we win any
// conflict over a manager that previously owned a field we now set —
// the control plane is authoritative for the resources it materialises
// (AGENTS.md §6.5).
var applyOptions = metav1.ApplyOptions{
	FieldManager: FieldManager,
	Force:        true,
}

// applyAll runs server-side apply for every object in decodedObjects in
// the order Namespace → ServiceAccount → NetworkPolicies → Service →
// Deployment. The order matters:
//
//   - Namespace MUST exist before any namespaced resource can land in
//     it.
//   - NetworkPolicies MUST land before the Deployment so the
//     default-deny is enforced as soon as the first pod schedules
//     (otherwise there is a small window during which a pod has no
//     policy and any peer in the cluster could reach it).
//   - Service before Deployment is convention — k8s does not require
//     it, but it makes the order match the resources operators see
//     when running `kubectl get all`.
func applyAll(ctx context.Context, cs kubernetes.Interface, objs decodedObjects) error {
	if objs.Namespace != nil {
		if err := applyNamespace(ctx, cs, objs.Namespace); err != nil {
			return err
		}
	}
	if objs.ServiceAccount != nil {
		if err := applyServiceAccount(ctx, cs, objs.ServiceAccount); err != nil {
			return err
		}
	}
	for _, np := range objs.NetworkPolicies {
		if err := applyNetworkPolicy(ctx, cs, np); err != nil {
			return err
		}
	}
	if objs.Service != nil {
		if err := applyService(ctx, cs, objs.Service); err != nil {
			return err
		}
	}
	if objs.Deployment != nil {
		if err := applyDeployment(ctx, cs, objs.Deployment); err != nil {
			return err
		}
	}
	return nil
}

func applyNamespace(ctx context.Context, cs kubernetes.Interface, ns *corev1.Namespace) error {
	ac, err := toApplyConfig(ns, &corev1ac.NamespaceApplyConfiguration{})
	if err != nil {
		return fmt.Errorf("%w: namespace %s: %w", ErrApply, ns.Name, err)
	}
	if _, err := cs.CoreV1().Namespaces().Apply(ctx, ac, applyOptions); err != nil {
		return fmt.Errorf("%w: namespace %s: %w", ErrApply, ns.Name, err)
	}
	return nil
}

func applyServiceAccount(ctx context.Context, cs kubernetes.Interface, sa *corev1.ServiceAccount) error {
	ac, err := toApplyConfig(sa, &corev1ac.ServiceAccountApplyConfiguration{})
	if err != nil {
		return fmt.Errorf("%w: serviceaccount %s/%s: %w", ErrApply, sa.Namespace, sa.Name, err)
	}
	if _, err := cs.CoreV1().ServiceAccounts(sa.Namespace).Apply(ctx, ac, applyOptions); err != nil {
		return fmt.Errorf("%w: serviceaccount %s/%s: %w", ErrApply, sa.Namespace, sa.Name, err)
	}
	return nil
}

func applyNetworkPolicy(ctx context.Context, cs kubernetes.Interface, np *netv1.NetworkPolicy) error {
	ac, err := toApplyConfig(np, &netv1ac.NetworkPolicyApplyConfiguration{})
	if err != nil {
		return fmt.Errorf("%w: networkpolicy %s/%s: %w", ErrApply, np.Namespace, np.Name, err)
	}
	if _, err := cs.NetworkingV1().NetworkPolicies(np.Namespace).Apply(ctx, ac, applyOptions); err != nil {
		return fmt.Errorf("%w: networkpolicy %s/%s: %w", ErrApply, np.Namespace, np.Name, err)
	}
	return nil
}

func applyService(ctx context.Context, cs kubernetes.Interface, svc *corev1.Service) error {
	ac, err := toApplyConfig(svc, &corev1ac.ServiceApplyConfiguration{})
	if err != nil {
		return fmt.Errorf("%w: service %s/%s: %w", ErrApply, svc.Namespace, svc.Name, err)
	}
	if _, err := cs.CoreV1().Services(svc.Namespace).Apply(ctx, ac, applyOptions); err != nil {
		return fmt.Errorf("%w: service %s/%s: %w", ErrApply, svc.Namespace, svc.Name, err)
	}
	return nil
}

func applyDeployment(ctx context.Context, cs kubernetes.Interface, dep *appsv1.Deployment) error {
	ac, err := toApplyConfig(dep, &appsv1ac.DeploymentApplyConfiguration{})
	if err != nil {
		return fmt.Errorf("%w: deployment %s/%s: %w", ErrApply, dep.Namespace, dep.Name, err)
	}
	if _, err := cs.AppsV1().Deployments(dep.Namespace).Apply(ctx, ac, applyOptions); err != nil {
		return fmt.Errorf("%w: deployment %s/%s: %w", ErrApply, dep.Namespace, dep.Name, err)
	}
	return nil
}

// toApplyConfig converts a typed Kubernetes object into its
// ApplyConfiguration form by round-tripping through JSON. Each
// `applyconfigurations.*` struct is a tag-compatible mirror of the
// corresponding typed struct — fields are pointers so omitted values
// are unset (the SSA contract). The JSON round-trip is the same
// mechanism `kubectl apply --server-side` uses internally, and it is
// what AGENTS.md §6.5 prescribes when client-go's hand-built
// constructors (WithName, WithSpec, etc.) would not preserve every
// field from a kustomize-rendered source.
//
// The destination MUST be a pointer to the ApplyConfiguration struct
// for the matching kind; the caller passes it in so each apply* helper
// can keep its return type strongly typed.
func toApplyConfig[T any](src any, dst *T) (*T, error) {
	b, err := json.Marshal(src)
	if err != nil {
		return nil, fmt.Errorf("marshal source: %w", err)
	}
	if err := json.Unmarshal(b, dst); err != nil {
		return nil, fmt.Errorf("unmarshal into ApplyConfiguration: %w", err)
	}
	return dst, nil
}
