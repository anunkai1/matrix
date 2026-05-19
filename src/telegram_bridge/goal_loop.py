import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from telegram_bridge.conversation_scope import build_telegram_scope_key, parse_telegram_scope_key
from telegram_bridge.executor import parse_executor_output
from telegram_bridge.handler_common import trim_output
from telegram_bridge.response_delivery import clear_cancel_event, register_cancel_event
from telegram_bridge.scope_state_store import load_json_object, persist_json_state_file
from telegram_bridge.session_manager import clear_busy, mark_busy
from telegram_bridge.state_models import ScopeKey, State, normalize_scope_key
from telegram_bridge.state_store import clear_in_flight_request, mark_in_flight_request
from telegram_bridge.engine_controls import build_engine_runtime_config


DEFAULT_MAX_TURNS = 20
DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES = 3
JUDGE_MAX_OUTPUT_CHARS = 1200
JUDGE_RESPONSE_SNIPPET_CHARS = 4000
EXPLICIT_GOAL_DONE_PATTERNS = (
    re.compile(r"\bgoal complete\b", re.IGNORECASE),
    re.compile(r"\bgoal achieved\b", re.IGNORECASE),
    re.compile(r"\bgoal is complete\b", re.IGNORECASE),
    re.compile(r"\bthe goal is complete\b", re.IGNORECASE),
    re.compile(r"\bi believe the goal is complete\b", re.IGNORECASE),
    re.compile(r"\btask complete\b", re.IGNORECASE),
    re.compile(r"\bdone\b", re.IGNORECASE),
)
EXPLICIT_BLOCKED_PATTERNS = (
    re.compile(r"\bblocked\b", re.IGNORECASE),
    re.compile(r"\bneed input from the user\b", re.IGNORECASE),
    re.compile(r"\bneed user input\b", re.IGNORECASE),
    re.compile(r"\bneed your input\b", re.IGNORECASE),
    re.compile(r"\bwaiting for the user\b", re.IGNORECASE),
    re.compile(r"\bwaiting for your input\b", re.IGNORECASE),
)

CONTINUATION_PROMPT_TEMPLATE = (
    "[Continuing toward your standing goal]\n"
    "Goal: {goal}\n\n"
    "Continue working toward this goal. Take the next concrete step. "
    "If you believe the goal is complete, state so explicitly and stop. "
    "If you are blocked and need input from the user, say so clearly and stop."
)

CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE = (
    "[Continuing toward your standing goal]\n"
    "Goal: {goal}\n\n"
    "Additional criteria the user added mid-loop:\n"
    "{subgoals_block}\n\n"
    "Continue working toward the goal AND all additional criteria. Take the next concrete step. "
    "If you believe the goal and every additional criterion are complete, state so explicitly and stop. "
    "If you are blocked and need input from the user, say so clearly and stop."
)

JUDGE_PROMPT_TEMPLATE = """You are a strict judge evaluating whether an autonomous agent has achieved a user's stated goal.

Reply ONLY with one line of JSON:
{{"done": true|false, "reason": "one short sentence"}}

Rules:
- done=true if the latest assistant response explicitly confirms the goal was completed
- done=true if the latest assistant response clearly shows the final deliverable was produced
- done=true if the latest assistant response clearly says it is blocked and needs user input
- otherwise done=false
- do not use tools
- do not add any text outside the JSON

Goal:
{goal}

{subgoals_section}Latest assistant response:
{response}
"""


@dataclass
class GoalState:
    goal: str
    status: str = "active"
    anchor_message_id: Optional[int] = None
    turns_used: int = 0
    max_turns: int = DEFAULT_MAX_TURNS
    created_at: float = field(default_factory=time.time)
    last_turn_at: float = 0.0
    last_verdict: Optional[str] = None
    last_reason: Optional[str] = None
    paused_reason: Optional[str] = None
    consecutive_parse_failures: int = 0
    subgoals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "GoalState":
        raw_subgoals = raw.get("subgoals") or []
        subgoals = []
        if isinstance(raw_subgoals, list):
            subgoals = [str(item).strip() for item in raw_subgoals if str(item).strip()]
        return cls(
            goal=str(raw.get("goal") or "").strip(),
            status=str(raw.get("status") or "active").strip() or "active",
            anchor_message_id=(
                int(raw.get("anchor_message_id"))
                if isinstance(raw.get("anchor_message_id"), int)
                else None
            ),
            turns_used=int(raw.get("turns_used", 0) or 0),
            max_turns=int(raw.get("max_turns", DEFAULT_MAX_TURNS) or DEFAULT_MAX_TURNS),
            created_at=float(raw.get("created_at", time.time()) or time.time()),
            last_turn_at=float(raw.get("last_turn_at", 0.0) or 0.0),
            last_verdict=str(raw.get("last_verdict") or "").strip() or None,
            last_reason=str(raw.get("last_reason") or "").strip() or None,
            paused_reason=str(raw.get("paused_reason") or "").strip() or None,
            consecutive_parse_failures=int(raw.get("consecutive_parse_failures", 0) or 0),
            subgoals=subgoals,
        )

    def render_subgoals_block(self) -> str:
        if not self.subgoals:
            return ""
        return "\n".join(f"- {idx}. {text}" for idx, text in enumerate(self.subgoals, start=1))


