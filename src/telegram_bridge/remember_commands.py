import secrets
import re
from pathlib import Path
from typing import Optional

from telegram_bridge.channel_adapter import ChannelAdapter
from telegram_bridge.handler_models import CallbackActionResult
from telegram_bridge.state_models import PendingRememberProposal, State


USAGE_MESSAGE = "Usage: /remember <text> | /remember forget <number>"
SAVE_SUCCESS_TOAST = "Saved to remember.md."
CANCEL_SUCCESS_TOAST = "Remember proposal dismissed."
UNKNOWN_PROPOSAL_TOAST = "Remember proposal not found."
DELETE_SUCCESS_TOAST = "Removed from remember.md."
UNKNOWN_ENTRY_TOAST = "Remembered item not found."

NUMBERED_ENTRY_RE = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")


def remember_file_path() -> Path:
    return Path(__file__).resolve().parents[2] / "remember.md"


def _reply(
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    text: str,
) -> bool:
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
    )
    return True


def _parse_remember_args(raw_text: str) -> str:
    stripped = (raw_text or "").strip()
    if not stripped:
        return ""
    head = stripped.split(maxsplit=1)[0]
    canonical_head = head.split("@", maxsplit=1)[0]
    if canonical_head != "/remember":
        return ""
    if len(stripped) == len(head):
        return ""
    return stripped[len(head):].strip()


def _normalize_remember_text(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip()
    if not normalized:
        return ""
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized


def build_remember_proposal(raw_text: str) -> str:
    args = _parse_remember_args(raw_text)
    normalized = _normalize_remember_text(args)
    if not normalized:
        return ""
    return normalized


def _parse_forget_number(raw_text: str) -> Optional[int]:
    args = _parse_remember_args(raw_text)
    if not args:
        return None
    head, _, tail = args.partition(" ")
    if head.lower() != "forget":
        return None
    value = tail.strip()
    if not value.isdigit():
        return -1
    number = int(value)
    if number < 1:
        return -1
    return number


def remember_callback_data(action: str, token: str) -> str:
    return f"cfg|remember|local|{action}|{token}"


def _build_reply_markup(token: str) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "Save", "callback_data": remember_callback_data("save", token)},
                {"text": "Cancel", "callback_data": remember_callback_data("cancel", token)},
            ]
        ]
    }


def _store_pending_proposal(state: State, scope_key: str, proposal: str) -> str:
    token = secrets.token_hex(8)
    pending = PendingRememberProposal(scope_key=scope_key, text=proposal)
    with state.lock:
        state.pending_remember_proposals[token] = pending
    return token


def _pop_pending_proposal(state: State, token: str) -> Optional[PendingRememberProposal]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return None
    with state.lock:
        return state.pending_remember_proposals.pop(normalized_token, None)


def _load_pending_proposal(state: State, token: str) -> Optional[PendingRememberProposal]:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return None
    with state.lock:
        return state.pending_remember_proposals.get(normalized_token)


def _proposal_response_text(proposal: str) -> str:
    return (
        "Proposed `remember.md` text:\n\n"
        f"```text\n{proposal}\n```\n\n"
        f"Target file: `{remember_file_path()}`\n"
        "Tap Save to append it to `remember.md`, or Cancel to discard it."
    )


def _load_remember_entries() -> list[str]:
    path = remember_file_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    entries: list[str] = []
    for raw_line in existing.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = NUMBERED_ENTRY_RE.match(line)
        candidate = match.group(2).strip() if match else line
        normalized = _normalize_remember_text(candidate)
        if normalized:
            entries.append(normalized)
    return entries


def _write_remember_entries(entries: list[str]) -> None:
    path = remember_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    numbered = [f"{index}. {entry}" for index, entry in enumerate(entries, start=1)]
    path.write_text("\n".join(numbered) + ("\n" if numbered else ""), encoding="utf-8")


