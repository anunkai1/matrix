# Server3 Browser Automation MVP

Status: deployed on live host

## Document Role

This file is the planning and operator document for a Server3 browser-automation runtime modeled after the useful parts of OpenClaw browser control.

It should contain:

- decisions already made
- rationale for those decisions
- next actions before live deployment

## Purpose

Define a robust browser-control layer on Server3 that a bot can use to operate a real browser reliably.

The goal is not a screenshot-only click bot. The goal is a browser service that:

- opens and controls a real browser on Server3
- reads the page in a structured way
- acts on identified page elements
- survives normal web friction such as popups, waits, login state, and page changes better than image-only automation

## Decisions

## Product Shape

The browser-automation MVP should be:

- a dedicated browser runtime on Server3
- controlled by a local service
- callable by higher-level bot runtimes later
- based on structured page inspection first, with screenshots as supporting evidence
- separate from any personal browser profile

This is explicitly closer to OpenClaw-style browser control than to coordinate-click automation.

## What "OpenClaw-style" Means Here

For this project, "OpenClaw-style" means:

- operate a real browser, not a fake DOM-only simulator
- expose a small browser action surface such as open, navigate, inspect page, click, type, screenshot, and manage tabs
- inspect page structure in a stable way instead of relying only on screenshots
- identify and act on page elements deliberately instead of approximate visual clicking
- maintain a clean browser session and profile boundary
- aim for reliability across real-world browser issues such as popups, timing delays, tab state, and login flows

## MVP Scope

Included:

- launch a dedicated browser on Server3 under its own profile
- navigate to pages
- inspect the current page in a structured form
- list and track tabs
- click identified elements
- type into identified fields
- take screenshots for verification
- keep browser state isolated from normal user browsing
- expose the browser runtime behind a local control service

Excluded from MVP:

- full general web-agent autonomy
- account/password vaulting
- arbitrary multi-site workflow execution without supervision
- visual-only coordinate clicking as the primary control method
- support for every browser family from day one
- broad multi-user browser tenancy

## Runtime Shape

Recommended runtime model:

- one isolated Linux user for browser control
- one dedicated browser profile
- one long-running browser-control service
- one local API or IPC surface for higher-level bot/runtime callers
- one state/log directory separate from existing chat runtimes

High-level components:

1. Browser process
2. Browser control service
3. Structured page-inspection layer
4. Action executor
5. Optional screenshot capture for audit/verification
6. Bot/tool wrapper later

## Control Model

The browser-control service should expose a small stable action set, for example:

- open or navigate to URL
- inspect current page structure
- list tabs
- switch tabs
- click element
- type into element
- capture screenshot
- close tab

The key requirement is that actions should be based on identified page elements from structured inspection, not approximate screen coordinates.

## Reliability Goals

The MVP should aim to handle:

- ordinary page loads and reloads
- delayed rendering
- simple popups and overlays
- tab changes
- login-state continuity inside the dedicated browser profile
- basic retries when a page changes between inspection and action

The MVP should avoid:

- "click somewhere near the blue button" behavior
- brittle dependence on screenshots alone
- mixing browser state with personal browsing
- leaving the browser profile in a dirty or ambiguous state between runs

## Safety Goals

The browser layer should be safe enough that higher-level bots do not act randomly through it.

That means:

- explicit action surface
- explicit target selection
- structured page reading before acting
- bounded retries
- no silent free-form browser improvisation
- clear logs of what was opened, inspected, clicked, or typed

## Why This Is Hard

The hard part is not opening a browser. The hard part is reliability.

The complexity comes from:

- pages changing after inspection
- popups and overlays intercepting clicks
- timing and async rendering
- login/session persistence
- stale element references
- pages that look simple in screenshots but are structurally messy underneath
- keeping the browser profile clean and reusable across sessions

## Rationale

Key rationale behind this MVP shape:

- a screenshot-only browser bot is fast to build but too brittle to be a good foundation
- structured page inspection is the core step that makes browser automation meaningfully more reliable
- isolating the browser profile and runtime prevents pollution of personal browsing state and reduces debugging confusion
- a small action surface is easier to trust, test, and harden than open-ended browser freedom
- keeping the browser layer separate from any one bot lets it become reusable infrastructure for Server3 later

## MVP Decisions

- managed browser: Brave on Server3
- browser family baseline: Chromium-compatible only for MVP
- control stack: Playwright-driven managed browser service with a local loopback API
- runtime isolation: dedicated `browser_brain` runtime, separate from the `tv` desktop/browser path
- default execution mode: headless
- action model: snapshot refs plus bounded stale-target recovery
- screenshot retention: temp capture directory with TTL cleanup on service start
- first integration mode: standalone local service first, higher-level runtime callers later

## Next Actions

After deployment, the next steps are:

1. Decide the first higher-level caller, likely Architect.
2. Add a small local CLI or caller wrapper for faster operator smoke tests.
3. Harden the allow/deny navigation policy before broad bot integration.
4. Add typed input and screenshot regression checks to the live smoke test path.
5. Add existing-session attach only after the isolated managed-profile path is stable.

## Expansion Path After MVP

Planned expansion order:

1. robust page inspection and action targeting
2. better popup and overlay handling
3. session persistence hardening
4. higher-level workflow composition
5. integration into one or more chat runtimes
6. support for more complex multi-step web tasks

## Source of Truth

This file is the current planning source for the browser-automation MVP on Server3 until a stricter contract is needed.
