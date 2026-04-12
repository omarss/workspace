#!/bin/bash
# UFW firewall rules for homelab
# Run once after fresh install. ufw rules are persistent across reboots.
set -e

sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH
sudo ufw allow 22/tcp

# HTTP/HTTPS (nginx)
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# RDP (xrdp)
sudo ufw allow 3389/tcp

sudo ufw enable
echo "UFW rules applied."
