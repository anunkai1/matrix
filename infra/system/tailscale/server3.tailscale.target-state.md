# Server3 Tailscale Target State

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-25T10:47:28+10:00
- Host OS: Ubuntu 24.04.4 LTS (noble)

## Installed Packages
- `tailscale`: `1.94.2`
- `tailscale-archive-keyring`: `1.35.181`

## Live Paths / Components
- `/etc/apt/sources.list.d/tailscale.list`
- `/usr/share/keyrings/tailscale-archive-keyring.gpg`
- `/etc/default/tailscaled`
- `tailscaled.service` (package-managed systemd unit)
- `/var/lib/tailscale/tailscaled.state`

## systemd State
- `tailscaled.service`: enabled + active

## Target Runtime State
- Backend state: `Running`
- Node hostname: `server3`
- Tailnet: `spets1@gmail.com` (`tailfc147.ts.net`)
- Node DNS name: `server3.tailfc147.ts.net`
- Tailscale IPv4: `100.76.116.84`
- Tailscale IPv6: `fd7a:115c:a1e0::f337:7454`
- Exit node mode: disabled
- Advertised routes: none

## Compatibility Note (NordVPN)
- NordVPN coexistence profile keeps these allowlist ports:
  - `443/tcp`
  - `3478/udp`
  - `41641/udp`
- Server3 uses NordVPN `online-recovery` mode to keep Tailscale node online:
  - `killswitch: off`
  - `firewall: off`
- Recovery workflow (if dashboard shows offline):
  - `bash ops/nordvpn/apply_server3_au.sh --profile online-recovery`
  - `sudo systemctl restart tailscaled`
  - `sudo tailscale up --qr=false`
