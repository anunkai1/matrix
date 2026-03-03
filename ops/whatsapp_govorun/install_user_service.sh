#!/usr/bin/env bash
set -euo pipefail

# Backward-compatible script name; now installs/enables system services.

sudo systemctl daemon-reload
sudo systemctl enable whatsapp-govorun-bridge.service govorun-whatsapp-bridge.service

echo "Enabled system services: whatsapp-govorun-bridge.service, govorun-whatsapp-bridge.service"
