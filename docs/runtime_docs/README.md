## Runtime Docs

This directory stores canonical runtime-local documentation that used to live only inside service user home directories.

Purpose:
- keep operational docs under version control
- let runtime roots consume repo-backed copies through symlinks
- avoid drift between live runtime docs and Git history

Current state:
- AgentSmith companion docs are repo-backed from this directory
- Tank handoff docs are repo-backed from this directory
- Govorun runtime README is repo-backed from this directory
- verify live symlink wiring with:
  - `bash ops/runtime_personas/check_runtime_repo_links.sh`

Keep out of Git:
- real secrets
- live sqlite state
- `.local/state` runtime data
- attachments, caches, and transient logs
