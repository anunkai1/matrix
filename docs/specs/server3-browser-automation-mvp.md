# Server3 Browser Automation MVP

Status: planning-only

## Document Role

This file is the human-readable planning spec for an OpenClaw-style browser automation layer on Server3.

It should contain:

- current planning decisions
- rationale for those decisions
- next actions before implementation

## Purpose

Define the first usable version of a Server3 browser-control layer that a bot can use through Telegram or CLI.

The goal is not screenshot-only automation. The goal is a reliable browser operator that can:

- open websites
- read what is on the page in a structured way
- click elements
- type into forms
- switch tabs
- take screenshots for verification

## Product Shape

The MVP should behave like this:

- Server3 runs a real browser under a dedicated profile
- a local control service can drive that browser
- a bot-facing tool can call that service
- screenshots are optional verification, not the primary control method
- page structure should be used when possible instead of coordinate guessing

## Why This Exists

This gives Server3 a reusable browser capability that can later be shared by multiple agents or runtime modules.

Good uses for this layer:

- website login and navigation
- reading web pages that have no clean API
- filling simple forms
- taking screenshots after an action
- letting a chat-controlled assistant use a browser more reliably

## MVP Scope

Included:

- one dedicated browser runtime on Server3
- one isolated browser profile
- one local browser control service
- one simple action surface for:
  - open URL
  - list tabs
  - switch tab
  - close tab
  - read page structure
  - click
  - type
  - capture screenshot
- bot/CLI integration point for calling those actions

Excluded from MVP:

- full visual-only automation
- OCR-first control loops
- complex login/session persistence across many unrelated accounts
- arbitrary desktop automation outside the browser
- autonomous multi-step browser tasks without user direction
- broad multi-user shared browsing

## High-Level Architecture

The MVP has four parts:

1. Browser runtime
   - a real Chromium/Chrome browser running on Server3
   - isolated profile, separate from any personal browsing state

2. Browser control service
   - a local service that can talk to the browser
   - exposes actions like open, read page, click, type, screenshot

3. Structured page-reading layer
   - returns page structure in a stable way
   - gives the bot identifiable elements to act on
   - avoids relying only on screenshots

4. Bot/CLI adapter
   - lets a bot or CLI request browser actions
   - returns readable results and screenshots when useful

## Runtime and Isolation

Recommended runtime shape:

- dedicated Linux user for the browser service
- dedicated browser profile directory
- dedicated env/state/logs
- dedicated systemd unit(s)
- shared main repo for code

This should follow the same broad Server3 pattern already used for isolated bot runtimes.

## Control Model

The browser layer should not decide tasks on its own.

For MVP:

- the user or calling bot issues the instruction
- the browser layer executes a narrow requested action
- multi-step tasks should still be driven by an external controller

Examples:

- "open example.com"
- "read this page"
- "click element 12"
- "type this text into the email field"
- "take a screenshot"

## Reliability Principles

The implementation should prefer:

- structured page reading over screenshot guessing
- element-targeted actions over coordinate clicking
- isolated browser profile over personal profile reuse
- simple deterministic actions over broad autonomy
- screenshots for verification after actions, not as the main control surface

## Why Not Screenshot-Only

Screenshot-only browser control is faster to build, but it is much less reliable.

Problems with screenshot-only control:

- buttons move
- pages resize
- popups shift layout
- the bot guesses where to click
- text entry targets are easier to miss

Using page structure is more reliable because the bot can target specific elements rather than guessing from pixels.

## Server3 Fit

This can be implemented on Server3 because Server3 already has:

- systemd-managed runtimes
- isolated Linux users for services
- bot-control patterns
- desktop/browser operational tooling
- a shared repo plus per-runtime isolation model

So the hosting model fits well. The harder part is making the browser-control logic reliable.

## Example Interaction Shape

User:
`Open bbc.com and tell me the main headlines`

Bot:
`Opened bbc.com. I found 8 major headline elements. The top headlines are: ...`

User:
`Click the first headline and take a screenshot`

Bot:
`Clicked the first headline and captured a screenshot.`

## Rationale

Key rationale behind this MVP shape:

- build a reusable browser capability instead of one-off page scripts
- keep the first version local to Server3 instead of adding remote browser complexity
- avoid image-only automation because it creates brittle behavior
- keep the browser runtime isolated so state and failures do not bleed into other services
- make the browser layer a tool that other bots can call later

## Next Actions

Before implementation starts, tighten these planning points:

1. Decide whether the browser service is shared by multiple bots or private to one caller in the first cut.
2. Decide the exact browser choice for MVP: Chromium or Chrome.
3. Define the page-structure format returned to the bot.
4. Define how screenshots are stored, retained, and exposed back to the caller.
5. Decide whether the first caller is Architect, a dedicated bot, or CLI-first.
6. Decide whether login/session persistence is in scope for the first cut or explicitly delayed.
7. Define the minimal action set that is actually required for the first milestone.

## Expansion Path After MVP

After the first working version, possible extensions are:

1. better page summarization
2. more robust element discovery
3. session persistence controls
4. support for more complex workflows
5. multi-runtime callers
6. optional remote browser host support
7. higher-level browser task planning
