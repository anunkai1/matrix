# 2026-02-18 13:41:20 UTC — Telegram Voice GPU Runtime Enablement

## Objective
- Enable GPU-backed Whisper transcription for Telegram voice flow on Server3 and keep CPU fallback for resilience.

## Live Changes Applied
- Installed NVIDIA runtime stack on Server3:
  - `nvidia-driver-590-open` (plus dependencies)
- Installed CUDA BLAS runtime libraries required by faster-whisper:
  - `libcublas12`
  - `libcublaslt12`
- Updated live bridge env in `/etc/default/telegram-architect-bridge`:
  - `TELEGRAM_VOICE_WHISPER_DEVICE=cuda`
  - `TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE=float16`
  - `TELEGRAM_VOICE_WHISPER_FALLBACK_DEVICE=cpu`
  - `TELEGRAM_VOICE_WHISPER_FALLBACK_COMPUTE_TYPE=int8`
- Preserved pre-change env backup:
  - `/etc/default/telegram-architect-bridge.bak-20260218-132203`

## Verification
- Host reboot completed and new boot timestamp observed:
  - `2026-02-18 13:30:20`
- NVIDIA runtime active:
  - `nvidia-smi` reports `NVIDIA GeForce GTX 1650`
  - driver `590.48.01`, CUDA `13.1`
- Bridge service active after reboot:
  - `telegram-architect-bridge.service` active/running
  - `ExecMainStartTimestamp=Wed 2026-02-18 13:39:33 UTC`
- Bridge runtime env verification (running process):
  - `TELEGRAM_VOICE_WHISPER_DEVICE=cuda`
  - `TELEGRAM_VOICE_WHISPER_COMPUTE_TYPE=float16`
  - fallback vars present
- Local transcription benchmark sample (20s silence `.ogg`):
  - CPU (`base/int8`): `0:01.51`
  - CUDA (`base/float16`): `0:01.62`
  - Note: silence sample is not representative of real speech complexity.

## Repo Traceability
- Mirrored live non-secret voice env keys in:
  - `infra/env/telegram-architect-bridge.server3.redacted.env`
