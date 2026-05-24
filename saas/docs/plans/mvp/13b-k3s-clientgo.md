# Phase 12b — k3s Provisioner (client-go Typed Apply + Kustomize + NetworkPolicy Default-Deny)

> **Goal**: Implement the `K3sAdapter` that the composite Provisioner calls. Render per-Deployment k3s manifests from a kustomize overlay (using `sigs.k8s.io/kustomize/api`), apply them via the client-go typed apply pattern with `FieldManager="saas-controlplane"` + `Force=true`. Each Deployment gets its own namespace `saas-<project>-<env>`, a Deployment + Service + ServiceAccount, and three NetworkPolicies (default-deny, allow-ingress-from-host, allow-egress-to-platform). Wait for rollout. CHECKPOINT 6 ends in a real namespace + pods + NetworkPolicy confirmed via `kubectl`.
>
> **Why now**: Phase 12a delivered the host nginx vhost; the vhost proxies to `127.0.0.1:<nodeport>` — that nodeport must be served by something. Phase 12b creates the k3s workload. Phase 12c-d add the per-Deployment DB and OpenBao key; Phase 12e wires the full sequence. NetworkPolicy default-deny is layer 4 of tenant isolation; misdesigning it breaks the platform's central claim.
>
> **What this phase does NOT do**: No Postgres provisioning (Phase 12c). No OpenBao key (Phase 12d). No per-Deployment Keycloak realm import (deferred). No HPA / VPA / PDB (out of MVP). No cert-manager / Linkerd mTLS (deferred). No image pull secret rotation (out of MVP).
>
> **Maps to AGENTS.md**: §4.3 (k3s + kustomize + client-go), §6.1 (per-Deployment namespace + service), §6.2 step 7 + step 8, §18.1 layer 4 (physical isolation: namespace + NetworkPolicy). `01-foundations.md` §9 (every API signature: client-go typed apply, kustomize Go API, NetworkPolicy stanzas, rollout wait).
>
> **Estimated subagent sessions**: 2-3 (one for manifest base + overlay template; one for adapter + apply; one for tests + NetworkPolicy cross-namespace deny verification).

---

## Pre-flight

1. AGENTS.md §4.3, §6.1, §6.2 (step 7-8), §18.1.
2. `01-foundations.md` §9 (verbatim NetworkPolicy stanzas + typed-apply pattern + rollout wait).
3. CHECKPOINT 4 approved (manifest templates reviewed at the end of Phase 11).
4. CHECKPOINT 5 approved (nginx vhost works).
5. Confirm k3s is reachable from the saas user. `kubectl get ns` should work; if not, the user must add saas to the `k3s` group + set `KUBECONFIG=/etc/rancher/k3s/k3s.yaml`.
6. Confirm the platform's k3s namespace `saas-controlplane` is created upfront and has a ServiceAccount with cluster-admin-ish rights ONLY over namespaces matching `saas-*`. This is the platform's own identity.

---

## Decisions to surface before coding

| Decision | Default | Alternatives |
|---|---|---|
| Manifest source | Kustomize overlay rendered via `sigs.k8s.io/kustomize/api` Go API | Helm chart (refused — chart complexity; templating sprawl) |
| Apply method | Server-side typed apply via `Apply<Resource>(ctx, ac, metav1.ApplyOptions{FieldManager: "saas-controlplane", Force: true})` | `kubectl apply` (refused — fragile; no field-manager); raw create+patch (refused — race-prone) |
| ServiceAccount per Deployment | Yes — `data-plane` SA in each ns. Used to bind to OpenBao via Kubernetes auth. | Shared SA (refused — OpenBao role binding leaks across deps) |
| NetworkPolicy default-deny target | All pods in the namespace (podSelector: {}) | Per-pod (refused — easier to forget) |
| Ingress allow source | Host external CIDR (where the host nginx proxies from); for k3s on a single host this is the cluster-internal flannel CIDR | Any ingress (refused — defeats default-deny) |
| Egress allow targets | Postgres (host:5432), OpenBao (host:8200), DNS (53/udp+tcp), Keycloak (host:8081), Novu (host:3000) | None (refused — pods need to reach platform services) |
| Image source | A private registry mirror; for MVP local dev: `localhost:5000/saas/dataplane:<version>` — also supports public Docker Hub for known tags | Public-only (refused — needs operator-managed registry for prod) |
| Service exposure | NodePort on `127.0.0.1:<3xxxx>` — the host nginx upstream is via 127.0.0.1 | LoadBalancer (refused — no MetalLB in homelab); ClusterIP via port-forward (refused — fragile) |
| Replica count | 1 in MVP. Doc'd in CONVENTIONS as a deployment.metadata.replicas override. | 2+ (refused — single-host k3s; no HA story for MVP) |
| Rollout wait timeout | 5 min | Configurable per deployment via metadata.rollout_timeout_seconds |

