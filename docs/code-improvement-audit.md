# Server3 Code Improvement Audit

Date: 2026-05-01  
Workspace: `/home/architect/matrix`

## Purpose

This document consolidates:

- validated findings from direct code inspection
- the useful parts of the earlier LLM audit
- corrections to the weak or unsafe parts of that audit
- a concrete refactor plan with phases, target files, and safest-first execution order

This is not a generic clean-code wishlist. The goal is to improve maintainability, reduce duplication, simplify operational behavior, and lower regression risk in the live Server3 bridge runtime.

## Executive Summary

No critical correctness bug jumped out in this audit pass. The main debt is structural.

The highest-value problems are:

1. duplicated state/session models and mirrored persistence paths
2. monolithic orchestration in `handlers.py` and `main.py`
3. repeated whole-file JSON rewrites on small state changes
4. oversized config loading and defensive config access patterns
5. overloaded engine adapters, especially Pi

The strongest improvement is not shaving lines. It is collapsing parallel implementations of the same concepts:

- session state
- state persistence
- command routing
- engine transport logic
- config resolution

## Validated Findings

### 1. State model duplication is the biggest structural problem

The bridge currently supports both legacy and canonical session/state flows, and many functions branch between them.

Examples:

- `src/telegram_bridge/session_manager.py`
  - `_ensure_chat_worker_session_canonical()`
  - `_ensure_chat_worker_session_legacy()`
- `src/telegram_bridge/state_store.py`
  - `set_thread_id()`
  - `clear_thread_id()`
  - `clear_worker_session()`
  - `mark_in_flight_request()`
  - `clear_in_flight_request()`
  - `pop_interrupted_requests()`

Impact:

- same business rules implemented twice
- more testing burden
- more branches for every state mutation
- higher regression risk when evolving worker/session behavior

Recommendation:

- make canonical session state the single primary runtime model
- treat legacy JSON state as compatibility import/export only
- remove legacy-first mutation paths once canonical is fully authoritative

### 2. Small state mutations trigger large persistence work

The current state layer frequently rewrites entire JSON state files for small updates, and canonical mode may also mirror changes back into legacy structures.

Examples:

- `src/telegram_bridge/state_store.py`
  - `persist_chat_threads()`
  - `persist_worker_sessions()`
  - `persist_in_flight_requests()`
  - `persist_canonical_sessions()`
  - `mirror_legacy_from_canonical()`

Impact:

- unnecessary I/O
- more chances for state drift or write-path bugs
- more code around persistence than the feature logic itself

Recommendation:

- use canonical SQLite as the operational source of truth
- reduce JSON files to bootstrap/export/debug mirrors only if still needed
- batch or debounce non-critical state writes where safe

### 3. `handlers.py` is carrying too much

`src/telegram_bridge/handlers.py` is about 7,000 lines and contains large functions such as:

- `handle_update()`
- `execute_prompt_with_retry()`
- `prepare_prompt_input()`
- `process_prompt()`
- `send_executor_output()`
- `handle_pi_command()`
- `process_youtube_request()`
- `handle_callback_query()`

It currently owns:

- command dispatch
- callback routing
- progress reporting
- prompt assembly
- media handling
- memory turn setup
- engine-specific command UX
- integrations such as YouTube, DishFramed, Nextcloud, Server3 TV
- diary queue orchestration

Impact:

- hard to reason about
- hard to isolate in tests
- edits in one area can regress unrelated flows

Recommendation:

- do not do a single giant split
- extract one seam at a time behind stable function boundaries
- introduce a small shared request/context object so helper functions stop carrying large parameter lists

### 4. `main.py` bootstrap/orchestration is too repetitive

`src/telegram_bridge/main.py` has a very large `run_bridge()` that repeats state-file load/quarantine/fallback logic for many different state files.

Impact:

- noisy startup path
- repetitive failure handling
- harder to add or remove state files safely

Recommendation:

- replace repeated state-loader blocks with a table-driven helper
- keep per-file names in a declarative structure
- centralize corrupt-file quarantine and event emission

### 5. Config is centralized, but not centralized enough

The earlier LLM audit was directionally right about config sprawl, but too simplistic.

What is true:

- `src/telegram_bridge/runtime_config.py` already centralizes many defaults in `load_config()`
- consumers still use a large amount of defensive `getattr(config, ...)` access
- test doubles and loose config objects are part of why this persists

Impact:

- repetitive parsing/normalization logic in consumers
- config semantics spread across modules
- some defaults can silently diverge over time

Recommendation:

