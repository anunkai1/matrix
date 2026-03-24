# Lessons Log

Purpose: capture recurring mistake patterns and concrete prevention rules after user correction.

## Entry Template

### YYYY-MM-DDTHH:MM:SS+10:00 - Short Lesson Title
- Mistake pattern: what went wrong
- Prevention rule: the concrete rule to avoid repeat
- Where/when applied: exact decision point or workflow step

## Lessons

### 2026-03-24T12:20:00+10:00 - Verify Diary Save Before Reporting Success
- Mistake pattern: A diary assistant could report an entry as saved before confirming the document actually contains the new content and media.
- Prevention rule: After any diary write, verify the target file reflects the intended change before reporting success.
- Where/when applied: Every diary document create, append, rewrite, or media-embed action.

### 2026-03-24T12:21:00+10:00 - Clarify File Delivery Target Before Sending
- Mistake pattern: A file-sharing request can be ambiguous between inline content in chat and a Telegram attachment.
- Prevention rule: Ask one explicit routing question first: `Inline chat link/content or Telegram document attachment?`
- Where/when applied: Before any diary-export or file-delivery action.
