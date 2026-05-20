1. Codex does not rely on cloud-only storage in this runtime.
2. For Architect on Server3, Codex stores local session history in `~/.codex/sessions/.../*.jsonl` files.
3. The Telegram bridge stores only the `thread_id` pointer in its own SQLite state. That `thread_id` is used to resume the matching local Codex session/history.
4. This must be remembered because I got it wrong once already. Do not claim Codex conversation history is cloud-only unless it has been explicitly verified otherwise.
5. you are architect from the matrix so act like it.
