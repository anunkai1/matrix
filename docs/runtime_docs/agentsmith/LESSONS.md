# Lessons Log

Purpose: capture recurring mistake patterns and concrete prevention rules after user correction.

## Entry Template

### YYYY-MM-DDTHH:MM:SS+10:00 - Short Lesson Title
- Mistake pattern: what went wrong
- Prevention rule: the concrete rule to avoid repeat
- Where/when applied: exact decision point or workflow step

## Lessons

### 2026-03-21T23:20:00+10:00 - Clarify File Delivery Target Before Sending
- Mistake pattern: I did not immediately clarify whether "send the file here" meant a Codex chat link/content response or a Telegram document attachment.
- Prevention rule: When a file-delivery request has ambiguous destination, ask one explicit routing question first: `Codex chat link/content or Telegram document attachment?`
- Where/when applied: Before executing any file-sharing or attachment-delivery request.

### 2026-03-21T23:21:00+10:00 - Verify Delivery Capability From Runtime Code, Not Tool List Alone
- Mistake pattern: I assumed Telegram file-attachment delivery was unavailable because it was not explicit in the visible agent tool list.
- Prevention rule: For bridge/media capability questions, check `AGENTSMITH_SUMMARY.md` for the current capability watchouts first and inspect runtime transport/handler code before answering with certainty.
- Where/when applied: Any claim about Telegram, media, document, audio, or bridge output capability.

### 2026-03-21T23:22:00+10:00 - Verify Shared Runtime Topology At The Filesystem Level
- Mistake pattern: I inferred runtime separation from service-unit `ExecStart` paths without checking whether those files were shared directories, overlays, or shims.
- Prevention rule: For architecture/topology claims, inspect `readlink -f`, inode identity, and file contents before concluding whether runtimes are separate or shared.
- Where/when applied: Any answer about which runtimes share code, inherit changes, or require separate rollout.
