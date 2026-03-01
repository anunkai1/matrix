# Change Log - Telegram Phase A Plugin Seams

Timestamp: 2026-03-01T10:07:09+10:00
Timezone: Australia/Brisbane

## Objective
- Introduce safe plugin seams for channels and engines with zero runtime behavior change.

## Scope
- In scope:
  - `src/telegram_bridge/channel_adapter.py`
  - `src/telegram_bridge/engine_adapter.py`
  - `src/telegram_bridge/plugin_registry.py`
  - `src/telegram_bridge/handlers.py`
  - `src/telegram_bridge/main.py`
  - `tests/telegram_bridge/test_bridge_core.py`
  - `SERVER3_SUMMARY.md`
  - this `logs/changes` record
- Out of scope:
  - enabling non-Telegram channels at runtime
  - enabling non-Codex engine providers at runtime
  - WhatsApp/Discord/Slack/Signal rollout work

## Changes Made
1. Added channel adapter seam:
   - new `ChannelAdapter` protocol and `TelegramChannelAdapter` wrapper.
   - maps existing Telegram client behavior to a channel plugin surface.
2. Added engine adapter seam:
   - new `EngineAdapter` protocol and `CodexEngineAdapter` wrapper.
   - wraps existing `run_executor` path without changing command behavior.
3. Added plugin registry:
   - new `PluginRegistry` with channel/engine registration and builder methods.
   - default registry registers `telegram` channel and `codex` engine.
4. Wired bridge startup to registry defaults:
   - `run_bridge` now builds channel + engine through registry and injects them into update handling.
5. Updated handler internals to adapter interfaces:
   - replaced direct `run_executor` call with `engine.run(...)`.
   - kept all execution, retry, media send, and command logic unchanged.
6. Expanded tests:
   - added coverage for default plugin registry exposure/build behavior.
   - full suite and smoke test revalidated.

## Validation
- Unit tests:
  - `python3 -m unittest discover -s tests -p 'test_*.py'`
  - Result: `Ran 88 tests ... OK`
- Smoke test:
  - `bash src/telegram_bridge/smoke_test.sh`
  - Result: `self-test: ok`, `smoke-test: ok`

## Notes
- Runtime defaults remain Telegram channel + Codex engine only.
- This is an architecture seam for future pluginization, not a channel/provider feature rollout.
