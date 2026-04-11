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

Connection modes:

- `managed` (default): Browser Brain launches and owns its own persistent profile under `/var/lib/server3-browser-brain/profile`
- `existing_session`: Browser Brain attaches over local CDP to a browser process that was started elsewhere, for example the visible TV-session Brave helper

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

Use the local CLI wrapper:

```bash
cd /home/architect/matrix
bash ops/browser_brain/browser_brain_ctl.sh status
bash ops/browser_brain/browser_brain_ctl.sh start
```

## Existing-Session Attach Mode

Set Browser Brain to attach mode in `/etc/default/server3-browser-brain`:

```bash
BROWSER_BRAIN_CONNECTION_MODE=existing_session
BROWSER_BRAIN_REMOTE_DEBUGGING_PORT=9223
```

Then start the visible TV-side Brave session with local CDP enabled:

```bash
cd /home/architect/matrix
bash ops/tv-desktop/server3-tv-brave-browser-brain-session.sh https://x.com/home
```

Notes:

- This keeps login manual in the visible `tv` desktop browser while letting Browser Brain reuse the same session after attachment.
- The TV helper uses a dedicated Brave profile under `/home/tv/.local/state/server3-browser-brain-brave-profile`.
- Browser Brain `stop` will disconnect from the attached browser but does not intentionally close the `tv` user's Brave session.

### Next-Time X.com Flow

If a later Architect session or Telegram chat asks to "log into `x.com`" for Browser Brain, the intended operator flow is:

1. Confirm Browser Brain should use the `existing_session` path, not headed mode.
2. Verify `/etc/default/server3-browser-brain` still has `BROWSER_BRAIN_CONNECTION_MODE=existing_session` and the expected CDP port/URL.
3. Start the visible TV-side helper: `bash ops/tv-desktop/server3-tv-brave-browser-brain-session.sh https://x.com/home`
4. Have the user log into `x.com` manually in that visible `tv` Brave window if the session is not already valid.
5. Start or reuse Browser Brain so it attaches over local CDP and then operate on the attached session.
6. If the site session has expired, repeat only the manual login step; do not switch Browser Brain itself to headed mode.

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
- `POST /v1/console`
- `POST /v1/network`
- `POST /v1/dialogs`
- `POST /v1/dialogs/handle`
- `POST /v1/act/click`
- `POST /v1/act/hover`
- `POST /v1/act/select`
- `POST /v1/act/type`
- `POST /v1/act/press`
- `POST /v1/act/upload`

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

Wrapper examples:

```bash
bash ops/browser_brain/browser_brain_ctl.sh open --url https://example.com
bash ops/browser_brain/browser_brain_ctl.sh snapshot --tab-id tab-1234abcd
bash ops/browser_brain/browser_brain_ctl.sh click --tab-id tab-1234abcd --snapshot-id snap-1234abcd --ref el-0001
bash ops/browser_brain/browser_brain_ctl.sh hover --tab-id tab-1234abcd --snapshot-id snap-1234abcd --ref el-0001
bash ops/browser_brain/browser_brain_ctl.sh select --tab-id tab-1234abcd --snapshot-id snap-1234abcd --ref el-0003 --value option-value
bash ops/browser_brain/browser_brain_ctl.sh console --tab-id tab-1234abcd --limit 20
bash ops/browser_brain/browser_brain_ctl.sh network --tab-id tab-1234abcd --limit 20
bash ops/browser_brain/browser_brain_ctl.sh dialogs --tab-id tab-1234abcd
bash ops/browser_brain/browser_brain_ctl.sh dialog-handle --tab-id tab-1234abcd --accept  # arms the next dialog
bash ops/browser_brain/browser_brain_ctl.sh upload --tab-id tab-1234abcd --snapshot-id snap-1234abcd --ref el-0002 --path /tmp/example.mp4
```

## Behavior Notes

- The service keeps one isolated persistent browser profile under `/var/lib/server3-browser-brain/profile`.
- Snapshot refs are short-lived and scoped to the most recent snapshot for a tab.
- Snapshot responses include an ARIA snapshot plus locator hints, and actions prefer Playwright locator resolution before falling back to the legacy DOM fingerprint matcher.
- On stale-target failures the service performs one bounded re-snapshot/rebind attempt, then returns a structured error.
- Screenshots are stored under `/var/lib/server3-browser-brain/captures` and old files are cleaned up on service start based on the configured TTL.
- Typed text is not logged verbatim; only action metadata is logged.
- Architect now has a keyword-routed first-caller path through `Server3 Browser ...` or `Browser Brain ...`.
- In `existing_session` mode, Browser Brain attaches to a user-run local Chromium browser via CDP instead of launching its own browser process.
- Safe extra action support covers hover, select option, next-dialog handling, dialog history, read-only console messages, and read-only network response events.
- Dialog handling is armed before the action that is expected to trigger a dialog. Unarmed dialogs are dismissed and recorded so a browser action cannot deadlock while waiting for a second API call.

## Navigation Policy

Optional env controls:

```bash
BROWSER_BRAIN_ALLOWED_ORIGINS=
BROWSER_BRAIN_BLOCKED_ORIGINS=
BROWSER_BRAIN_ALLOW_FILE_URLS=false
```

Policy values accept comma- or semicolon-separated entries. Entries may be exact origins such as `https://example.com`, hostnames such as `example.com`, wildcard hosts such as `*.example.com`, or `*`.

Rules:

- `about:blank` is always allowed.
- `http` and `https` are allowed by default unless blocked.
- If `BROWSER_BRAIN_ALLOWED_ORIGINS` is set, navigation must match it.
- `BROWSER_BRAIN_BLOCKED_ORIGINS` wins over the allowlist.
- `file://` navigation is blocked unless `BROWSER_BRAIN_ALLOW_FILE_URLS=true`.
- Redirects are checked after navigation and reported as `navigation_blocked_after_redirect` if the final URL violates policy.

## Live Smoke Test

Run a direct managed-browser smoke test without Telegram:

```bash
cd /home/architect/matrix
/var/lib/server3-browser-brain/venv/bin/python ops/browser_brain/smoke_test.py
```

The smoke test starts a local HTTP fixture, launches Browser Brain with a temporary managed profile, verifies open/snapshot/click/type/select/hover/dialog/console/network/screenshot behavior, then closes the browser. It prefers Playwright's bundled Chromium for deterministic headless verification; set `BROWSER_BRAIN_SMOKE_BROWSER=/path/to/browser` to override the executable.

## Out Of Scope For This MVP

- Arbitrary existing-session attachment beyond the local trusted TV-helper/CDP path
- Arbitrary JavaScript evaluation through the public API
- Browser actions exposed over a non-local network interface
- Replacing the existing `Server3 TV` browser helpers
