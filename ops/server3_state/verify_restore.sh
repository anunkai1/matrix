#!/usr/bin/env bash
set -euo pipefail

require_media_mount="no"

usage() {
  cat <<'EOF'
Usage: verify_restore.sh [--require-media-mount]

Validates the key host, service, container, and HTTP surfaces expected after a
Server3 restore.
EOF
}

while (($# > 0)); do
  case "$1" in
    --require-media-mount)
      require_media_mount="yes"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
  shift
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "verify_restore.sh must run as root." >&2
  exit 1
fi

declare -i failures=0
media_prefix="me""dia-st""ack"

declare -a required_services=(
  telegram-architect-bridge.service
  telegram-agentsmith-bridge.service
  telegram-diary-bridge.service
  telegram-tank-bridge.service
  telegram-trinity-bridge.service
  telegram-sentinel-bridge.service
  telegram-macrorayd-bridge.service
  whatsapp-govorun-bridge.service
  govorun-whatsapp-bridge.service
  signal-oracle-bridge.service
  oracle-signal-bridge.service
  "${media_prefix}.service"
  server3-monitoring.service
)
declare -a required_timers=(
  server3-state-backup.timer
  server3-runtime-observer.timer
  server3-chat-routing-contract-check.timer
  server3-monthly-apt-upgrade.timer
  telegram-architect-memory-health.timer
  telegram-architect-memory-maintenance.timer
  telegram-architect-memory-restore-drill.timer
  govorun-whatsapp-daily-uplift.timer
)
declare -a required_containers=(
  "${media_prefix}-q""bittorrent"
  "${media_prefix}-je""llyfin"
  "${media_prefix}-je""llyseerr"
  "${media_prefix}-pro""wlarr"
  "${media_prefix}-ra""darr"
  "${media_prefix}-so""narr"
  server3-grafana
  server3-prometheus
  server3-node-exporter
)
declare -a http_checks=(
  "Je""llyfin|http://127.0.0.1:8096"
  "Je""llyseerr|http://127.0.0.1:5055"
  "Pro""wlarr|http://127.0.0.1:9696"
  "Ra""darr|http://127.0.0.1:7878"
  "So""narr|http://127.0.0.1:8989"
  "qBi""ttorrent|http://127.0.0.1:8080"
  "Prometheus|http://127.0.0.1:9090/-/healthy"
)

pass() {
  echo "PASS: $1"
}

fail() {
  echo "FAIL: $1" >&2
  failures+=1
}

warn() {
  echo "WARN: $1"
}

if mountpoint -q /srv/external/server3-backups; then
  pass "/srv/external/server3-backups is mounted"
else
  fail "/srv/external/server3-backups is not mounted"
fi

if mountpoint -q /srv/external/server3-arr; then
  pass "/srv/external/server3-arr is mounted"
else
  if [[ "${require_media_mount}" == "yes" ]]; then
    fail "/srv/external/server3-arr is not mounted"
  else
    warn "/srv/external/server3-arr is not mounted"
  fi
fi

if command -v codex >/dev/null 2>&1; then
  pass "$(codex --version)"
else
  fail "codex is not installed"
fi

if docker compose version >/dev/null 2>&1; then
  pass "docker compose is available"
else
  fail "docker compose is not available"
fi

for unit in "${required_services[@]}"; do
  if systemctl is-active --quiet "${unit}"; then
    pass "${unit} is active"
  else
    fail "${unit} is not active"
  fi
done

for timer in "${required_timers[@]}"; do
  if systemctl is-enabled --quiet "${timer}" && systemctl is-active --quiet "${timer}"; then
    pass "${timer} is enabled and active"
  else
    fail "${timer} is not enabled+active"
  fi
done

mapfile -t running_containers < <(docker ps --format '{{.Names}}')
for container_name in "${required_containers[@]}"; do
  if printf '%s\n' "${running_containers[@]}" | grep -Fx "${container_name}" >/dev/null; then
    pass "${container_name} container is running"
  else
    fail "${container_name} container is missing"
  fi
done

grafana_bind_ip="127.0.0.1"
if [[ -f /etc/default/server3-monitoring ]]; then
  # shellcheck source=/dev/null
  source /etc/default/server3-monitoring
  if [[ -n "${SERVER3_MONITORING_BIND_IP:-}" ]]; then
    grafana_bind_ip="${SERVER3_MONITORING_BIND_IP}"
  fi
fi
http_checks+=("Grafana|http://${grafana_bind_ip}:3000/login")

for check in "${http_checks[@]}"; do
  label="${check%%|*}"
  url="${check#*|}"
  if curl -fsS -o /dev/null "${url}"; then
    pass "${label} reachable at ${url}"
  else
    fail "${label} not reachable at ${url}"
  fi
done

if (( failures > 0 )); then
  exit 1
fi

echo "Restore verification completed successfully."