If the user disagrees on any default, stop.

---

## Tasks

### 12b.1 Base manifests — `deploy/k3s/base/`

`deploy/k3s/base/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - namespace.yaml
  - serviceaccount.yaml
  - deployment.yaml
  - service.yaml
  - networkpolicy-default-deny.yaml
  - networkpolicy-allow-ingress.yaml
  - networkpolicy-allow-egress-platform.yaml
```

`deploy/k3s/base/namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: PLACEHOLDER-NS
  labels:
    saas.omarss.net/deployment-id: PLACEHOLDER-DEP
    saas.omarss.net/project: PLACEHOLDER-PROJECT
    saas.omarss.net/environment: PLACEHOLDER-ENV
```

`deploy/k3s/base/serviceaccount.yaml`:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  namespace: PLACEHOLDER-NS
  name: data-plane
```

`deploy/k3s/base/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  namespace: PLACEHOLDER-NS
  name: data-plane
  labels: { app: data-plane }
spec:
  replicas: 1
  selector: { matchLabels: { app: data-plane } }
  template:
    metadata:
      labels: { app: data-plane }
    spec:
      serviceAccountName: data-plane
      containers:
        - name: data-plane
          image: PLACEHOLDER-IMAGE
          imagePullPolicy: IfNotPresent
          env:
            - name: DEPLOYMENT_ID
              value: PLACEHOLDER-DEP
            - name: SAAS_ENV
              value: PLACEHOLDER-ENV
            - name: DATAPLANE_DATABASE_URL
              valueFrom: { secretKeyRef: { name: dataplane-db, key: dsn } }
            - name: BAO_ADDR
              value: "https://PLACEHOLDER-HOST:8200"
            - name: OIDC_ISSUER
              value: "https://PLACEHOLDER-HOST:8081/realms/saas-data-PLACEHOLDER-DEP"
            - name: OIDC_JWKS_URL
              value: "https://PLACEHOLDER-HOST:8081/realms/saas-data-PLACEHOLDER-DEP/protocol/openid-connect/certs"
            - name: OIDC_AUDIENCE
              value: "saas-data-PLACEHOLDER-DEP"
          ports:
            - { name: http, containerPort: 8080 }
          readinessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 3
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /healthz, port: 8080 }
            initialDelaySeconds: 10
            periodSeconds: 10
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits:   { cpu: 1000m, memory: 256Mi }
```

`deploy/k3s/base/service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  namespace: PLACEHOLDER-NS
  name: data-plane
spec:
  type: NodePort
  selector: { app: data-plane }
  ports:
    - { name: http, port: 8080, targetPort: 8080, nodePort: PLACEHOLDER-NODEPORT }
```

`deploy/k3s/base/networkpolicy-default-deny.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  namespace: PLACEHOLDER-NS
  name: default-deny
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
```

`deploy/k3s/base/networkpolicy-allow-ingress.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  namespace: PLACEHOLDER-NS
  name: allow-from-host-nginx
spec:
  podSelector: { matchLabels: { app: data-plane } }
  policyTypes: [Ingress]
  ingress:
    - from:
        - ipBlock: { cidr: PLACEHOLDER-HOST-CIDR }
      ports:
        - { protocol: TCP, port: 8080 }
