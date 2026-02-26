# Server3 Docker Target State

Last updated: 2026-02-26 (AEST, +10:00)

## Scope
- Baseline Docker runtime expectations for Server3 host operations.

## Host Baseline
- Docker engine installed and available.
- Docker compose plugin available via `docker compose`.
- Runtime control uses systemd service management where applicable.

## Verification Commands
```bash
docker --version
docker compose version
systemctl status docker --no-pager
```

## Notes
- Service-specific container orchestration details are documented only for currently in-scope components.
