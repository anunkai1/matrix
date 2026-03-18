# Server3 User Target State - browser_brain

## Objective

Dedicated local runtime user for the Server3 browser-control service.

## Desired State

- Username: `browser_brain`
- Home: `/home/browser_brain`
- Shell: `/bin/bash`
- Primary group: `browser_brain`
- Password: locked or otherwise not used for interactive login
- Sudo: not a member of `sudo`

## Provisioning Source

- `ops/browser_brain/setup_runtime_user.sh`

## Verification Commands

```bash
id browser_brain
sudo passwd -S browser_brain
```