- split `Config` into nested sub-configs or clearly grouped sections
- reduce ad hoc `SimpleNamespace`-style config test fixtures over time
- migrate high-churn code to direct typed attribute access first

### 6. `PiEngineAdapter` owns too many responsibilities

`src/telegram_bridge/engine_adapter.py` contains a Pi adapter that currently handles:

- local vs SSH execution
- Ollama tunnel management
- image-capability checks
- session path generation
- session rotation and archive cleanup
- RPC response extraction
- retry/fallback behavior
- provider/model scoping

Impact:

- high complexity in one class
- difficult to change transport logic without touching session logic
- harder to test narrowly

Recommendation:

- split Pi into smaller collaborators:
  - transport
  - session storage policy
  - capability/model inspection
  - response parsing/fallback handling

### 7. Command routing is still imperative and manual

Examples:

- `handle_known_command()` in `src/telegram_bridge/handlers.py`
- callback action routing in `handle_callback_query()`

Impact:

- lots of repetitive ceremony
- harder to add new commands consistently
- more command UX behavior scattered across helpers

Recommendation:

- introduce a command registry:
  - command string -> handler function/object
- introduce a callback action registry:
  - callback kind/action -> handler

### 8. Runtime concurrency is simple but unbounded in style

The bridge starts raw daemon threads from several locations:

- message workers
- diary capture workers
- diary queue workers
- restart trigger workers
- executor stdout/stderr drain workers

Impact:

- operational behavior is harder to reason about than a bounded executor model
- threading patterns are repeated instead of standardized

Recommendation:

- keep the current behavior initially
- later move runtime-owned work dispatch to a bounded executor abstraction
- standardize thread creation, naming, and lifecycle accounting

### 9. Some conceptual surface looks dead or half-retired

`expire_idle_worker_sessions()` in `src/telegram_bridge/session_manager.py` is currently a no-op.

Impact:

- misleading feature surface
- dead complexity in config and mental model

Recommendation:

- either reintroduce it as a real behavior with tests
- or remove the idle-expiry concept entirely

### 10. Tests are stronger than the earlier LLM audit implied, but still uneven

The repo already has meaningful tests for many bridge areas, including:

- `test_bridge_core.py`
- `test_runtime_config.py`
- `test_pi_plugin.py`
- `test_memory_engine.py`
- `test_affective_runtime.py`

But the testing style is still skewed toward large integration-style test modules.

Recommendation:

- add more direct tests for `state_store.py`
- add more direct tests for `session_manager.py`
- add narrow tests around extracted helper modules as refactors land

## Corrections to the Earlier LLM Audit

These points from the earlier audit should be refined before action:

### Base adapter extraction: partly valid

Valid:

- a tiny shared helper for repeated `CompletedProcess` wrapping is reasonable

Not valid as written:

- standardizing Venice and Pi image payload helpers into one output format

Why:

- Venice needs a `data:` URL string for its API payload
- Pi RPC uses a structured image object

Those should not be forced into one representation.

### Import fallback cleanup: valid goal, wrong first move

Valid:

- the `try/except ImportError` pattern is repetitive

Risk if done too early:

- current runtime and tests still support both package-style and direct execution/import behavior

Do not remove these fallbacks until the entrypoint/import story is normalized.

### Thin ops script consolidation: overstated

Some scripts are thin wrappers. Others contain service-specific preflight or auth behavior.

Do not replace the entire ops layer with a generic `systemctl "$1" "$2"` pattern. That would erase useful runtime-specific safety and discoverability.

## Recommended Refactor Strategy

### Principles

- prefer smallest safe change per phase
- preserve live runtime behavior while restructuring
- extract seams before redesigning internals
- add tests around each seam before or during extraction
- do not combine state-model unification with handler splitting in one phase

## Concrete Refactor Plan

### Phase 1: Safest-First Cleanup

Goal:

- reduce noise and duplication without changing runtime architecture

Target files:

- `src/telegram_bridge/main.py`
- `src/telegram_bridge/plugin_registry.py`
- `src/telegram_bridge/engine_adapter.py`
- `src/telegram_bridge/runtime_config.py`
- `tests/telegram_bridge/test_runtime_config.py`
- `tests/telegram_bridge/test_bridge_core.py`

Changes:

- add a shared state-load helper in `main.py` for load/quarantine/fallback behavior
- make default plugin registry reusable instead of rebuilding it ad hoc
- extract a tiny shared helper/mixin for repeated engine output wrapping
- group config sections with helper builders inside `runtime_config.py`
- add or tighten tests around these extractions

