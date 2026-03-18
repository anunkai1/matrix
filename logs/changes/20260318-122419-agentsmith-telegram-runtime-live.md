# AgentSmith Telegram Runtime Live

Time: 2026-03-18 12:24:19 AEST

## Objective
Provision a new isolated Telegram bot runtime for `AgentSmith` using the shared bridge core.

## Repo Changes
- Added `infra/systemd/telegram-agentsmith-bridge.service`.
- Added `infra/env/telegram-agentsmith-bridge.env.example`.
- Added `infra/runtime_personas/agentsmith.AGENTS.md`.
- Added `infra/system/sudoers/agentsmith-telegram-bridge`.
- Added `infra/codex/home/agentsmith/.codex/config.toml`.
- Updated restart allowlist, restore/verify coverage, runtime manifest, bootstrap user map, and `SERVER3_SUMMARY.md`.

## Live Changes
- Created Linux user `agentsmith` with isolated runtime root `/home/agentsmith/agentsmithbot`.
- Linked `/home/agentsmith/agentsmithbot/src` to the shared bridge core under `/home/architect/matrix/src`.
- Installed live env file `/etc/default/telegram-agentsmith-bridge`.
- Installed sudoers rule `/etc/sudoers.d/agentsmith-telegram-bridge`.
- Installed and enabled `telegram-agentsmith-bridge.service`.
- Seeded `/home/agentsmith/.codex` with auth/config so the new runtime can execute Codex.
- Allowed private Telegram chat `211761499` only.

## Verification
- `systemctl status telegram-agentsmith-bridge.service` showed `active (running)`.
- `journalctl -u telegram-agentsmith-bridge.service` showed `Bridge started. Allowed chats=[211761499]`.
- `python3 ops/server3_runtime_status.py` reported `AgentSmith` at expected `active` state.
- Bot API outbound proof succeeded with `AgentSmith runtime is live on Server3.` to chat `211761499`.

## Notes
- `python3 ops/server3_runtime_status.py` still reports the unrelated pre-existing `Mavali ETH` runtime warning; AgentSmith itself is healthy.
