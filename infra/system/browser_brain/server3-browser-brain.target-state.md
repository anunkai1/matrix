# Server3 Browser Brain Target State

## Intent

Provide a dedicated local browser-control runtime for structured browser automation on Server3.

## Desired State

- Runtime user: `browser_brain`
- Service unit: `server3-browser-brain.service`
- Env file: `/etc/default/server3-browser-brain`
- State root: `/var/lib/server3-browser-brain`
- Browser profile: `/var/lib/server3-browser-brain/profile`
- Capture directory: `/var/lib/server3-browser-brain/captures`
- Browser executable: `brave-browser`
- Bind address: `127.0.0.1:47831`
- Default mode: headless

## Runtime Policy

- Browser Brain is separate from `Server3 TV` mode and must not reuse the `tv` user profile.
- The service is loopback-only and intended for local trusted callers.
- Snapshot refs are required for element actions.
- Screenshots are temp artifacts with TTL-based cleanup.

## Provisioning Sources

- `ops/browser_brain/setup_runtime_user.sh`
- `ops/browser_brain/install_runtime_venv.sh`
- `ops/browser_brain/install_user_service.sh`
- `infra/systemd/server3-browser-brain.service`

## Verification Commands

```bash
id browser_brain
systemctl status server3-browser-brain.service --no-pager
curl -fsS http://127.0.0.1:47831/v1/status | jq
```
