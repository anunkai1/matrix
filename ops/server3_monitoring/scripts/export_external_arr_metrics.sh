#!/usr/bin/env bash

set -euo pipefail

output_dir="${1:-/var/lib/node_exporter_textfile}"
metric_target="${2:-/srv/external/server3-arr}"
metric_mount_label="${3:-${metric_target}}"
docker_container="${4:-}"
output_file="${output_dir}/server3_external_arr.prom"

mkdir -p "${output_dir}"
tmp_file="$(mktemp "${output_dir}/server3_external_arr.prom.XXXXXX")"

cleanup() {
  rm -f "${tmp_file}"
}
trap cleanup EXIT

cat <<'EOF' > "${tmp_file}"
# HELP server3_external_arr_up External ARR mount present on host.
# TYPE server3_external_arr_up gauge
# HELP server3_external_arr_size_bytes External ARR filesystem size in bytes.
# TYPE server3_external_arr_size_bytes gauge
# HELP server3_external_arr_used_bytes External ARR filesystem used bytes.
# TYPE server3_external_arr_used_bytes gauge
# HELP server3_external_arr_avail_bytes External ARR filesystem available bytes.
# TYPE server3_external_arr_avail_bytes gauge
# HELP server3_external_arr_used_percent External ARR filesystem used percentage.
# TYPE server3_external_arr_used_percent gauge
EOF

if [[ -n "${docker_container}" ]]; then
  df_command=(docker exec "${docker_container}" df -P -B1 "${metric_target}")
else
  df_command=(df -P -B1 "${metric_target}")
fi

if df_line="$("${df_command[@]}" 2>/dev/null | awk 'NR==2 {gsub(/%/, "", $5); print $1, $2, $3, $4, $5, $6}')"; then
  read -r source size used avail percent target <<EOF
${df_line}
EOF
else
  cat <<EOF >> "${tmp_file}"
server3_external_arr_up{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_size_bytes{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_used_bytes{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_avail_bytes{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_used_percent{device="",mountpoint="${metric_mount_label}"} 0
EOF
  mv "${tmp_file}" "${output_file}"
  trap - EXIT
  exit 0
fi

if [[ "${target}" == "${metric_target}" ]]; then
  cat <<EOF >> "${tmp_file}"
server3_external_arr_up{device="${source}",mountpoint="${metric_mount_label}"} 1
server3_external_arr_size_bytes{device="${source}",mountpoint="${metric_mount_label}"} ${size}
server3_external_arr_used_bytes{device="${source}",mountpoint="${metric_mount_label}"} ${used}
server3_external_arr_avail_bytes{device="${source}",mountpoint="${metric_mount_label}"} ${avail}
server3_external_arr_used_percent{device="${source}",mountpoint="${metric_mount_label}"} ${percent}
EOF
else
  cat <<EOF >> "${tmp_file}"
server3_external_arr_up{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_size_bytes{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_used_bytes{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_avail_bytes{device="",mountpoint="${metric_mount_label}"} 0
server3_external_arr_used_percent{device="",mountpoint="${metric_mount_label}"} 0
EOF
fi

chmod 0644 "${tmp_file}"
mv "${tmp_file}" "${output_file}"
trap - EXIT
