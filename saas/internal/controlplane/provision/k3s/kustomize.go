package k3s

import (
	"embed"
	"fmt"
	"io/fs"
	"path"
	"strconv"
	"strings"

	"sigs.k8s.io/kustomize/api/krusty"
	"sigs.k8s.io/kustomize/kyaml/filesys"
)

// embeddedAssets carries the CP-4-approved base manifests AND the
// Phase-12b overlay template. We embed under two sub-roots so the
// renderer can copy the tree verbatim into an in-memory filesystem,
// text-substitute the overlay's ${placeholders}, and then run kustomize
// over the resulting layout.
//
// Layout inside the embed:
//
//	embed/base/*.yaml
//	embed/overlay/kustomization.yaml
//
//go:embed embed/base/*.yaml embed/overlay/kustomization.yaml
var embeddedAssets embed.FS

// Kustomizer renders the overlay for one ApplyInput into the multi-doc
// YAML bytes the adapter then decodes + applies. Stateless beyond the
// embedded asset reference — safe to share across goroutines.
type Kustomizer struct{}

// NewKustomizer returns a renderer. Exposed so the CLI can render
// without constructing the full client-go-backed adapter (useful for
// `saasctl debug k3s render <dep_id>` if we ever add it; not wired in
// Phase 12b).
func NewKustomizer() *Kustomizer {
	return &Kustomizer{}
}

// Render returns the multi-doc YAML the adapter applies. The function
// builds an in-memory filesystem that mirrors:
//
//	/base/...                  (verbatim from embed/base)
//	/overlay/kustomization.yaml (template, post-substitution)
//
// Then calls krusty.Run("/overlay"). The placeholders the template
// uses are documented inline in the embed/overlay file.
//
// The substitution is intentionally a strings.Replacer pass on the
// kustomization.yaml only — base manifests stay byte-identical to
// `deploy/k3s/base/*.yaml` so a drift between the embed copy and the
// git-tracked CP-4 manifests is visible in a normal diff.
func (k *Kustomizer) Render(in ApplyInput) ([]byte, error) {
	if err := in.Validate(); err != nil {
		return nil, err
	}

	fSys := filesys.MakeFsInMemory()

	// Copy the embedded base manifests verbatim into /base/.
	if err := copyEmbedTree(fSys, "embed/base", "/base"); err != nil {
		return nil, fmt.Errorf("%w: copy base: %w", ErrRender, err)
	}

	// Read the overlay template, substitute placeholders, write into
	// /overlay/kustomization.yaml.
	tmpl, err := embeddedAssets.ReadFile("embed/overlay/kustomization.yaml")
	if err != nil {
		return nil, fmt.Errorf("%w: read overlay template: %w", ErrRender, err)
	}
	rendered := substitutePlaceholders(string(tmpl), in)
	// Check non-comment lines for leftover placeholders. The template's
	// header comment legitimately documents the ${...} markers, so a
	// naive Contains would always trip.
	if hasUnsubstituted(rendered) {
		return nil, fmt.Errorf("%w: unsubstituted placeholder in overlay (template drift)", ErrRender)
	}
	if err := fSys.MkdirAll("/overlay"); err != nil {
		return nil, fmt.Errorf("%w: mkdir overlay: %w", ErrRender, err)
	}
	if err := fSys.WriteFile("/overlay/kustomization.yaml", []byte(rendered)); err != nil {
		return nil, fmt.Errorf("%w: write overlay: %w", ErrRender, err)
	}

	opts := krusty.MakeDefaultOptions()
	builder := krusty.MakeKustomizer(opts)
	rm, err := builder.Run(fSys, "/overlay")
	if err != nil {
		return nil, fmt.Errorf("%w: krusty.Run: %w", ErrRender, err)
	}
	yamlBytes, err := rm.AsYaml()
	if err != nil {
		return nil, fmt.Errorf("%w: ResMap.AsYaml: %w", ErrRender, err)
	}
	// Defense in depth: kustomize strips comments from its output, so
	// a leftover ${ in the rendered manifest set is a true bug.
	if strings.Contains(string(yamlBytes), "${") {
		return nil, fmt.Errorf("%w: rendered manifest contains literal ${...}", ErrRender)
	}
	return yamlBytes, nil
}

// hasUnsubstituted scans non-comment lines of a YAML stream for a
// ${...} marker. We tolerate the markers in comments because the
// template's documentation block lists them explicitly.
func hasUnsubstituted(yaml string) bool {
	for _, line := range strings.Split(yaml, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "#") {
			continue
		}
		if strings.Contains(line, "${") {
			return true
		}
	}
	return false
}

// copyEmbedTree mirrors a sub-tree of embeddedAssets into the given
// in-memory filesystem at the given destination root. Used for the
// base manifests (we never need to touch them so a byte copy is
// enough).
func copyEmbedTree(fSys filesys.FileSystem, srcRoot, dstRoot string) error {
	return fs.WalkDir(embeddedAssets, srcRoot, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := relPath(srcRoot, p)
		if err != nil {
			return err
		}
		dst := path.Join(dstRoot, rel)
		if d.IsDir() {
			return fSys.MkdirAll(dst)
		}
		b, err := embeddedAssets.ReadFile(p)
		if err != nil {
			return err
		}
		return fSys.WriteFile(dst, b)
	})
}

// relPath returns the path of `p` relative to `root` using forward
// slashes (filepath.Rel returns OS-native separators which breaks on
// Windows — kustomize's filesys expects /). Both paths are embed-style
// slash-delimited.
func relPath(root, p string) (string, error) {
	if p == root {
		return "", nil
	}
	prefix := root + "/"
	if !strings.HasPrefix(p, prefix) {
		return "", fmt.Errorf("path %q outside root %q", p, root)
	}
	return strings.TrimPrefix(p, prefix), nil
}

// substitutePlaceholders does the Phase-12b convention text-replace on
// the overlay template. Using strings.NewReplacer (not text/template)
// because the placeholders need to survive YAML parsing — text/template
// would let a bad input inject arbitrary YAML.
func substitutePlaceholders(tmpl string, in ApplyInput) string {
	project := in.ProjectSlug
	if project == "" {
		project = in.DeploymentID
	}
	env := in.EnvironmentSlug
	if env == "" {
		env = in.DeploymentID
	}
	r := strings.NewReplacer(
		"${deployment_id}", in.DeploymentID,
		"${project_slug}", project,
		"${environment_slug}", env,
		"${image_version}", in.ImageVersion,
		"${nodeport}", strconv.Itoa(in.NodePort),
		"${host_nginx_cidr}", in.HostNginxCIDR,
		"${host_postgres_cidr}", in.HostPostgresCIDR,
		"${host_openbao_cidr}", in.HostOpenBaoCIDR,
	)
	return r.Replace(tmpl)
}
