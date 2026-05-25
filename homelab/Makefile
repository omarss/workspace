.PHONY: k3s-config apply-k8s apply-obsidian apply-openclaw apply-network-policies apply-nginx apply-apps-host apply-tweets-host tweets-browser-login tweets-refresh tweets-cookies-edit tweets-status tweets-restart apply-geofence geofence-status geofence-disable geofence-enable geofence-refresh apply-all

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
	sudo cp nginx/qudrat.omarss.net.conf /etc/nginx/sites-available/qudrat.omarss.net
	sudo ln -sf /etc/nginx/sites-available/swet.omarss.net /etc/nginx/sites-enabled/
	sudo ln -sf /etc/nginx/sites-available/sync.omarss.net /etc/nginx/sites-enabled/
	sudo ln -sf /etc/nginx/sites-available/apps.omarss.net /etc/nginx/sites-enabled/
	sudo ln -sf /etc/nginx/sites-available/qudrat.omarss.net /etc/nginx/sites-enabled/
	sudo nginx -t && sudo systemctl reload nginx

# One-shot full setup for the apps.omarss.net APK host:
# creates /srv/apps owned by omar, installs vhost, reloads nginx.
# After this, run: sudo certbot --nginx -d apps.omarss.net
apply-apps-host:
	sudo bash scripts/setup-apps-host.sh

# One-shot full setup for the tweets.omarss.net browser-hybrid scraper:
# builds tweetsd, installs both systemd units (tweets + tweets-browser),
# creates /srv/tweets (700, holds the X session cookies + browser profile),
# sets up the python venv for the CDP refresher, installs the nginx vhost
# + snippet, reloads nginx. Idempotent — safe to re-run after `git pull`.
apply-tweets-host:
	sudo bash scripts/setup-tweets-host.sh

# ── tweets convenience wrappers ────────────────────────────────────────

# ONE-TIME: open a HEADED Chrome with the systemd unit's profile so you
# can log into x.com interactively. Closes the headless instance first,
# launches headed, you log in, then we restart headless so it inherits
# the saved session. Needs your graphical session env (Wayland/X).
tweets-browser-login:
	@echo "Stopping headless tweets-browser…"
	@sudo systemctl stop tweets-browser.service
	@rm -f /srv/tweets/browser-profile/SingletonLock \
	       /srv/tweets/browser-profile/SingletonCookie \
	       /srv/tweets/browser-profile/SingletonSocket 2>/dev/null || true
	@echo "Launching headed Chrome — log into x.com, then close the window."
	@google-chrome \
	    --user-data-dir=/srv/tweets/browser-profile \
	    --no-first-run --no-default-browser-check \
	    --new-window https://x.com/login || true
	@echo "Restarting headless tweets-browser…"
	@sudo systemctl restart tweets-browser.service
	@echo "Now run: make -C homelab tweets-refresh"

# Trigger the CDP refresher to capture fresh cookies + search template.
tweets-refresh:
	sudo -u omar /srv/tweets/refresh-venv/bin/python /srv/tweets/refresh-template.py
	sudo systemctl restart tweets.service

tweets-cookies-edit:
	sudo -e /srv/tweets/cookies.json

tweets-status:
	@sudo systemctl --no-pager status tweets-browser.service | head -6 || true
	@echo
	@sudo systemctl --no-pager status tweets.service | head -6 || true
	@echo
	@curl -sS http://127.0.0.1:8088/healthz || echo "(local healthz unreachable)"

tweets-restart:
	sudo systemctl restart tweets-browser.service
	sleep 2
	sudo systemctl restart tweets.service
	@sudo systemctl --no-pager status tweets.service | head -6

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
