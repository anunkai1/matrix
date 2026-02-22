# Voucher Automation Resume Handoff

## High-Level Human Summary (Beginner-Friendly)
This project is paused before implementation.
You decided to build a terminal-only Bitrefill voucher bot on Server3 (ETH/USDT on Ethereum mainnet) with strong safety checks, but no code has been written yet.
You tested and then fully rolled back the staker SSH-tunnel RPC approach, so staker is back to safer baseline.
When resuming, use a temporary public RPC first (`https://ethereum-rpc.publicnode.com`) and keep all secrets in `private/` only (never in public GitHub-tracked files).
Main blocker for API-first mode is Bitrefill API credentials (not available yet), so likely start with browser-session-first automation and add API mode later.

## LLM/Codex Handoff Prompt
```md
You are operating in `/home/architect/matrix` on Server3.

Date context:
- Last working session context date: 2026-02-22.
- Resume from current repo state, do not assume prior in-memory context.

Mandatory process rules:
1. Read and follow `ARCHITECT_INSTRUCTION.md` first (authoritative).
2. Read `SERVER3_SUMMARY.md` at session start before planning/editing; open `SERVER3_PROGRESS.md` only when more detail is required.
3. Before any change, print **AI Prompt for Action** with:
   - Objective
   - Scope (IN / OUT)
   - Files to change
   - Commands to run
   - Acceptance checks
   - Rollback
   - Commit plan (messages)
4. Ask for explicit confirmation and WAIT before implementing.
5. For non-exempt changes: commit + push to `origin/main`, then show:
   - `git status`
   - `git show --stat --oneline -1`
   - `git log -1 --oneline`
6. Update `SERVER3_SUMMARY.md` at end of non-exempt work; update `SERVER3_PROGRESS.md` only for detailed archival context.
7. Do not assume missing values. Ask user when required.
8. Keep secrets out of git.
9. Follow minimal-change principle.
10. If risky/irreversible live change is required, ask first.

Project objective:
Implement terminal-only Bitrefill voucher automation on Server3 with automated ETH/USDT payment on Ethereum mainnet, with strict user safety controls.

Decisions already finalized:
1. Network/chain:
- Ethereum mainnet only (`chainId=1`).

2. Payment assets:
- ETH and USDT (ERC-20 on Ethereum mainnet).
- Strict per-command asset selection only (no auto-switch unless explicitly requested).

3. USDT contract:
- Hardcode canonical mainnet USDT:
`0xdAC17F958D2ee523a2206206994597C13D831ec7`

4. Product scope:
- Initial product: Woolworths AU only.
- Any available denomination.

5. Safety/approval rules:
- Mandatory terminal approval gate every order (`APPROVE`).
- On tx/payment failure: stop and ask user what to do.
- Single-order lock required (no concurrent runs).
- Max order limit required: USD-equivalent <= 2000 at quote/approval stage.

6. Auth behavior:
- Support both saved session mode and credential fallback mode.
- If captcha appears: bot should try; if blocked/unresolved, prompt user.

7. Voucher output:
- Save to `private/vouchers/`.
- Full voucher/card+PIN can display in terminal (explicitly approved).
- Full voucher/card+PIN must be excluded from structured logs.

8. Storage:
- Plaintext voucher storage allowed for phase 1 (explicitly approved).

9. Wallet key:
- Raw private key in config/env for phase 1 (explicitly approved).

10. Confirmed local file paths:
- Private env file: `private/voucher-automation.env`
- Bitrefill session file: `private/bitrefill/session.json`
- Bitrefill credential file: `private/bitrefill/credentials.env`

11. Confirmed CLI format:
- `python -m voucher_automation.cli buy --brand woolworths_au --amount <amount> --asset <ETH|USDT>`

Important update on RPC direction:
- Infura account/API not available currently.
- Use temporary public no-account RPC for now.
- Tested working candidate: `https://ethereum-rpc.publicnode.com`
- Tested but not suitable for needed methods: `https://cloudflare-eth.com`

Staker tunnel experiment status (completed and rolled back):
1. Previously tested tunnel worked:
- `127.0.0.1:18545 -> 127.0.0.1:8545` via SSH to staker.

2. Rollback completed:
- Removed UFW allow on staker: `allow from 192.168.0.148 to any port 8545`.
- Verified staker Nethermind RPC still localhost-only (`127.0.0.1:8545`).
- Removed tunnel key entry from staker `~/.ssh/authorized_keys`.
- Stopped tunnel process on Server3.
- Verified `127.0.0.1:18545` is no longer reachable.
- Deleted Server3 tunnel key files:
  - `/home/architect/.ssh/id_ed25519_nuc_tunnel`
  - `/home/architect/.ssh/id_ed25519_nuc_tunnel.pub`

Current implementation status:
- Voucher automation code/files: not created yet.
- No voucher feature commit/push has been made yet.
- Last session did not change repo files for voucher work.

Known open decisions/questions before deep implementation:
1. Bitrefill integration mode to start with:
- Browser-session-first (likely immediate path), then API mode later when credentials are available.
2. Exact env var names/shape for wallet secret + RPC in `private/voucher-automation.env`.
3. Preferred structured log format (jsonl vs plain lines) for voucher automation runtime logs.

Resume sequence requested:
1. Create env template/docs/runbook for voucher automation (no secrets).
2. Implement CLI + guardrails first.
3. Implement Bitrefill client path (session + credential fallback + captcha prompt path).
4. Implement ETH/USDT sender (chainId=1 only, USDT fixed address).
5. Implement voucher storage/output and log redaction.
6. Add tests/validations.
7. Commit + push + update `SERVER3_PROGRESS.md`.

Security reminders for public GitHub repo:
- Never commit private keys, tokens, API secrets, voucher card/PIN, or full credential dumps.
- Keep all sensitive runtime material under `private/` or live system env only.
- Ensure structured logs redact secrets and voucher sensitive fields.
```
