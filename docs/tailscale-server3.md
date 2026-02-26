# Tailscale Rollout Runbook (Server3)

## Scope
- Host: Server3
- Target: Join existing tailnet and keep `tailscaled` persistent via systemd
- Validated state: Tailscale registered and reachable while NordVPN remains connected

## NordVPN Coexistence Policy
- Keep these NordVPN allowlist ports configured:
  - `443/tcp`
  - `3478/udp`
  - `41641/udp`
- These are enforced by:
  - `ops/tailscale/apply_server3.sh`
  - `ops/nordvpn/apply_server3_au.sh`
- Preferred Server3 mode to keep dashboard visibility is NordVPN `online-recovery` profile:
```bash
bash ops/nordvpn/apply_server3_au.sh --profile online-recovery
```
- If `server3` still shows offline in Tailscale, run:
```bash
sudo systemctl restart tailscaled
sudo tailscale up --qr=false
```

## Baseline Checks
```bash
cat /etc/os-release
systemctl is-active tailscaled 2>/dev/null || true
tailscale status 2>/dev/null || true
```

## Install
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo systemctl enable --now tailscaled
```

## Login

### Interactive (Browser Approval)
```bash
# On this host, NordVPN firewall + kill switch can block Tailscale control-plane bootstrap.
sudo nordvpn set killswitch off
sudo nordvpn set firewall off

sudo tailscale up --qr=false

# After approval completes:
sudo nordvpn set firewall on
sudo nordvpn set killswitch on
```

### Auth-Key (Minimal Manual Involvement)
```bash
read -rsp 'Paste Tailscale auth key: ' TS_AUTH_KEY; echo
bash ops/tailscale/apply_server3.sh --auth-key "$TS_AUTH_KEY"
unset TS_AUTH_KEY
```

## Verify
```bash
sudo systemctl is-enabled tailscaled
sudo systemctl is-active tailscaled
sudo tailscale ip -4
sudo tailscale status
sudo nordvpn status
sudo nordvpn settings
sudo tailscale ping -c 3 homeassistant
```

## Rollback
```bash
bash ops/tailscale/rollback_server3.sh
```

## Deep Rollback (Optional)
```bash
bash ops/tailscale/rollback_server3.sh --remove-packages
```
