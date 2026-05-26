package k3s

import (
	"bytes"
	"errors"
	"fmt"
	"io"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	netv1 "k8s.io/api/networking/v1"
	"k8s.io/apimachinery/pkg/runtime"
	utilyaml "k8s.io/apimachinery/pkg/util/yaml"
	"k8s.io/client-go/kubernetes/scheme"
)

// decodedObjects holds the rendered manifest broken out by kind. The
// strict typing — instead of a []runtime.Object slice — lets the apply
// layer hand each object to the right typed Apply method without a
// type-switch nor a reflective conversion.
type decodedObjects struct {
	Namespace       *corev1.Namespace
	ServiceAccount  *corev1.ServiceAccount
	Service         *corev1.Service
	Deployment      *appsv1.Deployment
	NetworkPolicies []*netv1.NetworkPolicy
	UnknownKinds    []string
}

// DecodeManifest splits the multi-doc YAML produced by Kustomizer.Render
// into typed Kubernetes objects. The kinds the adapter knows how to
// apply (Namespace / ServiceAccount / Service / Deployment /
// NetworkPolicy) populate the matching fields; anything else lands in
// UnknownKinds so the caller can fail loud rather than silently drop a
// resource.
//
// We use the scheme registered by client-go's kubernetes package —
// that scheme already includes every GVK we touch. Adding a new kind
// to the base manifest set requires extending the type-switch below.
func DecodeManifest(yamlBytes []byte) (decodedObjects, error) {
	out := decodedObjects{}
	dec := utilyaml.NewYAMLOrJSONDecoder(bytes.NewReader(yamlBytes), 4096)

	codec := scheme.Codecs.UniversalDeserializer()

	for {
		var raw runtime.RawExtension
		if err := dec.Decode(&raw); err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			return decodedObjects{}, fmt.Errorf("%w: split yaml docs: %w", ErrDecode, err)
		}
		if len(bytes.TrimSpace(raw.Raw)) == 0 {
			continue
		}
		obj, gvk, err := codec.Decode(raw.Raw, nil, nil)
		if err != nil {
			return decodedObjects{}, fmt.Errorf("%w: decode doc: %w", ErrDecode, err)
		}
		switch v := obj.(type) {
		case *corev1.Namespace:
			out.Namespace = v
		case *corev1.ServiceAccount:
			out.ServiceAccount = v
		case *corev1.Service:
			out.Service = v
		case *appsv1.Deployment:
			out.Deployment = v
		case *netv1.NetworkPolicy:
			out.NetworkPolicies = append(out.NetworkPolicies, v)
		default:
			kind := "<unknown>"
			if gvk != nil {
				kind = gvk.String()
			}
			out.UnknownKinds = append(out.UnknownKinds, kind)
		}
	}

	if len(out.UnknownKinds) > 0 {
		return out, fmt.Errorf("%w: unsupported kinds in manifest: %v", ErrDecode, out.UnknownKinds)
	}
	if out.Namespace == nil {
		return out, fmt.Errorf("%w: rendered manifest has no Namespace", ErrDecode)
	}
	if out.Deployment == nil {
		return out, fmt.Errorf("%w: rendered manifest has no Deployment", ErrDecode)
	}
	if out.Service == nil {
		return out, fmt.Errorf("%w: rendered manifest has no Service", ErrDecode)
	}
	if len(out.NetworkPolicies) < 3 {
		return out, fmt.Errorf("%w: rendered manifest has %d NetworkPolicies, expected 3 (default-deny + allow-ingress + allow-egress)",
			ErrDecode, len(out.NetworkPolicies))
	}
	return out, nil
}
