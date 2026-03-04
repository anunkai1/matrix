#!/usr/bin/env bash
set -euo pipefail

# Use noninteractive mode for unattended monthly upgrades.
export DEBIAN_FRONTEND=noninteractive

/usr/bin/apt-get update
/usr/bin/apt-get upgrade -y

