# Change Log - Architect Google OAuth Bootstrap (Full Scope)

Timestamp: 2026-03-01T15:55:24+10:00
Timezone: Australia/Brisbane

## Objective
Prepare end-to-end Server3 tooling for Architect Google OAuth (full Gmail + Calendar scopes), leaving only the human Google consent/login step.

## Scope
- In scope:
  - OAuth device-flow script
  - Gmail/Calendar verification script
  - env template and target-state docs
  - setup runbook and summary update
- Out of scope:
  - creating Google account itself
  - Google Cloud console clicks (project/API/consent/client creation)
  - storing secrets in git

## Changes Made
1. Added OAuth device-flow script:
   - `ops/google/architect_google_oauth_device.py`
   - Requests scopes:
     - `https://mail.google.com/`
     - `https://www.googleapis.com/auth/calendar`
   - Writes token JSON to local secret path with secure file mode.
2. Added verification script:
   - `ops/google/architect_google_verify.py`
   - Refreshes access token and validates:
     - Gmail profile endpoint
     - Calendar list endpoint
3. Added env template:
   - `infra/env/google-architect-oauth.env.example`
4. Added target-state doc:
   - `infra/system/google/architect-google-oauth.target-state.redacted.md`
5. Added runbook:
   - `docs/runbooks/architect-google-oauth.md`

## Validation
- Script syntax/help checks:
  - `python3 ops/google/architect_google_oauth_device.py --help`
  - `python3 ops/google/architect_google_verify.py --help`
- Both commands return usage output successfully.

## Notes
- No Google secrets were committed.
- Live OAuth token issuance is pending user completion of Google Cloud + browser consent step.
