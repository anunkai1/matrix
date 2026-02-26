# Change Record - Server3 NordVPN/Tailscale Coexistence Fix

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-25T11:13:46+10:00
- Operator: Codex (Architect)
- Scope: Live NordVPN allowlist tuning and Tailscale coexistence validation on Server3

## Objective
- Keep NordVPN protections enabled (`Firewall` + `Kill Switch`) while restoring healthy Tailscale operation.
- Encode the coexistence policy into repo-tracked scripts/docs.

## Live Changes Applied
1. Added NordVPN allowlist ports:
   - `443/tcp`
   - `3478/udp`
   - `41641/udp`
2. Revalidated runtime while NordVPN remained connected to AU endpoint.
3. Performed controlled restart tests and compatibility recovery tests for `tailscaled`.

## Key Findings
- With allowlist ports configured, Tailscale can run healthy with NordVPN protections enabled.
- After `tailscaled` restart, daemon can remain in `NoState` under full NordVPN protections.
- Recovery is reliable with a short compatibility window:
  - `nordvpn set killswitch off`
  - `nordvpn set firewall off`
  - `tailscale up`
  - restore `firewall on` + `killswitch on`

## Verification Evidence
- NordVPN final policy:
  - `Firewall: enabled`
  - `Kill Switch: enabled`
  - `Auto-connect: enabled`
  - `LAN Discovery: disabled`
  - Allowlisted ports visible in `nordvpn settings`:
    - `443 (TCP)`, `3478 (UDP)`, `41641 (UDP)`
- Tailscale final state:
  - `BackendState: Running`
  - `Health: []`
  - Tailscale IPv4: `100.76.116.84`
- Status nuance:
  - `tailscale status` can still render `server3` as `offline` while direct tailnet peer pings succeed.
- Peer reachability:
  - `tailscale ping homeassistant` => pong
  - `tailscale ping staker2` => pong
  - `tailscale ping nuc202305` => pong

## Security Notes
- No credentials or auth keys were stored in repo artifacts.
- NordVPN protections were restored to enabled state after compatibility-window actions.
