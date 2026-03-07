#!/usr/bin/env bash
set -euo pipefail

sudo systemctl restart signal-oracle-bridge.service
sudo systemctl restart oracle-signal-bridge.service
sudo systemctl status signal-oracle-bridge.service --no-pager -n 30
sudo systemctl status oracle-signal-bridge.service --no-pager -n 30
