package nginx

import (
	"bytes"
	_ "embed"
	"fmt"
	"text/template"
)

// vhostTemplateSource is the CP-4-approved pre-certbot vhost template
// from deploy/nginx/vhost.conf.tmpl. We embed it so the adapter binary
// is self-contained — the operator does not need to ship deploy/ to the
// host, only the controlplane binary plus the one-time setup script.
//
//go:embed embed/vhost.conf.tmpl
var vhostTemplateSource string

// renderer wraps the parsed template + caches it. text/template parsing
// is cheap but we still cache to keep Apply() allocation-light when the
// destroy reconciler retries a sequence at speed.
type renderer struct {
	tmpl *template.Template
}

func newRenderer() (*renderer, error) {
	t, err := template.New("vhost").Parse(vhostTemplateSource)
	if err != nil {
		return nil, fmt.Errorf("parse embedded vhost template: %w", err)
	}
	return &renderer{tmpl: t}, nil
}

// render runs the embedded template against the given ApplyInput. The
// output is the exact bytes that will land on disk at
// /etc/nginx/sites-available/saas-<dep_id>.conf — no post-processing.
func (r *renderer) render(in ApplyInput) ([]byte, error) {
	var buf bytes.Buffer
	if err := r.tmpl.Execute(&buf, in); err != nil {
		return nil, fmt.Errorf("execute vhost template for %s: %w", in.DeploymentID, err)
	}
	return buf.Bytes(), nil
}
