# Server3 Monitoring

## Purpose

Run a LAN-only Prometheus + Grafana + node_exporter stack for Server3 host monitoring.

## Live Shape

- compose root: `/srv/server3-monitoring`
- live stack file: `/srv/server3-monitoring/monitoring-stack.yml`
- live env file: `/etc/default/server3-monitoring`
- systemd unit: `server3-monitoring.service`
- Grafana bind: `http://192.168.0.148:3000`
- Prometheus bind: `127.0.0.1:9090`
- node exporter: internal-only on the compose network

## Credentials

- Grafana username: `admin`
- Grafana password: `Qwertyu1!`

## Live Env

Expected variables in `/etc/default/server3-monitoring`:

- `SERVER3_MONITORING_BIND_IP`
- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`

## Deployment Notes

- Grafana is the only exposed UI.
- Prometheus and node exporter are not exposed on the LAN.
- Grafana dashboards and datasource are provisioned from the repo.
- Provisioned dashboards:
  - `Server3 Node Overview`
  - `Node Exporter Full` (`gnetId=1860`, revision `42`)
- The systemd unit pre-creates/chowns the bind-mounted data directories before startup:
  - Grafana data: UID/GID `472:472`
  - Prometheus data: UID/GID `65534:65534`

## Basic Verification

```bash
sudo systemctl status server3-monitoring.service --no-pager
curl -I http://192.168.0.148:3000/login
curl -s http://127.0.0.1:9090/api/v1/targets
```

## Files

- compose: `ops/server3_monitoring/monitoring-stack.yml`
- env template: `ops/server3_monitoring/.env.example`
- Prometheus config: `ops/server3_monitoring/prometheus/prometheus.yml`
- Grafana provisioning: `ops/server3_monitoring/grafana/provisioning`
- dashboard JSONs:
  - `ops/server3_monitoring/grafana/dashboards/server3-node-overview.json`
  - `ops/server3_monitoring/grafana/dashboards/node-exporter-full.json`
- unit: `infra/systemd/server3-monitoring.service`