```

`deploy/k3s/base/networkpolicy-allow-egress-platform.yaml`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  namespace: PLACEHOLDER-NS
  name: allow-egress-platform
spec:
  podSelector: { matchLabels: { app: data-plane } }
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock: { cidr: PLACEHOLDER-HOST-CIDR }
      ports:
        - { protocol: TCP, port: 5432 }
        - { protocol: TCP, port: 8200 }
        - { protocol: TCP, port: 8081 }
        - { protocol: TCP, port: 3000 }
    - to:
        - namespaceSelector: { matchLabels: { name: kube-system } }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
```

### 12b.2 Overlay template — `deploy/k3s/overlays/template/`

`kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
namespace: PLACEHOLDER-NS
replacements:
  - source: { kind: Namespace, name: PLACEHOLDER-NS, fieldPath: metadata.name }
    targets:
      - select: { kind: ServiceAccount }
        fieldPaths: [metadata.namespace]
      - select: { kind: Deployment }
        fieldPaths: [metadata.namespace]
      - select: { kind: Service }
        fieldPaths: [metadata.namespace]
      - select: { kind: NetworkPolicy }
        fieldPaths: [metadata.namespace]
images:
  - name: PLACEHOLDER-IMAGE
    newName: localhost:5000/saas/dataplane
    newTag: PLACEHOLDER-VERSION
```

Per-Deployment overlay rendered at provision time:

```yaml
# rendered to deploy/k3s/overlays/<dep_id>/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
namespace: saas-acme-prod
namePrefix: ""
replacements:
  - ... (substitute every PLACEHOLDER)
images:
  - name: PLACEHOLDER-IMAGE
    newName: localhost:5000/saas/dataplane
    newTag: v0.3.1
```

The platform writes this file to disk per-Deployment, then uses the Go kustomize API to render it to YAML bytes.

### 12b.3 Adapter — `internal/controlplane/provision/k3s/`

```text
internal/controlplane/provision/k3s/
  adapter.go          # K3sAdapter
  render.go           # kustomize Go API → YAML bytes
  apply.go            # client-go typed apply via apply configurations
  rollout.go          # wait.PollUntilContextTimeout
  network_test.go     # cross-namespace deny test (real k3s)
  adapter_test.go
```

`adapter.go`:

```go
package k3s

import (
    "context"

    appsv1 "k8s.io/api/apps/v1"
    corev1 "k8s.io/api/core/v1"
    netv1  "k8s.io/api/networking/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/kubernetes"
)

const FieldManager = "saas-controlplane"

type Adapter struct {
    cs      kubernetes.Interface
    overlays string  // directory where per-Deployment overlays land
}

func New(kubeconfigPath, overlaysDir string) (*Adapter, error) { ... }

func (a *Adapter) Provision(ctx context.Context, dep *Deployment) error {
    if err := a.renderOverlay(dep); err != nil { return err }
    docs, err := a.renderToYAML(ctx, dep.ID)
    if err != nil { return err }
    for _, d := range docs {
        if err := a.applyOne(ctx, d); err != nil { return err }
    }
    return a.WaitForRollout(ctx, dep.Namespace, "data-plane")
}

// Destroy deletes the namespace (cascades to all resources within).
func (a *Adapter) Destroy(ctx context.Context, dep *Deployment) error {
    return a.cs.CoreV1().Namespaces().Delete(ctx, dep.Namespace, metav1.DeleteOptions{})
}

func (a *Adapter) Restart(ctx context.Context, dep *Deployment) error {
    // patch annotation to trigger rollout.
    patch := []byte(fmt.Sprintf(`{"spec":{"template":{"metadata":{"annotations":{"saas.omarss.net/restartedAt":"%s"}}}}}`, time.Now().Format(time.RFC3339Nano)))
    _, err := a.cs.AppsV1().Deployments(dep.Namespace).Patch(ctx, "data-plane", types.StrategicMergePatchType, patch, metav1.PatchOptions{FieldManager: FieldManager})
    if err != nil { return err }
    return a.WaitForRollout(ctx, dep.Namespace, "data-plane")
}
```

`apply.go`:

