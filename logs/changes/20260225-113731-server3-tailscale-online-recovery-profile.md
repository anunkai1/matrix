# Change Record - Server3 Tailscale Online Recovery Profile

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-25T11:37:31+10:00
- Operator: Codex (Architect)
- Scope: Live recovery of Server3 Tailscale online state under NordVPN, plus repo profile codification

## Objective
- Recover `server3` visibility in Tailscale dashboard (`Self.Online=true`) while keeping NordVPN connected.
- Persist a reproducible coexistence profile in repo scripts/docs.

## Live Changes Applied
1. Set NordVPN coexistence runtime to online-recovery:
   - `killswitch off`
   - `firewall off`
   - `autoconnect on` (kept)
   - `lan-discovery off` (kept)
   - allowlist ports retained: `443/tcp`, `3478/udp`, `41641/udp`
2. Restarted Tailscale daemon and reasserted node session:
   - `systemctl restart tailscaled`
   - `tailscale up --qr=false`
3. Verified control-plane reachability and node online state.

## Verification Evidence
- Tailscale state (`tailscale status --json`):
  - `BackendState: Running`
  - `Self.Online: true`
  - `Health: []`
- Tailscale network checks (`tailscale netcheck`):
  - `UDP: true`
  - `Nearest DERP: Sydney`
- NordVPN policy (`nordvpn settings`):
  - `Firewall: disabled`
  - `Kill Switch: disabled`
  - `Auto-connect: enabled`
  - `LAN Discovery: disabled`
  - allowlisted ports/subnet present
- NordVPN connection (`nordvpn status`):
  - `Status: Connected`
  - `Country: Australia`

## Repo Artifacts Updated
- `ops/nordvpn/apply_server3_au.sh` (added `--profile strict|online-recovery`, default online-recovery)
- `docs/nordvpn-server3.md`
- `docs/tailscale-server3.md`
- `infra/system/nordvpn/server3.nordvpn.target-state.md`
- `infra/system/tailscale/server3.tailscale.target-state.md`

## Security Notes
- Online-recovery profile improves Tailscale control-plane reliability and dashboard visibility.
- Tradeoff: NordVPN kill switch and firewall are disabled in this profile.
- Strict mode remains available via:
  - `bash ops/nordvpn/apply_server3_au.sh --profile strict`
