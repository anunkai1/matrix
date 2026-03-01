# Architect Google OAuth Target State (Redacted)

- Timestamp (Australia/Brisbane ISO-8601): 2026-03-01T15:55:24+10:00
- Identity: `vladislavsllm26@gmail.com`
- OAuth model: Device authorization flow + refresh token

## Scopes (Full)
- `https://mail.google.com/`
- `https://www.googleapis.com/auth/calendar`

## Local Secret Paths (Server3)
- Client secret JSON: `/home/architect/.config/google/architect/client_secret.json`
- Token JSON: `/home/architect/.config/google/architect/oauth_token.json`

## Operational Scripts
- OAuth device flow: `ops/google/architect_google_oauth_device.py`
- API verification: `ops/google/architect_google_verify.py`

## Validation Targets
- Device flow script returns token payload with `refresh_token`.
- Verify script outputs:
  - Gmail email/profile info
  - Calendar list count

## Notes
- Secret material is local-only and never committed.
- OAuth consent and account login are human-in-the-loop steps.
