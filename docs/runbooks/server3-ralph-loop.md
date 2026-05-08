# Server3 Ralph Loop

`Ralph` means `Reliability, Availability, Latency, Price, Health`.

Purpose:
- continuously inspect live Architect bridge telemetry
- rank the highest-value operational optimization target
- refresh a machine-readable backlog plus a human-readable latest report

Scope:
- reads live bridge/system telemetry
- writes ranked outputs under `RALPH_LOOP_STATE_DIR`
- does not edit code or deploy changes by itself

Primary files:
- loop script: `ops/ralph_loop/ralph_loop.py`
- latest report: `/var/lib/server3-ralph-loop/latest.md`
- latest backlog: `/var/lib/server3-ralph-loop/optimization_backlog.json`
- history: `/var/lib/server3-ralph-loop/history.jsonl`

Commands:
- run once: `python3 /home/architect/matrix/ops/ralph_loop/ralph_loop.py collect`
- install timer: `bash /home/architect/matrix/ops/ralph_loop/install_systemd.sh apply`
- remove timer: `bash /home/architect/matrix/ops/ralph_loop/install_systemd.sh rollback`

Default cadence:
- `server3-ralph-loop.timer` runs hourly with a small randomized delay

Current intent:
- keep the next optimization target fresh without owner prompting
- feed later autonomous engineering passes with real operational evidence instead of guesswork