def ensure_numbered_remember_file() -> bool:
    path = remember_file_path()
    if not path.exists():
        return False
    existing = path.read_text(encoding="utf-8")
    entries = _load_remember_entries()
    numbered = "\n".join(f"{index}. {entry}" for index, entry in enumerate(entries, start=1))
    normalized = numbered + ("\n" if numbered else "")
    if existing == normalized:
        return False
    _write_remember_entries(entries)
    return True


def _append_remember_text(text: str) -> Optional[int]:
    line = _normalize_remember_text(text)
    if not line:
        return None
    entries = _load_remember_entries()
    if line in entries:
        return None
    entries.append(line)
    _write_remember_entries(entries)
    return len(entries)


def _delete_remember_entry(number: int) -> Optional[str]:
    entries = _load_remember_entries()
    if number < 1 or number > len(entries):
        return None
    removed = entries.pop(number - 1)
    _write_remember_entries(entries)
    return removed


def _delete_response_text(number: int, removed: str) -> str:
    return (
        f"Removed remembered item {number} from `remember.md`:\n\n"
        f"```text\n{removed}\n```"
    )


def _missing_delete_response_text(number: int) -> str:
    return f"Remembered item {number} was not found in `remember.md`."


def _invalid_forget_number_response_text() -> str:
    return "Usage: /remember forget <number>"


def _saved_response_text(number: int, proposal: str) -> str:
    return (
        f"Saved to `remember.md` as item {number}:\n\n"
        f"```text\n{proposal}\n```"
    )


def _already_saved_response_text(proposal: str) -> str:
    return (
        "That exact text is already present in `remember.md`.\n\n"
        f"```text\n{proposal}\n```"
    )


def handle_remember_forget_command(
    *,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    number = _parse_forget_number(raw_text)
    if number is None:
        return False
    if number < 1:
        return _reply(client, chat_id, message_id, _invalid_forget_number_response_text())
    removed = _delete_remember_entry(number)
    if removed is None:
        return _reply(client, chat_id, message_id, _missing_delete_response_text(number))
    client.send_message(
        chat_id,
        _delete_response_text(number, removed),
        reply_to_message_id=message_id,
    )
    return True


def handle_remember_command(
    *,
    state: State,
    scope_key: str,
    client: ChannelAdapter,
    chat_id: int,
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    if handle_remember_forget_command(
        client=client,
        chat_id=chat_id,
        message_id=message_id,
        raw_text=raw_text,
    ):
        return True
    proposal = build_remember_proposal(raw_text)
    if not proposal:
        return _reply(client, chat_id, message_id, USAGE_MESSAGE)
    token = _store_pending_proposal(state, scope_key, proposal)
    client.send_message(
        chat_id,
        _proposal_response_text(proposal),
        reply_to_message_id=message_id,
        reply_markup=_build_reply_markup(token),
    )
    return True


def handle_remember_callback_action(
    *,
    state: State,
    scope_key: str,
    action: str,
    token: str,
) -> CallbackActionResult:
    proposal = _load_pending_proposal(state, token)
    if proposal is None or proposal.scope_key != scope_key:
        return CallbackActionResult(
            text="Remember proposal not found or already handled.",
            toast_text=UNKNOWN_PROPOSAL_TOAST,
        )
    if action == "cancel":
        _pop_pending_proposal(state, token)
        return CallbackActionResult(
            text="Remember proposal dismissed. Nothing was saved.",
            toast_text=CANCEL_SUCCESS_TOAST,
        )
    if action != "save":
        return CallbackActionResult(
            text="Unsupported remember action.",
            toast_text="Unsupported action.",
        )
    _pop_pending_proposal(state, token)
    appended_number = _append_remember_text(proposal.text)
    if appended_number is not None:
        return CallbackActionResult(
            text=_saved_response_text(appended_number, proposal.text),
            toast_text=SAVE_SUCCESS_TOAST,
        )
    return CallbackActionResult(
        text=_already_saved_response_text(proposal.text),
        toast_text="Already saved.",
    )
