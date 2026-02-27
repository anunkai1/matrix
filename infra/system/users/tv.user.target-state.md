# Server3 User Target State - tv

## Objective
Dedicated local desktop user for TV session runtime.

## Desired State
- Username: `tv`
- Home: `/home/tv`
- Shell: `/bin/bash`
- Primary group: `tv`
- Supplementary groups: `audio`, `video`
- Password: locked (`passwd -S tv` => `L`)
- Sudo: not a member of `sudo`

## Provisioning Source
- `ops/tv-desktop/apply_server3.sh`

## Verification Commands
```bash
id tv
sudo passwd -S tv
```
