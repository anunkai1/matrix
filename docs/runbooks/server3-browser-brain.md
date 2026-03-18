# Server3 Browser Brain

## Purpose

Provide a dedicated local browser-automation runtime on Server3 that higher-level assistants can call through a loopback HTTP API.

This runtime is separate from `Server3 TV` mode:

- `Server3 TV` remains the human-visible HDMI/browser desktop path.
- Browser Brain is the machine-operated browser-control service.

## Runtime Shape

- Linux user: `browser_brain`
- Service unit: `server3-browser-brain.service`
- Live env file: `/etc/default/server3-browser-brain`
- Default state root: `/var/lib/server3-browser-brain`
- Managed browser: `brave-browser`
- Control surface: loopback HTTP on `127.0.0.1:47831`
- Action model: structured snapshot refs, then element-targeted actions

## Install

Prepare the runtime user and state directories:

```bash
cd /home/architect/matrix
bash ops/browser_brain/setup_runtime_user.sh
```

Provision the Python venv and Playwright dependency:

```bash
cd /home/architect/matrix
bash ops/browser_brain/install_runtime_venv.sh
```

Install the systemd service and env file:

```bash
cd /home/architect/matrix
bash ops/browser_brain/install_user_service.sh
sudo systemctl start server3-browser-brain.service
```

## Status And Verification

Check systemd:

```bash
systemctl status server3-browser-brain.service --no-pager
```

Check the local API:

```bash
curl -fsS http://127.0.0.1:47831/v1/status | jq
```

## API Surface

Routes:

- `GET /v1/status`
- `POST /v1/start`
- `POST /v1/stop`
- `GET /v1/tabs`
- `POST /v1/tabs/open`
- `POST /v1/tabs/focus`
- `POST /v1/tabs/close`
- `POST /v1/navigate`
- `POST /v1/snapshot`
- `POST /v1/screenshot`
- `POST /v1/wait`
- `POST /v1/act/click`
- `POST /v1/act/type`
- `POST /v1/act/press`

Examples:

Open a tab:

```bash
curl -fsS http://127.0.0.1:47831/v1/tabs/open \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com"}' | jq
```

Capture a snapshot from the first tab:

```bash
curl -fsS http://127.0.0.1:47831/v1/snapshot \
  -H 'Content-Type: application/json' \
  -d '{}' | jq
```

Click an element by snapshot ref:

```bash
curl -fsS http://127.0.0.1:47831/v1/act/click \
  -H 'Content-Type: application/json' \
  -d '{"tab_id":"tab-1234abcd","snapshot_id":"snap-1234abcd","ref":"el-0001"}' | jq
```

## Behavior Notes

- The service keeps one isolated persistent browser profile under `/var/lib/server3-browser-brain/profile`.
- Snapshot refs are short-lived and scoped to the most recent snapshot for a tab.
- On stale-target failures the service performs one bounded re-snapshot/rebind attempt, then returns a structured error.
- Screenshots are stored under `/var/lib/server3-browser-brain/captures` and old files are cleaned up on service start based on the configured TTL.
- Typed text is not logged verbatim; only action metadata is logged.

## Out Of Scope For This MVP

- Existing-session attach to a human browser profile
- Arbitrary JavaScript evaluation through the public API
- Browser actions exposed over a non-local network interface
- Replacing the existing `Server3 TV` browser helpers