```go
package k3s

import (
    "context"
    "k8s.io/apimachinery/pkg/runtime"
    "k8s.io/apimachinery/pkg/runtime/serializer/yaml"
    appsv1ac "k8s.io/client-go/applyconfigurations/apps/v1"
    corev1ac "k8s.io/client-go/applyconfigurations/core/v1"
    netv1ac  "k8s.io/client-go/applyconfigurations/networking/v1"
    metav1   "k8s.io/apimachinery/pkg/apis/meta/v1"
)

func (a *Adapter) applyOne(ctx context.Context, doc []byte) error {
    obj, gvk, err := yamlSerializer.Decode(doc, nil, nil)
    if err != nil { return err }
    opts := metav1.ApplyOptions{FieldManager: FieldManager, Force: true}
    switch v := obj.(type) {
    case *corev1.Namespace:
        ac := corev1ac.Namespace(v.Name).WithLabels(v.Labels)
        _, err = a.cs.CoreV1().Namespaces().Apply(ctx, ac, opts)
    case *corev1.ServiceAccount:
        ac := corev1ac.ServiceAccount(v.Name, v.Namespace)
        _, err = a.cs.CoreV1().ServiceAccounts(v.Namespace).Apply(ctx, ac, opts)
    case *appsv1.Deployment:
        ac := toApplyDeployment(v)  // helper that maps a typed Deployment to ApplyConfiguration
        _, err = a.cs.AppsV1().Deployments(v.Namespace).Apply(ctx, ac, opts)
    case *corev1.Service:
        ac := toApplyService(v)
        _, err = a.cs.CoreV1().Services(v.Namespace).Apply(ctx, ac, opts)
    case *netv1.NetworkPolicy:
        ac := toApplyNetworkPolicy(v)
        _, err = a.cs.NetworkingV1().NetworkPolicies(v.Namespace).Apply(ctx, ac, opts)
    default:
        return fmt.Errorf("unknown gvk %s", gvk)
    }
    return err
}
```

`render.go`:

```go
package k3s

import (
    "sigs.k8s.io/kustomize/api/krusty"
    "sigs.k8s.io/kustomize/kyaml/filesys"
)

func (a *Adapter) renderToYAML(ctx context.Context, depID string) ([][]byte, error) {
    opts := krusty.MakeDefaultOptions()
    k := krusty.MakeKustomizer(opts)
    fSys := filesys.MakeFsOnDisk()
    rm, err := k.Run(fSys, filepath.Join(a.overlays, depID))
    if err != nil { return nil, err }
    out := make([][]byte, 0, rm.Size())
    for _, r := range rm.Resources() {
        y, _ := r.AsYAML()
        out = append(out, y)
    }
    return out, nil
}
```

`rollout.go`:

```go
package k3s

import (
    "context"
    "fmt"
    "time"

    appsv1 "k8s.io/api/apps/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/apimachinery/pkg/util/wait"
)

func (a *Adapter) WaitForRollout(ctx context.Context, ns, name string) error {
    return wait.PollUntilContextTimeout(ctx, 2*time.Second, 5*time.Minute, true,
        func(ctx context.Context) (bool, error) {
            d, err := a.cs.AppsV1().Deployments(ns).Get(ctx, name, metav1.GetOptions{})
            if err != nil { return false, err }
            if d.Generation != d.Status.ObservedGeneration { return false, nil }
            if d.Status.AvailableReplicas < *d.Spec.Replicas { return false, nil }
            for _, c := range d.Status.Conditions {
                if c.Type == appsv1.DeploymentProgressing && c.Reason == "ProgressDeadlineExceeded" {
                    return false, fmt.Errorf("rollout failed: %s/%s", ns, name)
                }
            }
            return true, nil
        })
}
```

### 12b.4 NetworkPolicy cross-namespace verification

`network_test.go` (integration; tagged):