def load_chat_goals(path: str) -> Dict[ScopeKey, GoalState]:
    raw = load_json_object(path, state_label="chat goal")
    parsed: Dict[ScopeKey, GoalState] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            scope_key = normalize_scope_key(key)
            state = GoalState.from_dict(value)
        except Exception:
            continue
        if state.goal:
            parsed[scope_key] = state
    _prune_shadowed_chat_goals(parsed)
    return parsed


def persist_chat_goals(state: State) -> None:
    with state.lock:
        values = {scope_key: goal_state.to_dict() for scope_key, goal_state in state.chat_goals.items()}
    persist_json_state_file(state.chat_goal_path, values)


def get_goal_state(state: State, scope_key: ScopeKey) -> Optional[GoalState]:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        goal = state.chat_goals.get(scope_key)
        if goal is None:
            return None
        return GoalState.from_dict(goal.to_dict())


def _set_goal_state(state: State, scope_key: ScopeKey, goal_state: GoalState) -> None:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        state.chat_goals[scope_key] = goal_state
        _prune_shadowed_chat_goals(state.chat_goals)
    persist_chat_goals(state)


def clear_goal_state(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    with state.lock:
        if scope_key in state.chat_goals:
            del state.chat_goals[scope_key]
            removed = True
        if removed:
            _prune_shadowed_chat_goals(state.chat_goals)
    if removed:
        persist_chat_goals(state)
    return removed


def status_line(goal_state: Optional[GoalState]) -> str:
    if goal_state is None:
        return "No active goal. Set one with /goal <text>."
    turns = f"{goal_state.turns_used}/{goal_state.max_turns} turns"
    sub = ""
    if goal_state.subgoals:
        count = len(goal_state.subgoals)
        sub = f", {count} subgoal{'s' if count != 1 else ''}"
    if goal_state.status == "active":
        return f"⊙ Goal (active, {turns}{sub}): {goal_state.goal}"
    if goal_state.status == "paused":
        extra = f" - {goal_state.paused_reason}" if goal_state.paused_reason else ""
        return f"⏸ Goal (paused, {turns}{sub}{extra}): {goal_state.goal}"
    if goal_state.status == "done":
        return f"✓ Goal done ({turns}{sub}): {goal_state.goal}"
    return f"Goal ({goal_state.status}, {turns}{sub}): {goal_state.goal}"


def build_continuation_prompt(goal_state: GoalState) -> str:
    if goal_state.subgoals:
        return CONTINUATION_PROMPT_WITH_SUBGOALS_TEMPLATE.format(
            goal=goal_state.goal,
            subgoals_block=goal_state.render_subgoals_block(),
        )
    return CONTINUATION_PROMPT_TEMPLATE.format(goal=goal_state.goal)


def _parse_goal_args(raw_text: str, command: str) -> str:
    stripped = (raw_text or "").strip()
    if not stripped:
        return ""
    head = stripped.split(maxsplit=1)[0]
    canonical_head = head.split("@", maxsplit=1)[0]
    if canonical_head != command:
        return ""
    if len(stripped) == len(head):
        return ""
    return stripped[len(head):].strip()


def _is_scope_busy(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    with state.lock:
        return scope_key in state.busy_chats


def _truncate(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _parse_judge_response(raw: str) -> Tuple[bool, str, bool]:
    text = str(raw or "").strip()
    if not text:
        return False, "judge returned empty response", True
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1 :]
    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return False, f"judge reply was not JSON: {trim_output(text, 200)!r}", True
        try:
            parsed = json.loads(text[start : end + 1])
        except Exception:
            return False, f"judge reply was not JSON: {trim_output(text, 200)!r}", True
    if not isinstance(parsed, dict):
        return False, "judge reply was not a JSON object", True
    done_value = parsed.get("done")
    if isinstance(done_value, str):
        done = done_value.strip().lower() in {"true", "1", "yes", "done"}
    else:
        done = bool(done_value)
    reason = str(parsed.get("reason") or "").strip() or "no reason provided"
    return done, reason, False


def _response_explicitly_requests_stop(last_response: str) -> bool:
    text = str(last_response or "").strip()
    if not text:
        return False
    done_match = any(pattern.search(text) for pattern in EXPLICIT_GOAL_DONE_PATTERNS)
    blocked_match = any(pattern.search(text) for pattern in EXPLICIT_BLOCKED_PATTERNS)
    return done_match or blocked_match


def _run_goal_judge(
    *,
    state: State,
    config,
    client,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
    goal_state: GoalState,
    last_response: str,
) -> Tuple[str, str, bool]:
    from telegram_bridge.request_starts import resolve_engine_for_scope

    try:
        engine = resolve_engine_for_scope(state, config, scope_key, None)
    except Exception as exc:
        logging.debug("Goal judge engine resolution failed for scope=%s: %s", scope_key, exc)
        return "continue", "judge engine unavailable", False

    subgoals_section = ""
    if goal_state.subgoals:
        subgoals_section = (
            "Additional criteria the user added mid-loop (all must also be satisfied for done=true):\n"
            f"{goal_state.render_subgoals_block()}\n\n"
        )
    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
        goal=_truncate(goal_state.goal, 2000),
        subgoals_section=subgoals_section,
        response=_truncate(last_response, JUDGE_RESPONSE_SNIPPET_CHARS),
    )
    try:
        engine_config = build_engine_runtime_config(
            state,
            config,
            scope_key,
            getattr(engine, "engine_name", ""),
        )
        result = engine.run(
            config=engine_config,
            prompt=judge_prompt,
            thread_id=None,
            session_key=f"{scope_key}:goal_judge",
            channel_name=getattr(client, "channel_name", "telegram"),
            actor_chat_id=chat_id,
            actor_user_id=None,
            progress_callback=None,
            cancel_event=None,
        )
    except Exception as exc:
        logging.info("Goal judge request failed for scope=%s: %s", scope_key, exc)
        return "continue", f"judge error: {type(exc).__name__}", False
    if result.returncode != 0:
        return "continue", f"judge error: returncode {result.returncode}", False
    _, output = parse_executor_output(result.stdout or "")
    done, reason, parse_failed = _parse_judge_response(_truncate(output, JUDGE_MAX_OUTPUT_CHARS))
    if done and not _response_explicitly_requests_stop(last_response):
        return (
            "continue",
            "judge said done, but the assistant did not explicitly say the goal is complete or blocked",
            parse_failed,
        )
    return ("done" if done else "continue"), reason, parse_failed


def evaluate_goal_after_turn(
    *,
    state: State,
    config,
    client,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
    last_response: str,
) -> Dict[str, object]:
    goal_state = get_goal_state(state, scope_key)
    if goal_state is None or goal_state.status != "active":
        return {
            "should_continue": False,
            "message": "",
            "continuation_prompt": None,
            "status": goal_state.status if goal_state is not None else None,
        }

    goal_state.turns_used += 1
    goal_state.last_turn_at = time.time()
    verdict, reason, parse_failed = _run_goal_judge(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        goal_state=goal_state,
        last_response=last_response,
    )
    goal_state.last_verdict = verdict
    goal_state.last_reason = reason
    goal_state.consecutive_parse_failures = (
        goal_state.consecutive_parse_failures + 1 if parse_failed else 0
    )

    if verdict == "done":
        goal_state.status = "done"
        _set_goal_state(state, scope_key, goal_state)
        return {
            "should_continue": False,
            "message": f"✓ Goal achieved: {reason}",
            "continuation_prompt": None,
            "status": "done",
        }

    if goal_state.consecutive_parse_failures >= DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES:
        goal_state.status = "paused"
        goal_state.paused_reason = (
            f"judge model returned unparseable output {goal_state.consecutive_parse_failures} turns in a row"
        )
        _set_goal_state(state, scope_key, goal_state)
        return {
            "should_continue": False,
            "message": (
                "⏸ Goal paused - judge output was unparseable for "
                f"{goal_state.consecutive_parse_failures} turns. Use /goal resume to continue."
            ),
            "continuation_prompt": None,
            "status": "paused",
        }

    if goal_state.turns_used >= goal_state.max_turns:
        goal_state.status = "paused"
        goal_state.paused_reason = (
            f"turn budget exhausted ({goal_state.turns_used}/{goal_state.max_turns})"
        )
        _set_goal_state(state, scope_key, goal_state)
        return {
            "should_continue": False,
            "message": (
                f"⏸ Goal paused - {goal_state.turns_used}/{goal_state.max_turns} turns used. "
                "Use /goal resume to keep going, or /goal clear to stop."
            ),
            "continuation_prompt": None,
            "status": "paused",
        }

    goal_state.status = "active"
    goal_state.paused_reason = None
    _set_goal_state(state, scope_key, goal_state)
    return {
        "should_continue": True,
        "message": f"↻ Continuing toward goal ({goal_state.turns_used}/{goal_state.max_turns}): {reason}",
        "continuation_prompt": build_continuation_prompt(goal_state),
        "status": "active",
    }


def maybe_start_goal_continuation(
    *,
    state: State,
    config,
    client,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
    continuation_prompt: Optional[str],
) -> bool:
    from telegram_bridge.request_starts import resolve_engine_for_scope, start_message_worker

    prompt = str(continuation_prompt or "").strip()
    if not prompt:
        return False
    goal_state = get_goal_state(state, scope_key)
    if goal_state is None or goal_state.status != "active":
        return False
    if not mark_busy(state, scope_key):
        return False
    cancel_event = register_cancel_event(state, scope_key)
    try:
        mark_in_flight_request(state, scope_key, None)
        active_engine = resolve_engine_for_scope(state, config, scope_key, None)
        start_message_worker(
            state=state,
            config=config,
            client=client,
            engine=active_engine,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=goal_state.anchor_message_id,
            prompt=prompt,
            photo_file_id=None,
            photo_file_ids=None,
            voice_file_id=None,
            document=None,
            cancel_event=cancel_event,
            stateless=False,
            sender_name="Goal Continuation",
            enforce_voice_prefix_from_transcript=False,
            actor_user_id=None,
        )
    except Exception:
        clear_in_flight_request(state, scope_key)
        clear_cancel_event(state, scope_key, cancel_event)
        clear_busy(state, scope_key)
        raise
    return True


def handle_goal_command(
    *,
    state: State,
    config,
    client,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    scope_key = _canonical_goal_scope_key(
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
    )
    args = _parse_goal_args(raw_text, "/goal")
    lower = args.lower()
    goal_state = get_goal_state(state, scope_key)

    if not args or lower == "status":
        client.send_message(
            chat_id,
            status_line(goal_state),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if lower == "pause":
        if goal_state is None:
            text = "No active goal. Set one with /goal <text>."
        else:
            goal_state.status = "paused"
            goal_state.paused_reason = "user-paused"
            _set_goal_state(state, scope_key, goal_state)
            text = f"⏸ Goal paused: {goal_state.goal}"
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if lower == "resume":
        if goal_state is None:
            text = "No paused goal to resume."
        else:
            goal_state.status = "active"
            goal_state.paused_reason = None
            goal_state.turns_used = 0
            if isinstance(message_id, int):
                goal_state.anchor_message_id = message_id
            _set_goal_state(state, scope_key, goal_state)
            maybe_start_goal_continuation(
                state=state,
                config=config,
                client=client,
                scope_key=scope_key,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                continuation_prompt=build_continuation_prompt(goal_state),
            )
            text = f"▶ Goal resumed: {goal_state.goal}"
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if lower in {"clear", "stop", "done"}:
        had_goal = clear_goal_state(state, scope_key)
        client.send_message(
            chat_id,
            "Goal cleared." if had_goal else "No active goal.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if _is_scope_busy(state, scope_key):
        client.send_message(
            chat_id,
            "Agent is running - use /goal status / pause / clear mid-run, or /cancel before setting a new goal.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    new_state = GoalState(
        goal=args.strip(),
        anchor_message_id=message_id if isinstance(message_id, int) else None,
    )
    _set_goal_state(state, scope_key, new_state)
    started = maybe_start_goal_continuation(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        continuation_prompt=build_continuation_prompt(new_state),
    )
    text = f"⊙ Goal set ({new_state.max_turns} turns): {new_state.goal}"
    if not started:
        text += "\n\nGoal was stored, but the scope is currently busy."
    client.send_message(
        chat_id,
        text,
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
    return True


def handle_subgoal_command(
    *,
    state: State,
    client,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
    message_id: Optional[int],
    raw_text: str,
) -> bool:
    scope_key = _canonical_goal_scope_key(
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
    )
    args = _parse_goal_args(raw_text, "/subgoal")
    goal_state = get_goal_state(state, scope_key)
    if goal_state is None:
        client.send_message(
            chat_id,
            "No active goal. Set one with /goal <text>.",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if not args:
        client.send_message(
            chat_id,
            f"{status_line(goal_state)}\n{goal_state.render_subgoals_block() or '(no subgoals - use /subgoal <text> to add criteria)'}",
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    tokens = args.split(None, 1)
    verb = tokens[0].lower()
    rest = tokens[1].strip() if len(tokens) > 1 else ""

    if verb == "remove":
        if not rest:
            text = "Usage: /subgoal remove <n>"
        else:
            try:
                idx = int(rest.split()[0]) - 1
                if idx < 0:
                    raise ValueError("subgoal index must be positive")
                removed = goal_state.subgoals.pop(idx)
                _set_goal_state(state, scope_key, goal_state)
                text = f"✓ Removed subgoal {idx + 1}: {removed}"
            except Exception:
                text = "/subgoal remove: invalid index"
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if verb == "clear":
        prev = len(goal_state.subgoals)
        goal_state.subgoals = []
        _set_goal_state(state, scope_key, goal_state)
        text = f"✓ Cleared {prev} subgoal{'s' if prev != 1 else ''}." if prev else "No subgoals to clear."
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    goal_state.subgoals.append(args.strip())
    _set_goal_state(state, scope_key, goal_state)
    client.send_message(
        chat_id,
        f"✓ Added subgoal {len(goal_state.subgoals)}: {args.strip()}",
        reply_to_message_id=message_id,
        message_thread_id=message_thread_id,
    )
    return True


def maybe_handle_goal_post_turn(
    *,
    state: State,
    config,
    client,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
    delivered_output: str,
) -> None:
    scope_key = _canonical_goal_scope_key(
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
    )
    if not str(delivered_output or "").strip():
        return
    decision = evaluate_goal_after_turn(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        last_response=delivered_output,
    )
    message = str(decision.get("message") or "").strip()
    goal_state = get_goal_state(state, scope_key)
    if message:
        client.send_message(
            chat_id,
            message,
            reply_to_message_id=goal_state.anchor_message_id if goal_state is not None else None,
            message_thread_id=message_thread_id,
        )
    if decision.get("should_continue"):
        maybe_start_goal_continuation(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            continuation_prompt=decision.get("continuation_prompt"),
        )


__all__ = [
    "DEFAULT_MAX_TURNS",
    "GoalState",
    "clear_goal_state",
    "get_goal_state",
    "handle_goal_command",
    "handle_subgoal_command",
    "load_chat_goals",
    "maybe_handle_goal_post_turn",
    "persist_chat_goals",
    "status_line",
]


def _canonical_goal_scope_key(
    *,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
) -> ScopeKey:
    """Prefer the explicit Telegram topic scope when present.

    The bridge already carries both a scope key and the raw chat/topic ids.
    Goal state should be topic-scoped, so reconstruct the scope from
    ``chat_id`` + ``message_thread_id`` when possible instead of trusting a
    caller-provided chat-only fallback key.
    """
    if message_thread_id is not None:
        return build_telegram_scope_key(chat_id, message_thread_id=message_thread_id)
    return normalize_scope_key(scope_key)


def _prune_shadowed_chat_goals(chat_goals: Dict[ScopeKey, GoalState]) -> None:
    """Drop chat-wide goal records shadowed by topic-scoped goals in the same chat.

    Older bridge builds stored forum-topic goals at the chat scope. Once a
    topic-scoped goal exists, keeping the legacy chat-scoped record causes the
    loop to run in both places. Prefer the topic-scoped record and prune the
    chat-wide shadow.
    """
    topic_chat_ids = set()
    for scope_key in list(chat_goals):
        try:
            scope = parse_telegram_scope_key(scope_key)
        except ValueError:
            continue
        if scope.message_thread_id is not None:
            topic_chat_ids.add(scope.chat_id)

    if not topic_chat_ids:
        return

    for chat_id in topic_chat_ids:
        legacy_scope_key = build_telegram_scope_key(chat_id)
        chat_goals.pop(legacy_scope_key, None)
