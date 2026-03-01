# Architect Google OAuth Runbook (Full Scope)

## Purpose
Set up Google OAuth for Architect identity (`vladislavsllm26@gmail.com`) with full Gmail + Calendar access scopes.

## Scope
- Gmail scope: `https://mail.google.com/`
- Calendar scope: `https://www.googleapis.com/auth/calendar`

## Prerequisites
- You own/control the Google account.
- You can access Google Cloud Console in browser.
- Server3 repo path: `/home/architect/matrix`

## 1) Create Google Cloud Project
1. Open Google Cloud Console.
2. Create a new project dedicated to Architect identity integration.
3. Enable APIs:
- Gmail API
- Google Calendar API

## 2) Configure OAuth Consent Screen
1. Configure OAuth consent screen in the same project.
2. Set app type to internal (if your org allows) or external.
3. Add required scopes:
- `https://mail.google.com/`
- `https://www.googleapis.com/auth/calendar`
4. Save.

## 3) Create OAuth Client Credentials
1. Create OAuth client ID.
2. Choose client type: `Desktop app`.
3. Download client JSON.
4. Place it on Server3:
- Path: `/home/architect/.config/google/architect/client_secret.json`
- Permissions:
  - directory: `700`
  - file: `600`

## 4) Run Device Authorization Flow on Server3
From repo root:

```bash
cd /home/architect/matrix
python3 ops/google/architect_google_oauth_device.py \
  --client-secret /home/architect/.config/google/architect/client_secret.json \
  --token-out /home/architect/.config/google/architect/oauth_token.json
```

The script prints:
- verification URL
- user code

In browser:
1. Open verification URL.
2. Login as `vladislavsllm26@gmail.com`.
3. Enter user code.
4. Approve requested scopes.

## 5) Verify Gmail + Calendar API Access

```bash
cd /home/architect/matrix
python3 ops/google/architect_google_verify.py \
  --client-secret /home/architect/.config/google/architect/client_secret.json \
  --token-file /home/architect/.config/google/architect/oauth_token.json
```

Expected result:
- `Google API verification succeeded`
- Gmail email/profile fields
- Calendar list count

## 6) Secret Handling Rules
- Never commit `client_secret.json` or token JSON to git.
- Never paste passwords or tokens in chat.
- Rotate credentials if exposure is suspected.

## Troubleshooting
- `invalid_client`: wrong OAuth client JSON/project or deleted client.
- `access_denied`: approval denied in browser.
- no `refresh_token`: revoke existing app grant and re-run flow.
- API `403`: missing enabled API or missing scope on consent screen.
