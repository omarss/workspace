// Quickstart demonstrates the §21 first-class SDK workflows end-to-end.
//
// This is a RUNNABLE example, not a test. It requires a live stack:
//
//	make compose-up && make migrate
//	./bin/saasctl operator login   # writes ~/.saas/operator_token
//	export SAAS_OPERATOR_TOKEN=$(cat ~/.saas/operator_token)
//	go run ./sdk/go/examples/quickstart
//
// The program walks ProvisionDeployment -> CreateTenant -> CreateAPIKey
// -> SendNotification, then exits. Secrets returned by the platform
// (bootstrap API key, minted API key) are deliberately NOT printed —
// only their ids. Adapt locally if you need to capture them for testing.
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	cp "github.com/omarss/saas/sdk/go/controlplane"
	dp "github.com/omarss/saas/sdk/go/dataplane"
	"github.com/omarss/saas/sdk/go/workflows"
)

func main() {
	opToken := os.Getenv("SAAS_OPERATOR_TOKEN")
	if opToken == "" {
		log.Fatal("SAAS_OPERATOR_TOKEN not set; run `saasctl operator login` first")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	controlURL := envOr("SAAS_CONTROL_URL", "https://control.saas.omarss.net")
	cpClient, err := cp.NewClientWithResponses(controlURL,
		cp.WithRequestEditorFn(workflows.BearerControlPlane(opToken)))
	if err != nil {
		log.Fatalf("control plane client: %v", err)
	}

	// 1) Provision a fresh deployment.
	prov, err := workflows.ProvisionDeployment(ctx, cpClient, workflows.ProvisionInput{
		ProjectSlug:     "quickstart",
		EnvironmentSlug: "dev",
		ImageVersion:    envOr("SAAS_IMAGE_VERSION", "v0.3.1"),
		Region:          envOr("SAAS_REGION", "local"),
		Modules:         []string{"identity", "notifications", "rbac", "api-keys"},
	})
	if err != nil {
		log.Fatalf("provision: %v", err)
	}
	// Print the id only — never log BootstrapSecret.
	fmt.Println("provisioned deployment id:", prov.Deployment.Id)

	// 2) Talk to the data plane using the one-time bootstrap secret.
	dpClient, err := dp.NewClientWithResponses(
		"https://"+prov.Deployment.PrimaryVhost,
		dp.WithRequestEditorFn(workflows.BearerDataPlane(prov.BootstrapSecret)))
	if err != nil {
		log.Fatalf("data plane client: %v", err)
	}

	tenant, err := workflows.CreateTenant(ctx, dpClient, workflows.CreateTenantInput{
		Slug: "acme", Name: "Acme Inc",
	})
	if err != nil {
		log.Fatalf("create tenant: %v", err)
	}
	fmt.Println("created tenant id:", tenant.Id)

	// 3) Mint an API key under the tenant.
	apiKey, err := workflows.CreateAPIKey(ctx, dpClient, workflows.CreateAPIKeyInput{
		TenantID: tenant.Id,
		Name:     "ci-bot",
		Scopes:   []string{"tenant.read"},
	})
	if err != nil {
		log.Fatalf("create api key: %v", err)
	}
	fmt.Println("minted api key id:", apiKey.Data.Id)
	// apiKey.Secret is plaintext, one-time — never print it.

	// 4) Send a welcome notification (queued).
	notif, err := workflows.SendNotification(ctx, dpClient, workflows.SendNotificationInput{
		WorkflowName: "welcome",
		ToUserID:     "user_01H000000000000000000000",
		Payload:      map[string]interface{}{"tenant_id": tenant.Id},
	})
	if err != nil {
		log.Fatalf("send notification: %v", err)
	}
	fmt.Println("queued notification id:", notif.Id)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