```go
//go:build integration

func TestK3s_NetworkPolicy_CrossNamespaceDeny(t *testing.T) {
    // Provision two test deployments.
    depA := provisionTest("netpoltest-a", "dev")
    depB := provisionTest("netpoltest-b", "dev")

    // From a pod in depA's namespace, attempt to reach depB's service.
    res := runPodOnceInNamespace(depA.Namespace, "curl", "-sf",
        fmt.Sprintf("http://data-plane.%s.svc.cluster.local:8080/healthz", depB.Namespace))
    require.Error(t, res.Err, "cross-namespace request should be blocked by default-deny")
    // The request should time out, not return 403/404 — that proves NP, not app-layer auth.
    require.Contains(t, res.Stderr, "timed out")
}
```

This test is the proof of layer-4 tenant isolation. If it ever regresses, the security review fails.

### 12b.5 Image build + push

`Dockerfile.dataplane` already exists (Phase 1). Add a `make image-dataplane` target:

```make
image-dataplane:
	docker build -t localhost:5000/saas/dataplane:$$(git describe --always) -f Dockerfile.dataplane .
	docker push localhost:5000/saas/dataplane:$$(git describe --always)
```

For local dev, run a `registry:2` container on `localhost:5000`. In production, the operator points at their preferred registry via the `image` field in the deployment metadata.

### 12b.6 Composite Provisioner wiring

`deployments.CompositeProvisioner` (introduced in Phase 12a) now gets the `K3s Adapter`:

```go
type CompositeProvisioner struct {
    Local *LocalProvisioner
    Nginx *nginx.Adapter
    K3s   *k3s.Adapter
    // Postgres, OpenBao in 12c, 12d
}

func (c *CompositeProvisioner) Provision(ctx context.Context, d *Deployment) (BootstrapResult, error) {
    // Order: see §6.2 in AGENTS.md. Phase 12b implements step 7 + step 8.
    // Steps 4-6 are LocalProvisioner; 9-11 are Nginx; ...

    // Step 7-8: k3s namespace + workload.
    if err := c.K3s.Provision(ctx, d); err != nil { return BootstrapResult{}, err }
    // Step 4-6: DB + migrations + seed.
    boot, err := c.Local.Provision(ctx, d); if err != nil { return BootstrapResult{}, err }
    // Step 9-10: nginx vhost + cert.
    if err := c.Nginx.ApplyVhost(ctx, vhostInput(d)); err != nil { return boot, err }
    if err := c.Nginx.IssueCertificate(ctx, d.ID, d.PrimaryVhost, d.CustomDomains); err != nil { return boot, err }
    // Step 11: wait for /healthz via the public vhost.
    if err := waitForPublicHealth(ctx, d); err != nil { return boot, err }
    return boot, nil
}
```

The order is opinionated and matches §6.2. Phase 12e re-orders into the full 13-step sequence with proper rollback.

### 12b.7 NodePort allocation

NodePort range default in k3s is 30000–32767. Allocate one per Deployment from the control-plane DB:

```sql
ALTER TABLE deployment ADD COLUMN node_port integer UNIQUE;
```

Allocation logic: pick the smallest free port in `[30000, 32767)` that doesn't conflict with the homelab's existing usage. Reserve a config-driven range (default `[31000, 31500]`) to avoid collisions with non-saas k3s services.

### 12b.8 Tests

`adapter_test.go`:

- Render: golden YAML for a known overlay (deployment_id stable).
- Apply mock client: verify `metav1.ApplyOptions{FieldManager: "saas-controlplane", Force: true}` on every call.
- Destroy: namespace delete returns nil even if already-absent (idempotent).
- Restart: triggers a rollout via annotation patch.
- WaitForRollout: succeeds when observed_generation == generation + available_replicas >= replicas.
- WaitForRollout: returns error on `ProgressDeadlineExceeded`.

`network_test.go`:

- Cross-namespace deny (above).
- Egress to Postgres ALLOWED (positive case): pod in dep namespace can `nc -zv host 5432`.
- Egress to a random host BLOCKED: pod cannot `nc -zv 1.1.1.1 443`.
- Ingress from outside the host CIDR BLOCKED.

### 12b.9 Commits