Expected risk:

- low

Expected payoff:

- immediate readability improvement
- lower startup-path duplication
- safer base for later refactors

### Phase 2: Routing and Handler Surface Simplification

Goal:

- reduce the size and complexity of `handlers.py` without changing external behavior

Target files:

- `src/telegram_bridge/handlers.py`
- new modules under `src/telegram_bridge/handlers_*` or a `handlers/` package
- `tests/telegram_bridge/test_bridge_core.py`
- new targeted test files as extracted

Recommended extraction order:

1. command routing helpers
2. callback routing helpers
3. progress/reporting helpers
4. prompt preparation helpers
5. media/document/voice helpers

Concrete moves:

- introduce a `RequestContext` or `ChatRequestContext` dataclass
- introduce a command registry for slash commands
- introduce a callback action registry
- move progress formatting/reporting out of core request orchestration

Expected risk:

- medium

Expected payoff:

- biggest readability win without touching persistence

### Phase 3: Pi Adapter Decomposition

Goal:

- simplify the highest-complexity engine adapter

Target files:

- `src/telegram_bridge/engine_adapter.py`
- possible new modules:
  - `pi_transport.py`
  - `pi_sessions.py`
  - `pi_capabilities.py`
  - `pi_response_parser.py`
- `tests/telegram_bridge/test_pi_plugin.py`

Concrete moves:

- extract local/SSH transport behavior
- extract session pathing/rotation/archive logic
- extract model image-capability lookup
- keep the public Pi engine interface stable during decomposition

Expected risk:

- medium

Expected payoff:

- much better testability
- easier future Pi feature work

### Phase 4: State/Persistence Unification

Goal:

- remove the largest structural duplication in the codebase

Target files:

- `src/telegram_bridge/state_store.py`
- `src/telegram_bridge/session_manager.py`
- `src/telegram_bridge/main.py`
- auth and memory reset integration points
- tests:
  - `tests/telegram_bridge/test_bridge_core.py`
  - new `tests/telegram_bridge/test_state_store.py`
  - `tests/telegram_bridge/test_session_manager.py`

Concrete moves:

- make canonical state the only mutation path
- reduce legacy state to import/export compatibility
- make canonical SQLite the primary operational store
- remove mirrored legacy writes from routine operations

Expected risk:

- high

Expected payoff:

- largest reduction in complexity and maintenance cost

### Phase 5: Concurrency and Runtime Surface Cleanup

Goal:

- standardize execution and remove dead conceptual paths

Target files:

- `src/telegram_bridge/handlers.py`
- `src/telegram_bridge/session_manager.py`
- `src/telegram_bridge/executor.py`
- `src/telegram_bridge/main.py`

Concrete moves:

- introduce a bounded runtime work executor for bridge-owned background jobs
- standardize worker thread creation
- decide the fate of idle worker expiry:
  - implement properly, or
  - remove it

Expected risk:

- medium

Expected payoff:

- cleaner runtime behavior under load

## Safest-First Execution Order

If this work is executed incrementally, the safest order is:

1. `main.py` state-load helper extraction
2. plugin registry reuse/singleton cleanup
3. tiny engine output helper extraction
4. direct tests for `state_store.py`
5. `RequestContext` introduction in handlers
6. command registry extraction
7. callback registry extraction
8. Pi adapter decomposition
9. canonical-state-only mutation path
10. persistence/store unification
11. runtime executor/threading cleanup

## What Not To Do

- do not do a one-shot split of `handlers.py`
- do not unify Venice and Pi image payload formats
- do not remove import fallbacks before normalizing entrypoints/tests
- do not replace all ops scripts with one generic systemctl wrapper
- do not combine handler extraction and state-model unification in one rollout

## Suggested Deliverables by PR

### PR 1

- `main.py` loader helper
- plugin registry reuse
- tiny engine output helper

### PR 2

- add `test_state_store.py`
- expand `test_session_manager.py`

### PR 3

- `RequestContext`
- command registry extraction

### PR 4

- callback routing extraction
- progress/reporting extraction

### PR 5

- Pi adapter decomposition

### PR 6

- canonical-state-only mutation path
- legacy compatibility layer reduction

### PR 7

- persistence/store unification
- optional runtime executor cleanup

## Bottom Line

The best improvements for Server3 are not cosmetic.

The real gains come from:

- one authoritative session/state model
- one authoritative persistence path
- smaller routing/orchestration surfaces
- smaller engine adapter responsibilities
- clearer config ownership

That is the path to a codebase that is both more elegant and less fragile.
