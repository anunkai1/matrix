# Server3 SQLite Tooling Target State

Last verified: 2026-02-26T15:47:07+10:00

## Objective
Keep a local SQLite CLI available on Server3 for direct inspection of Telegram bridge canonical session state.

## Current State
- Package: `sqlite3`
- Installed version: `3.45.1-1ubuntu2.5`
- Binary path: `/usr/bin/sqlite3`

## Operational Use
- Canonical state DB path:
  - `/home/architect/.local/state/telegram-architect-bridge/chat_sessions.sqlite3`
- Active state directory expected contents:
  - `chat_sessions.sqlite3`
- Quick validation command:
  - `sqlite3 /home/architect/.local/state/telegram-architect-bridge/chat_sessions.sqlite3 'SELECT COUNT(*) FROM canonical_sessions;'`
