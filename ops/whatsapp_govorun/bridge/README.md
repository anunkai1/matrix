# WhatsApp Govorun Bridge

Matrix-managed runtime component that links WhatsApp messages to Codex execution.

## Behavior
- Group chats: responds only when message starts with `WA_TRIGGER` (default `@govorun`).
- DMs: responds to all messages when `WA_DM_ALWAYS_RESPOND=true`.
- Runs Codex with model `gpt-5-codex-mini` and reasoning effort `medium` by default.
- Fetches latest WhatsApp Web version at startup/auth to avoid stale-version auth failures.

## Local run

```bash
cd ops/whatsapp_govorun/bridge
npm install
cp .env.example .env
npm run auth
npm run start
```

## Auth modes
- QR mode (default): keep `WA_PAIRING_PHONE` empty and run `npm run auth`.
- Pairing code mode (optional): set `WA_PAIRING_PHONE` (digits only, country code included) and run `npm run auth`.
  The script will print a pairing code for WhatsApp Linked Devices.

## Runtime paths (recommended)
- App: `/home/wa-govorun/whatsapp-govorun/app`
- State: `/home/wa-govorun/whatsapp-govorun/state`

## Security note
`CODEX_FULL_ACCESS=true` runs Codex without sandbox/approval prompts inside the runtime user boundary.
Use only with a non-sudo service user.
