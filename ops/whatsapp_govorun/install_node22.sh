#!/usr/bin/env bash
set -euo pipefail

if command -v node >/dev/null 2>&1; then
  current_major="$(node -v | sed 's/^v//' | cut -d. -f1)"
else
  current_major="0"
fi

if [[ "${current_major}" -ge 22 ]]; then
  echo "Node already >=22: $(node -v)"
  exit 0
fi

curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

echo "Installed Node: $(node -v)"
echo "Installed npm: $(npm -v)"
