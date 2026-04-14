.PHONY: k3s-config apply-k8s apply-obsidian apply-openclaw apply-network-policies apply-nginx apply-apps-host apply-geofence geofence-status geofence-disable geofence-enable geofence-refresh apply-all

# Copy k3s server configs to /etc/rancher/k3s/
k3s-config:
	sudo cp k3s/config.yaml /etc/rancher/k3s/config.yaml
	sudo cp k3s/admission-control.yaml /etc/rancher/k3s/admission-control.yaml
	sudo cp k3s/audit-policy.yaml /etc/rancher/k3s/audit-policy.yaml
	sudo systemctl restart k3s

# Apply default network policies
apply-network-policies:
	kubectl apply -f network-policies/

# Deploy Obsidian Sync (CouchDB)
# NOTE: secret must be created manually first:
#   kubectl create namespace obsidian-sync
#   kubectl create secret generic couchdb-credentials -n obsidian-sync \
#     --from-literal=COUCHDB_USER=omar \
#     --from-literal=COUCHDB_PASSWORD=$$(openssl rand -base64 24)
apply-obsidian:
	kubectl apply -f apps/obsidian-sync/

# Deploy OpenClaw
apply-openclaw:
	kubectl apply -f apps/openclaw/

# Copy nginx site configs (run certbot after)
apply-nginx:
	sudo cp nginx/swet.omarss.net.conf /etc/nginx/sites-available/swet.omarss.net
	sudo cp nginx/sync.omarss.net.conf /etc/nginx/sites-available/sync.omarss.net
	sudo cp nginx/apps.omarss.net.conf /etc/nginx/sites-available/apps.omarss.net
	sudo ln -sf /etc/nginx/sites-available/swet.omarss.net /etc/nginx/sites-enabled/
	sudo ln -sf /etc/nginx/sites-available/sync.omarss.net /etc/nginx/sites-enabled/
	sudo ln -sf /etc/nginx/sites-available/apps.omarss.net /etc/nginx/sites-enabled/
	sudo nginx -t && sudo systemctl reload nginx

# One-shot full setup for the apps.omarss.net APK host:
# creates /srv/apps owned by omar, installs vhost, reloads nginx.
# After this, run: sudo certbot --nginx -d apps.omarss.net
apply-apps-host:
	sudo bash scripts/setup-apps-host.sh

# Saudi Arabia geofence: blocks all incoming TCP from non-SA IPs except
# tailscale, LAN, and tcp/80 (kept open for ACME). Pre-flights against
# the host's own public IP and refuses to apply if it would lock you out.
apply-geofence:
	sudo bash geofence/setup.sh

geofence-status:
	sudo geofence-status

geofence-disable:
	sudo geofence-disable

geofence-enable:
	sudo geofence-apply

geofence-refresh:
	sudo geofence-refresh

# Apply all k8s resources
apply-k8s: apply-network-policies apply-obsidian apply-openclaw

# Apply everything
apply-all: k3s-config apply-nginx apply-k8s
