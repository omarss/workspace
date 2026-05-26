package k3s

import (
	"fmt"

	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// ClientConfig is the input to NewHostAdapter — kept narrow so the CLI
// can override the kubeconfig path without parsing flags inside the
// adapter package.
type ClientConfig struct {
	// KubeconfigPath, when non-empty, takes precedence over in-cluster
	// detection. Empty means "use $KUBECONFIG (resolved by client-go's
	// default loading rules), then ~/.kube/config, then in-cluster".
	KubeconfigPath string
}

// LoadClientset returns a kubernetes.Interface ready for typed apply.
// The resolution order matches kubectl's:
//
//  1. explicit KubeconfigPath if set
//  2. $KUBECONFIG / ~/.kube/config via client-go's default loading rules
//  3. in-cluster service-account token
//
// We delegate env-var + home-dir resolution to client-go's
// clientcmd.NewDefaultClientConfigLoadingRules / rest.InClusterConfig
// rather than reading os.Getenv directly — the cmd/* package is the
// sanctioned location for env reads (see .golangci.yml forbidigo).
func LoadClientset(cfg ClientConfig) (kubernetes.Interface, *rest.Config, error) {
	restCfg, err := loadRESTConfig(cfg)
	if err != nil {
		return nil, nil, err
	}
	cs, err := kubernetes.NewForConfig(restCfg)
	if err != nil {
		return nil, nil, fmt.Errorf("build clientset: %w", err)
	}
	return cs, restCfg, nil
}

func loadRESTConfig(cfg ClientConfig) (*rest.Config, error) {
	// Explicit override (CLI --kubeconfig flag) short-circuits everything.
	if cfg.KubeconfigPath != "" {
		return clientcmd.BuildConfigFromFlags("", cfg.KubeconfigPath)
	}
	// Default loading rules: honours $KUBECONFIG, then ~/.kube/config.
	// client-go handles the env-var read internally so we keep the
	// adapter free of bare os.Getenv calls.
	loader := clientcmd.NewDefaultClientConfigLoadingRules()
	overrides := &clientcmd.ConfigOverrides{}
	cfgLoader := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loader, overrides)
	if c, err := cfgLoader.ClientConfig(); err == nil {
		return c, nil
	}
	// In-cluster fall-through: when the controlplane eventually runs as
	// a Pod, this is the production path. On-host invocations skip it
	// (the function returns ErrNoKubeconfig when /var/run/secrets/...
	// is absent).
	if c, err := rest.InClusterConfig(); err == nil {
		return c, nil
	}
	return nil, ErrNoKubeconfig
}
