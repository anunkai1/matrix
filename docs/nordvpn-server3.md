# NordVPN Rollout Runbook (Server3)

## Scope
- Host: Server3
- VPN target: Australia (`au`)
- Required LAN subnet: `192.168.0.0/24`
- Custom DNS target: `1.1.1.1`, `1.0.0.1` (default in apply script)
- Default coexistence profile: `online-recovery` (`autoconnect on`, `killswitch off`, `firewall off`)

## Constraint
- NordVPN CLI does not allow private subnet allowlist when `LAN Discovery` is enabled.
- This runbook uses:
  - `LAN Discovery: off`
  - `Allowlisted subnet: 192.168.0.0/24`

## Tailscale Coexistence
- Server3 uses additional NordVPN allowlisted ports so Tailscale control/data paths can coexist:
  - `443/tcp`
  - `3478/udp`
  - `41641/udp`
- `ops/nordvpn/apply_server3_au.sh` enforces these allowlist entries and supports profiles:
  - `online-recovery` (default): keep node online in Tailscale dashboard.
  - `strict`: tighter NordVPN protections (`killswitch on`, `firewall on`) with higher risk of Tailscale control-plane degradation.
  - default custom DNS: `1.1.1.1 1.0.0.1` (override with `--dns "<ip1 ip2>"` or disable via `--dns off`)
- If `server3` appears offline in Tailscale under strict mode, recover with:
```bash
bash ops/nordvpn/apply_server3_au.sh --profile online-recovery
sudo tailscale up --qr=false
```

## Baseline Checks
```bash
ip -4 route
curl -4 -fsS https://ifconfig.co/ip
systemctl is-active telegram-architect-bridge.service
ping -c 3 -W 2 192.168.0.1
```

## Install
```bash
curl -fsS https://downloads.nordcdn.com/apps/linux/install.sh -o /tmp/nordvpn-install.sh
sudo sh /tmp/nordvpn-install.sh
sudo apt-get install -y nordvpn
```

## Login (Token-Based)
```bash
read -rsp 'Paste NordVPN token: ' NORD_TOKEN; echo
sudo nordvpn login --token "$NORD_TOKEN"
unset NORD_TOKEN
```

## Apply Target State
```bash
bash ops/nordvpn/apply_server3_au.sh
```

## Apply Strict Variant (Optional)
```bash
bash ops/nordvpn/apply_server3_au.sh --profile strict
```

## Apply Without Custom DNS (Optional)
```bash
bash ops/nordvpn/apply_server3_au.sh --dns off
```

## Verify
```bash
sudo nordvpn status
sudo nordvpn settings
sudo tailscale status
resolvectl status
curl -4 -fsS https://ifconfig.co/ip
ip -4 route
ping -c 3 -W 2 192.168.0.1
systemctl is-active telegram-architect-bridge.service
```

## Rollback
```bash
bash ops/nordvpn/rollback_server3.sh
```

## Deep Rollback (Optional)
```bash
sudo apt-get remove -y nordvpn
sudo rm -f /etc/apt/sources.list.d/nordvpn.list
sudo apt-get update
```
