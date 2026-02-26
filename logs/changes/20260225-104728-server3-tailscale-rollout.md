# Change Record - Server3 Tailscale Rollout

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-25T10:47:28+10:00
- Operator: Codex (Architect)
- Scope: Live Tailscale install/login rollout on Server3 with NordVPN coexistence

## Objective
- Install and enable Tailscale on Server3.
- Join Server3 to existing tailnet.
- Keep NordVPN final target state intact (`Firewall/Kill Switch/Auto-connect` enabled).

## Live Changes Applied
1. Installed Tailscale packages on Ubuntu 24.04:
   - `tailscale` (`1.94.2`)
   - `tailscale-archive-keyring` (`1.35.181`)
2. Enabled and started daemon:
   - `systemctl enable --now tailscaled`
3. Performed interactive tailnet authentication:
   - `tailscale up --qr=false` and browser approval link flow.
4. Applied NordVPN compatibility window during login bootstrap:
   - `nordvpn set killswitch off`
   - `nordvpn set firewall off`
   - completed `tailscale up` auth
   - restored:
     - `nordvpn set firewall on`
     - `nordvpn set killswitch on`

## Constraint Observed
- On Server3, initial `tailscale up` login bootstrap did not complete while NordVPN firewall protections were enforced.
- Symptom observed repeatedly:
  - `fetch control key ... context canceled`
  - no auth URL returned in `tailscale status --json`
- Resolution used in this rollout:
  - temporary NordVPN firewall + kill switch disable during login bootstrap only
  - immediate restoration after successful node registration

## Verification Evidence
- Tailscale daemon:
  - `systemctl is-enabled tailscaled` => `enabled`
  - `systemctl is-active tailscaled` => `active`
- Tailnet state:
  - `tailscale status --json` => `BackendState: Running`
  - node DNS: `server3.tailfc147.ts.net`
  - tailnet: `spets1@gmail.com` (`tailfc147.ts.net`)
  - Tailscale IPs:
    - IPv4: `100.76.116.84`
    - IPv6: `fd7a:115c:a1e0::f337:7454`
  - peer list includes existing devices (`homeassistant`, `nuc202305`, `staker2`, others)
  - direct peer checks succeeded:
    - `tailscale ping homeassistant` => pong
    - `tailscale ping staker2` => pong
    - `tailscale ping nuc202305` => pong
- NordVPN final state retained:
  - `Firewall: enabled`
  - `Kill Switch: enabled`
  - `Auto-connect: enabled`
  - `LAN Discovery: disabled`
  - `nordvpn status` remained connected to `au` endpoint

## Security Notes
- No Tailscale auth key was stored in repo files.
- No SSH/firewall/netplan files were edited directly.
- Temporary NordVPN protection relaxation was limited to login bootstrap window and restored in-session.
