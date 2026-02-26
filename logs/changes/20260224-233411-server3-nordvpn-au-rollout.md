# Change Record - Server3 NordVPN AU Rollout

- Timestamp (Australia/Brisbane ISO-8601): 2026-02-24T23:34:11+10:00
- Operator: Codex (Architect)
- Scope: Live NordVPN install/config rollout on Server3 with rollback verification

## Objective
- Deploy NordVPN on Server3 with AU target and safe LAN retention for `192.168.0.0/24`.
- Enable `autoconnect` and `killswitch` only after successful verification.

## Baseline Evidence (Before Install/Connect)
- `ip -4 route`:
  - `default via 192.168.0.1 dev eno2 ... src 192.168.0.148`
  - `192.168.0.0/24 dev eno2 ... src 192.168.0.148`
- Public IP:
  - `124.158.96.26`
- Bridge health:
  - `systemctl is-active telegram-architect-bridge.service` => `active`
- LAN reachability:
  - `ping -c 3 -W 2 192.168.0.1` => `3/3 received, 0% packet loss`

## Commands Executed (High-Level)
1. Install:
   - `curl -fsS https://downloads.nordcdn.com/apps/linux/install.sh -o /tmp/nordvpn-install.sh`
   - `sudo sh /tmp/nordvpn-install.sh`
   - `sudo apt-get install -y nordvpn`
2. Login:
   - `read -rsp 'Paste NordVPN token: ' NORD_TOKEN; echo; sudo nordvpn login --token "$NORD_TOKEN"; unset NORD_TOKEN`
3. Initial connect + verification:
   - `sudo nordvpn connect au`
   - `sudo nordvpn status`
   - `curl -4 -fsS https://ifconfig.co/ip`
   - `ip -4 route`
   - `ping -c 3 -W 2 192.168.0.1`
   - `systemctl is-active telegram-architect-bridge.service`
4. Persistence:
   - `sudo nordvpn set autoconnect on`
   - `sudo nordvpn set killswitch on`
5. Subnet whitelist mode (constraint handling):
   - `sudo nordvpn set lan-discovery off`
   - `sudo nordvpn allowlist add subnet 192.168.0.0/24`
6. Rollback verification (executed, then restored desired state):
   - `sudo nordvpn set autoconnect off`
   - `sudo nordvpn set killswitch off`
   - `sudo nordvpn disconnect`
   - Validate public IP, LAN ping, bridge service
   - Re-apply target state:
     - `sudo nordvpn connect au`
     - `sudo nordvpn set autoconnect on`
     - `sudo nordvpn set killswitch on`

## Constraint Observed
- NordVPN CLI rejects private subnet allowlisting while `LAN Discovery` is enabled.
- Error observed:
  - `Allowlisting a private subnet is not available while local network discovery is turned on.`
- Final selected mode:
  - `LAN Discovery: disabled`
  - `Allowlisted subnets: 192.168.0.0/24`

## Verification Evidence
- AU connection verified:
  - `Status: Connected`
  - `Country: Australia`
  - server examples: `Australia #785`, later `Australia #680`
- Public IP changed after VPN connect:
  - baseline: `124.158.96.26`
  - connected checks: `45.248.79.125`, final `116.90.72.94`
- LAN access preserved on VPN:
  - `ping -c 3 -W 2 192.168.0.1` => `3/3 received, 0% packet loss`
- Bridge service remained healthy:
  - `systemctl is-active telegram-architect-bridge.service` => `active`
- Final policy settings:
  - `Technology: NORDLYNX`
  - `Auto-connect: enabled`
  - `Kill Switch: enabled`
  - `LAN Discovery: disabled`
  - `Allowlisted subnets: 192.168.0.0/24`

## Rollback Commands (Verified)
```bash
sudo nordvpn set autoconnect off
sudo nordvpn set killswitch off
sudo nordvpn disconnect
```

## Security Notes
- Token-based login used interactively only.
- Token not written to repo files or logs.