```bash
git add deploy/k3s/base/ deploy/k3s/overlays/template/
git commit -m "add k3s base manifests and overlay template"

git add internal/controlplane/provision/k3s/
git commit -m "implement k3s provisioner with typed apply"

git add Makefile Dockerfile.dataplane
git commit -m "add image build target"

git add cmd/controlplane/main.go internal/controlplane/deployments/
git commit -m "wire k3s adapter into composite provisioner"
```

---

## Verification checklist

```bash
# 1. The image registry is reachable.
$ docker run -d -p 5000:5000 --restart always --name local-registry registry:2 2>/dev/null
$ make image-dataplane
$ curl -s http://localhost:5000/v2/saas/dataplane/tags/list | jq

# 2. kubectl access works as saas user.
$ KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get nodes
# Expected: at least one node Ready

# 3. Provision a test deployment.
$ ./bin/saasctl deployment create --project nettest --environment dev --image $(git describe --always)

# 4. Namespace exists with labels.
$ kubectl get ns | grep saas-nettest-dev
$ kubectl get ns saas-nettest-dev -o jsonpath='{.metadata.labels}' | jq
# Expected: saas.omarss.net/deployment-id, saas.omarss.net/project, saas.omarss.net/environment

# 5. Workload exists + healthy.
$ kubectl -n saas-nettest-dev get pods
$ kubectl -n saas-nettest-dev get svc
$ kubectl -n saas-nettest-dev get networkpolicy
# Expected: 3 NetworkPolicies (default-deny, allow-from-host-nginx, allow-egress-platform)

# 6. Pod /healthz responds.
$ curl -s http://localhost:31000/healthz | jq
# Expected: { status: ok, ... }

# 7. Cross-namespace deny (real test).
$ kubectl -n saas-nettest-dev run probe --rm -i --restart=Never --image=curlimages/curl -- \
    curl --max-time 3 -sf http://data-plane.saas-OTHERDEP.svc.cluster.local:8080/healthz
# Expected: timeout / unreachable (NetworkPolicy blocks)

# 8. Egress to host Postgres allowed.
$ kubectl -n saas-nettest-dev run probe --rm -i --restart=Never --image=busybox -- \
    nc -zv $(hostname -I | awk '{print $1}') 5432
# Expected: open

# 9. Egress to random internet host blocked.
$ kubectl -n saas-nettest-dev run probe --rm -i --restart=Never --image=busybox -- \
    nc -zv -w 2 1.1.1.1 443
# Expected: blocked

# 10. Destroy cleans up.
$ ./bin/saasctl deployment delete dep_... --retain-days 0
$ ./bin/saasctl deployment purge dep_...
$ kubectl get ns | grep saas-nettest-dev
# Expected: not found

# 11. Rollout failure is detected.
$ # Force a bad image; provision should mark deployment as failed and not proceed.
$ ./bin/saasctl deployment create --project bad --environment dev --image ghost-image-that-does-not-exist
# Expected: error from rollout wait; status=failed; namespace exists but pods CrashLoopBackOff.

# 12. §17.4 partial: rollback behavior.
$ # On failed provision, namespace should be left for destroy reconciler (Phase 12e),
$ # but vhost + cert from Phase 12a should NOT have been written yet (since k3s step ran first).
```

---

## Anti-pattern guards

- **NEVER** use `kubectl apply -f` from Go code. Use client-go typed apply with FieldManager + Force.
- **NEVER** use a shared ServiceAccount across Deployments. Each ns gets its own `data-plane` SA — needed for OpenBao Kubernetes auth role binding (Phase 12d).
- **NEVER** skip the NetworkPolicy default-deny. Layer 4 of tenant isolation depends on it; the cross-namespace test pins.
- **NEVER** widen `allow-egress-platform` to `0.0.0.0/0`. Egress is strictly Postgres + OpenBao + Keycloak + Novu + DNS.
- **NEVER** allocate a NodePort outside the configured range (default `[31000, 31500]`). Collisions with non-saas k3s services are nasty.
- **NEVER** push the data-plane image to a public registry without operator approval. The image carries OpenBao policy templates that contain the deployment id naming convention.
- **NEVER** patch a Deployment without `FieldManager: "saas-controlplane"`. Without it, server-side apply fails over field ownership conflicts.
- **NEVER** delete a namespace if `status='active'` in the control plane DB. Destroy must go through the service layer's state machine; raw kubectl delete leaves the control plane row drifted.

