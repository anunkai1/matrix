# Server3 NordVPN Target State (Redacted)

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-25T11:36:27+10:00
- Scope: Live NordVPN + Tailscale coexistence runtime configuration on Server3

## Live Paths / Components
- `/etc/apt/sources.list.d/nordvpn.list`
- `nordvpn` package (CLI + daemon)
- `nordvpnd.service`

## Target Runtime State
- Technology: `NORDLYNX`
- Country target: `au`
- Auto-connect: `enabled`
- Kill Switch: `disabled` (online-recovery coexistence profile)
- LAN Discovery: `disabled`
- Firewall: `disabled` (online-recovery coexistence profile)
- Allowlisted subnets:
  - `192.168.0.0/24`
- Allowlisted ports:
  - `443/tcp` (Tailscale control-plane HTTPS)
  - `3478/udp` (STUN/NAT traversal)
  - `41641/udp` (Tailscale local UDP endpoint)

## Constraint Note
- NordVPN Linux CLI does not permit a private subnet allowlist while `LAN Discovery` is enabled.
- To satisfy explicit subnet whitelist input, this rollout keeps `LAN Discovery` disabled and uses `allowlist subnet 192.168.0.0/24`.
- Server3 keeps an online-recovery coexistence profile by default to retain Tailscale control-plane reachability.
- Strict mode remains available via `bash ops/nordvpn/apply_server3_au.sh --profile strict`.
