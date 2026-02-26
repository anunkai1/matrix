# Live Change Record — ESPHome/Xiaomi BLE Recovery Attempt

- Timestamp (UTC): 2026-02-19 07:39
- Operator: Codex (Architect)
- Scope: Runtime Home Assistant/ESPHome recovery operations only (no repo/live config file edits)

## Trigger
- User reported Xiaomi `LYWSD03MMC` temperature/humidity entities became unavailable immediately after ESPHome add-on update from `2026.1.5` to `2026.2.0`.

## Actions Executed
1. Verified outage pattern:
   - All four Xiaomi temperature entities in HA were `unavailable`.
   - Shared transition window observed around `2026-02-19 06:03:03 UTC` (later state refresh retained unavailable state at `2026-02-19 07:11:22 UTC`).
2. Attempted HA config entry reload via WS service calls (`homeassistant.reload_config_entry`) for:
   - `esphome` entry `01KGH94D64PMBH9AHPP6N5YGNT`
   - `bluetooth` entry `01KGHGT7VWRMW5MJCM0RJ18GYG`
   - Four `xiaomi_ble` entries (`01KGK34...`, `01KGKD...`, `01KGKDR...`, `01KGKF...`)
   - Result: blocked (`home_assistant_error: Unauthorized`).
3. Restarted ESPHome add-on via WS service call:
   - `hassio.addon_restart` with addon slug `5c53de3b_esphome`
   - Result: accepted (`success: true`).
4. Monitored Xiaomi entity states for 6 minutes post-restart.
   - Result: no recovery; all watched entities remained `unavailable`.
5. Attempted HA core restart path:
   - `homeassistant.restart`
   - Result: blocked (`home_assistant_error: Unauthorized`).

## Key Observations
- ESP32 BLE proxy host remained reachable on LAN (`192.168.0.142`) with ESPHome API port `6053` open.
- Browser access to `http://192.168.0.142` fails by design (HTTP port closed), which does not by itself indicate proxy offline.
- Live token used in this session has partial permissions: can read HA state and restart add-ons via `hassio`, but cannot execute `homeassistant.reload_config_entry` or `homeassistant.restart`.

## Current Status
- Xiaomi BLE sensors remain unavailable after add-on restart.
- Recovery is blocked from deeper integration reload/core restart through current token permissions.

## Recommended Next Step
- Perform Supervisor/UI-admin action to roll back ESPHome add-on from `2026.2.0` to `2026.1.5` (or run HA core restart + Bluetooth integration reload with full admin privileges), then re-verify Xiaomi entities.