---

## Open questions

1. **Image registry.** Default local: `localhost:5000` via a registry:2 container. For production, the operator must configure a private registry (or use a public one with image pull secrets). Confirm.
2. **NodePort range.** Default `[31000, 31500]` — 500 deployments max. Adequate for MVP; raise via config if needed.
3. **Replicas > 1.** Out of MVP per single-host constraint. When multi-host k3s lands, a `deployment.metadata.replicas` override drives the manifest. Confirm deferral.
4. **Image pull secrets.** Out of MVP local dev (the local registry is unauthenticated). Production operators add a `dockerconfigjson` Secret; the manifest is amended to reference it. Add as a v1 enhancement.

---

## Phase 12b — Definition of done

- [ ] `deploy/k3s/base/` + `deploy/k3s/overlays/template/` committed
- [ ] `internal/controlplane/provision/k3s/` complete: adapter, render, apply, rollout, tests
- [ ] CompositeProvisioner uses `K3s.Provision` + `K3s.Destroy` + `K3s.Restart`
- [ ] Rendered manifests use kustomize Go API (not text templates)
- [ ] All applies use FieldManager=saas-controlplane + Force=true
- [ ] First real Deployment has a namespace + 3 NetworkPolicies + SA + Deployment + Service
- [ ] Cross-namespace deny test passes (REAL k3s)
- [ ] Egress to platform services positive cases pass
- [ ] Egress to internet host blocked
- [ ] NodePort allocated from the configured range; unique per Deployment
- [ ] Rollout wait detects success + failure
- [ ] `make image-dataplane` builds + pushes to local registry
- [ ] All Phase 2-12a tests still green
- [ ] PR template, `ready` label, CI green

---

## CHECKPOINT 6 — First real k3s namespace with NetworkPolicy isolation

### What was done
- deploy/k3s/base/ (7 manifests) + deploy/k3s/overlays/template/
- internal/controlplane/provision/k3s/{adapter, render, apply, rollout, network_test, adapter_test}.go
- Makefile: image-dataplane target + local registry runbook in docs/runbooks/k3s-host-setup.md
- CompositeProvisioner now invokes K3sAdapter
- One real namespace `saas-<project>-<env>` with default-deny NP + pods Healthy

### What to verify (user runs these)
```bash
$ kubectl get ns | grep ^saas-
$ kubectl -n saas-<project>-<env> get all,networkpolicy
$ kubectl -n saas-<project>-<env> describe networkpolicy default-deny
$ kubectl -n saas-<project>-<env> describe networkpolicy allow-from-host-nginx
$ kubectl -n saas-<project>-<env> describe networkpolicy allow-egress-platform

# Cross-namespace deny:
$ kubectl -n saas-<project>-<env> run probe --rm -i --restart=Never --image=curlimages/curl -- \
    curl --max-time 3 -sf http://data-plane.saas-OTHER.svc.cluster.local:8080/healthz
# Expected: timeout / blocked

# /healthz reachable through NodePort:
$ curl -s http://localhost:31000/healthz
```

### What approval means
By proceeding past CHECKPOINT 6, you accept:
- The platform creates and tears down k3s namespaces matching `saas-<project>-<env>`.
- Every namespace gets default-deny + ingress-from-host-CIDR + egress-to-platform-services. Cross-namespace traffic between deployments is physically blocked.
- ServiceAccount `data-plane` in each namespace is reused for OpenBao auth (Phase 12d binds it to a per-Deployment role).
- NodePorts are allocated from the configured range and recorded in the control-plane DB.
- The image is pulled from `localhost:5000/saas/dataplane:<version>` by default; operator overrides via the deployment metadata.

### Rollback if rejected
```bash
$ kubectl get ns -l saas.omarss.net/deployment-id -o name | xargs -I{} kubectl delete {}
$ git revert <hashes for the 4 phase-12b commits>
```

---

End of Phase 12b. Next: `13c-postgres-provisioner.md`.
