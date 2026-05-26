import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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
DEFAULT_JUDGE_TIMEOUT_SECONDS = 30.0
DEFAULT_JUDGE_MAX_OUTPUT_CHARS = 4096
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

JUDGE_SYSTEM_PROMPT = """You are a strict judge evaluating whether an autonomous agent has achieved a user's stated goal.

You receive the goal text and the agent's most recent response. Your only job is to decide whether the goal is fully satisfied based on that response.

A goal is DONE only when:
- The response explicitly confirms the goal was completed, OR
- The response clearly shows the final deliverable was produced, OR
- The response explains the goal is unachievable / blocked / needs user input

Otherwise the goal is NOT done.

Reply ONLY with one line of JSON:
{"done": true|false, "reason": "one short sentence"}

Do not use tools. Do not add any text outside the JSON."""

JUDGE_USER_PROMPT_TEMPLATE = """Goal:
{goal}

Latest assistant response:
{response}

Current time: {current_time}

Is the goal satisfied?"""

JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE = """Goal:
{goal}

Additional criteria the user added mid-loop (all must also be satisfied for done=true):
{subgoals_block}

Latest assistant response:
{response}

Current time: {current_time}

Decision rule:
For each numbered criterion above, require specific evidence from the response.
Do not accept generic phrases like "all requirements met" without concrete support.
If any criterion lacks specific evidence, return done=false.

Is the goal and every additional criterion satisfied?"""


@dataclass(frozen=True)
class GoalPostTurnDecision:
    status: Optional[str]
    should_continue: bool
    message: str = ""
    continuation_prompt: Optional[str] = None
    pause_reason: Optional[str] = None


@dataclass(frozen=True)
class GoalContinuationRequest:
    scope_key: ScopeKey
    chat_id: int
    message_thread_id: Optional[int]
    anchor_message_id: Optional[int]
    prompt: str


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


def reconcile_goal_state_with_canonical_sessions(state: State) -> bool:
    if not state.canonical_sessions_enabled:
        with state.lock:
            _prune_shadowed_chat_goals(state.chat_goals)
        return False

    from telegram_bridge.state_models import CanonicalSession

    changed = False
    with state.lock:
        _prune_shadowed_chat_goals(state.chat_goals)
        legacy_goals = {
            normalize_scope_key(scope_key): goal_state
            for scope_key, goal_state in state.chat_goals.items()
            if isinstance(goal_state, GoalState)
        }
        for scope_key, legacy_goal_state in legacy_goals.items():
            session = state.chat_sessions.get(scope_key)
            if session is None:
                session = CanonicalSession()
                state.chat_sessions[scope_key] = session
            if not isinstance(session.goal_state, dict) and legacy_goal_state.goal:
                session.goal_state = legacy_goal_state.to_dict()
                changed = True
        sessions_snapshot = {
            normalize_scope_key(scope_key): session
            for scope_key, session in state.chat_sessions.items()
        }
    canonical_goals: Dict[ScopeKey, GoalState] = {}
    for scope_key, session in sessions_snapshot.items():
        raw_goal_state = getattr(session, "goal_state", None)
        if not isinstance(raw_goal_state, dict):
            continue
        try:
            goal_state = GoalState.from_dict(raw_goal_state)
        except Exception:
            continue
        if goal_state.goal:
            canonical_goals[scope_key] = goal_state
    _prune_shadowed_chat_goals(canonical_goals)
    with state.lock:
        if state.chat_goals != canonical_goals:
            state.chat_goals = canonical_goals
    return changed


def _goal_states_from_canonical_sessions(state: State) -> Dict[ScopeKey, GoalState]:
    out: Dict[ScopeKey, GoalState] = {}
    with state.lock:
        sessions_snapshot = {
            normalize_scope_key(scope_key): session
            for scope_key, session in state.chat_sessions.items()
        }
    for scope_key, session in sessions_snapshot.items():
        raw_goal_state = getattr(session, "goal_state", None)
        if not isinstance(raw_goal_state, dict):
            continue
        try:
            goal_state = GoalState.from_dict(raw_goal_state)
        except Exception:
            continue
        if goal_state.goal:
            out[scope_key] = goal_state
    _prune_shadowed_chat_goals(out)
    return out


def persist_chat_goals(state: State) -> None:
    if state.canonical_sessions_enabled:
        values = {
            scope_key: goal_state.to_dict()
            for scope_key, goal_state in _goal_states_from_canonical_sessions(state).items()
        }
    else:
        with state.lock:
            values = {scope_key: goal_state.to_dict() for scope_key, goal_state in state.chat_goals.items()}
    persist_json_state_file(state.chat_goal_path, values)


def get_goal_state(state: State, scope_key: ScopeKey) -> Optional[GoalState]:
    scope_key = normalize_scope_key(scope_key)
    if state.canonical_sessions_enabled:
        with state.lock:
            session = state.chat_sessions.get(scope_key)
            raw_goal_state = session.goal_state if session is not None else None
        if isinstance(raw_goal_state, dict):
            try:
                return GoalState.from_dict(raw_goal_state)
            except Exception:
                return None
        return None
    with state.lock:
        goal = state.chat_goals.get(scope_key)
        if goal is None:
            return None
        return GoalState.from_dict(goal.to_dict())


def _set_goal_state(state: State, scope_key: ScopeKey, goal_state: GoalState) -> None:
    scope_key = normalize_scope_key(scope_key)
    if state.canonical_sessions_enabled:
        from telegram_bridge.canonical_runtime_state_store import persist_canonical_session_scope
        from telegram_bridge.state_models import CanonicalSession

        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is None:
                session = CanonicalSession()
                state.chat_sessions[scope_key] = session
            session.goal_state = goal_state.to_dict()
            state.chat_goals[scope_key] = GoalState.from_dict(goal_state.to_dict())
            _prune_shadowed_chat_goals(state.chat_goals)
        persist_canonical_session_scope(state, scope_key)
        persist_chat_goals(state)
        return
    with state.lock:
        state.chat_goals[scope_key] = goal_state
        _prune_shadowed_chat_goals(state.chat_goals)
    persist_chat_goals(state)


def clear_goal_state(state: State, scope_key: ScopeKey) -> bool:
    scope_key = normalize_scope_key(scope_key)
    removed = False
    if state.canonical_sessions_enabled:
        from telegram_bridge.canonical_runtime_state_store import persist_canonical_session_scope
        from telegram_bridge.canonical_state_store import canonical_session_is_empty

        with state.lock:
            session = state.chat_sessions.get(scope_key)
            if session is not None and isinstance(session.goal_state, dict):
                session.goal_state = None
                removed = True
                if canonical_session_is_empty(session):
                    del state.chat_sessions[scope_key]
            if scope_key in state.chat_goals:
                del state.chat_goals[scope_key]
            if removed:
                _prune_shadowed_chat_goals(state.chat_goals)
        if removed:
            persist_canonical_session_scope(state, scope_key)
            persist_chat_goals(state)
        return removed
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


class ScopeGoalManager:
    """Hermes-style goal state machine backed by Server3 scope state.

    Hermes persists goals per session id and keeps transport orchestration in
    the CLI. Server3 needs the same goal lifecycle, but keyed by Telegram scope
    and wired into bridge worker/busy handling instead of a local input queue.
    """

    def __init__(self, state: State, scope_key: ScopeKey):
        self._state = state
        self.scope_key = normalize_scope_key(scope_key)

    @property
    def goal_state(self) -> Optional[GoalState]:
        return get_goal_state(self._state, self.scope_key)

    def is_active(self) -> bool:
        goal_state = self.goal_state
        return goal_state is not None and goal_state.status == "active"

    def has_goal(self) -> bool:
        goal_state = self.goal_state
        return goal_state is not None and goal_state.status in {"active", "paused"}

    def status_line(self) -> str:
        return status_line(self.goal_state)

    def anchor_message_id(self) -> Optional[int]:
        goal_state = self.goal_state
        if goal_state is None:
            return None
        return goal_state.anchor_message_id

    def set(
        self,
        goal: str,
        *,
        anchor_message_id: Optional[int] = None,
        max_turns: Optional[int] = None,
    ) -> GoalState:
        goal = str(goal or "").strip()
        if not goal:
            raise ValueError("goal text is empty")
        goal_state = GoalState(
            goal=goal,
            anchor_message_id=anchor_message_id,
            max_turns=int(max_turns or DEFAULT_MAX_TURNS),
        )
        _set_goal_state(self._state, self.scope_key, goal_state)
        return goal_state

    def pause(self, reason: str = "user-paused") -> Optional[GoalState]:
        goal_state = self.goal_state
        if goal_state is None:
            return None
        goal_state.status = "paused"
        goal_state.paused_reason = reason
        _set_goal_state(self._state, self.scope_key, goal_state)
        return goal_state

    def resume(
        self,
        *,
        reset_budget: bool = True,
        anchor_message_id: Optional[int] = None,
    ) -> Optional[GoalState]:
        goal_state = self.goal_state
        if goal_state is None:
            return None
        goal_state.status = "active"
        goal_state.paused_reason = None
        if reset_budget:
            goal_state.turns_used = 0
        if isinstance(anchor_message_id, int):
            goal_state.anchor_message_id = anchor_message_id
        _set_goal_state(self._state, self.scope_key, goal_state)
        return goal_state

    def clear(self) -> bool:
        return clear_goal_state(self._state, self.scope_key)

    def pause_for_user_preemption(self) -> Optional[GoalState]:
        return self.pause(reason="user-follow-up preempted the active goal turn")

    def pause_for_interrupt(self) -> Optional[GoalState]:
        return self.pause(reason="active goal turn was canceled or interrupted by the user")

    def build_continuation_prompt(self) -> Optional[str]:
        goal_state = self.goal_state
        if goal_state is None or goal_state.status != "active":
            return None
        return build_continuation_prompt(goal_state)

    def build_continuation_request(
        self,
        *,
        chat_id: int,
        message_thread_id: Optional[int],
        continuation_prompt: Optional[str] = None,
    ) -> Optional[GoalContinuationRequest]:
        goal_state = self.goal_state
        prompt = str(continuation_prompt or self.build_continuation_prompt() or "").strip()
        if goal_state is None or goal_state.status != "active" or not prompt:
            return None
        return GoalContinuationRequest(
            scope_key=self.scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            anchor_message_id=goal_state.anchor_message_id,
            prompt=prompt,
        )

    def add_subgoal(self, text: str) -> str:
        goal_state = self.goal_state
        if goal_state is None or goal_state.status not in {"active", "paused"}:
            raise RuntimeError("no active goal")
        cleaned = str(text or "").strip()
        if not cleaned:
            raise ValueError("subgoal text is empty")
        goal_state.subgoals.append(cleaned)
        _set_goal_state(self._state, self.scope_key, goal_state)
        return cleaned

    def remove_subgoal(self, index_1_based: int) -> str:
        goal_state = self.goal_state
        if goal_state is None or goal_state.status not in {"active", "paused"}:
            raise RuntimeError("no active goal")
        idx = int(index_1_based) - 1
        if idx < 0 or idx >= len(goal_state.subgoals):
            raise IndexError("subgoal index out of range")
        removed = goal_state.subgoals.pop(idx)
        _set_goal_state(self._state, self.scope_key, goal_state)
        return removed

    def clear_subgoals(self) -> int:
        goal_state = self.goal_state
        if goal_state is None or goal_state.status not in {"active", "paused"}:
            raise RuntimeError("no active goal")
        previous = len(goal_state.subgoals)
        goal_state.subgoals = []
        _set_goal_state(self._state, self.scope_key, goal_state)
        return previous

    def evaluate_after_turn(
        self,
        *,
        config,
        client,
        chat_id: int,
        message_thread_id: Optional[int],
        last_response: str,
    ) -> GoalPostTurnDecision:
        goal_state = self.goal_state
        if goal_state is None or goal_state.status != "active":
            return GoalPostTurnDecision(
                status=goal_state.status if goal_state is not None else None,
                should_continue=False,
            )

        goal_state.turns_used += 1
        goal_state.last_turn_at = time.time()
        verdict, reason, parse_failed = _run_goal_judge(
            state=self._state,
            config=config,
            client=client,
            scope_key=self.scope_key,
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
            _set_goal_state(self._state, self.scope_key, goal_state)
            return GoalPostTurnDecision(
                status="done",
                should_continue=False,
                message=f"✓ Goal achieved: {reason}",
            )

        if goal_state.consecutive_parse_failures >= DEFAULT_MAX_CONSECUTIVE_PARSE_FAILURES:
            goal_state.status = "paused"
            goal_state.paused_reason = (
                f"judge model returned unparseable output {goal_state.consecutive_parse_failures} turns in a row"
            )
            _set_goal_state(self._state, self.scope_key, goal_state)
            return GoalPostTurnDecision(
                status="paused",
                should_continue=False,
                pause_reason=goal_state.paused_reason,
                message=(
                    "⏸ Goal paused - judge output was unparseable for "
                    f"{goal_state.consecutive_parse_failures} turns. Use /goal resume to continue."
                ),
            )

        if goal_state.turns_used >= goal_state.max_turns:
            goal_state.status = "paused"
            goal_state.paused_reason = (
                f"turn budget exhausted ({goal_state.turns_used}/{goal_state.max_turns})"
            )
            _set_goal_state(self._state, self.scope_key, goal_state)
            return GoalPostTurnDecision(
                status="paused",
                should_continue=False,
                pause_reason=goal_state.paused_reason,
                message=(
                    f"⏸ Goal paused - {goal_state.turns_used}/{goal_state.max_turns} turns used. "
                    "Use /goal resume to keep going, or /goal clear to stop."
                ),
            )

        goal_state.status = "active"
        goal_state.paused_reason = None
        _set_goal_state(self._state, self.scope_key, goal_state)
        return GoalPostTurnDecision(
            status="active",
            should_continue=True,
            message=f"↻ Continuing toward goal ({goal_state.turns_used}/{goal_state.max_turns}): {reason}",
            continuation_prompt=self.build_continuation_prompt(),
        )


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


def _goal_judge_max_output_chars(config) -> int:
    value = getattr(config, "goal_judge_max_output_chars", DEFAULT_JUDGE_MAX_OUTPUT_CHARS)
    try:
        parsed = int(value)
    except Exception:
        return DEFAULT_JUDGE_MAX_OUTPUT_CHARS
    return parsed if parsed > 0 else DEFAULT_JUDGE_MAX_OUTPUT_CHARS


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

    current_time = datetime.now(tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    if goal_state.subgoals:
        judge_user_prompt = JUDGE_USER_PROMPT_WITH_SUBGOALS_TEMPLATE.format(
            goal=_truncate(goal_state.goal, 2000),
            subgoals_block=_truncate(goal_state.render_subgoals_block(), 2000),
            response=_truncate(last_response, JUDGE_RESPONSE_SNIPPET_CHARS),
            current_time=current_time,
        )
    else:
        judge_user_prompt = JUDGE_USER_PROMPT_TEMPLATE.format(
            goal=_truncate(goal_state.goal, 2000),
            response=_truncate(last_response, JUDGE_RESPONSE_SNIPPET_CHARS),
            current_time=current_time,
        )
    judge_prompt = (
        "[System Instructions]\n"
        f"{JUDGE_SYSTEM_PROMPT}\n\n"
        "[User Input]\n"
        f"{judge_user_prompt}"
    )
    try:
        engine_config = build_engine_runtime_config(
            state,
            config,
            scope_key,
            getattr(engine, "engine_name", ""),
        )
        try:
            setattr(engine_config, "max_output_chars", _goal_judge_max_output_chars(config))
            setattr(
                engine_config,
                "exec_timeout_seconds",
                float(
                    getattr(config, "goal_judge_timeout_seconds", DEFAULT_JUDGE_TIMEOUT_SECONDS)
                    or DEFAULT_JUDGE_TIMEOUT_SECONDS
                ),
            )
        except Exception:
            logging.debug("Goal judge engine config does not accept runtime overrides", exc_info=True)
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
    manager = ScopeGoalManager(state, scope_key)
    decision = manager.evaluate_after_turn(
        config=config,
        client=client,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        last_response=last_response,
    )
    return asdict(decision)


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

    manager = ScopeGoalManager(state, scope_key)
    continuation_request = manager.build_continuation_request(
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        continuation_prompt=continuation_prompt,
    )
    if continuation_request is None:
        return False
    goal_state = manager.goal_state
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
            scope_key=continuation_request.scope_key,
            chat_id=continuation_request.chat_id,
            message_thread_id=continuation_request.message_thread_id,
            message_id=continuation_request.anchor_message_id,
            prompt=continuation_request.prompt,
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
    manager = ScopeGoalManager(state, scope_key)
    args = _parse_goal_args(raw_text, "/goal")
    lower = args.lower()
    goal_state = manager.goal_state

    if not args or lower == "status":
        client.send_message(
            chat_id,
            manager.status_line(),
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if lower == "pause":
        paused = manager.pause(reason="user-paused")
        if paused is None:
            text = "No active goal. Set one with /goal <text>."
        else:
            text = f"⏸ Goal paused: {paused.goal}"
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if lower == "resume":
        resumed = manager.resume(anchor_message_id=message_id)
        if resumed is None:
            text = "No paused goal to resume."
        else:
            maybe_start_goal_continuation(
                state=state,
                config=config,
                client=client,
                scope_key=scope_key,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                continuation_prompt=manager.build_continuation_prompt(),
            )
            text = f"▶ Goal resumed: {resumed.goal}"
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    if lower in {"clear", "stop", "done"}:
        had_goal = manager.clear()
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

    new_state = manager.set(
        args.strip(),
        anchor_message_id=message_id if isinstance(message_id, int) else None,
    )
    started = maybe_start_goal_continuation(
        state=state,
        config=config,
        client=client,
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        continuation_prompt=manager.build_continuation_prompt(),
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
    manager = ScopeGoalManager(state, scope_key)
    args = _parse_goal_args(raw_text, "/subgoal")
    goal_state = manager.goal_state
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
                removed = manager.remove_subgoal(idx + 1)
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
        prev = manager.clear_subgoals()
        text = f"✓ Cleared {prev} subgoal{'s' if prev != 1 else ''}." if prev else "No subgoals to clear."
        client.send_message(
            chat_id,
            text,
            reply_to_message_id=message_id,
            message_thread_id=message_thread_id,
        )
        return True

    manager.add_subgoal(args.strip())
    client.send_message(
        chat_id,
        f"✓ Added subgoal {len(manager.goal_state.subgoals) if manager.goal_state is not None else 0}: {args.strip()}",
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
    sender_name: str = "Telegram User",
    steered_follow_up_count: int = 0,
) -> None:
    scope_key = _canonical_goal_scope_key(
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
    )
    if not str(delivered_output or "").strip():
        return
    manager = ScopeGoalManager(state, scope_key)
    if (
        sender_name == "Goal Continuation"
        and steered_follow_up_count > 0
        and manager.is_active()
    ):
        paused = manager.pause_for_user_preemption()
        if paused is not None:
            client.send_message(
                chat_id,
                "⏸ Goal paused - a real user follow-up arrived during the active goal turn. "
                "Use /goal resume to continue, or /goal clear to stop.",
                reply_to_message_id=manager.anchor_message_id(),
                message_thread_id=message_thread_id,
            )
        return
    decision = manager.evaluate_after_turn(
        config=config,
        client=client,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        last_response=delivered_output,
    )
    message = str(decision.message or "").strip()
    if message:
        client.send_message(
            chat_id,
            message,
            reply_to_message_id=manager.anchor_message_id(),
            message_thread_id=message_thread_id,
        )
    if decision.should_continue:
        maybe_start_goal_continuation(
            state=state,
            config=config,
            client=client,
            scope_key=scope_key,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            continuation_prompt=decision.continuation_prompt,
        )


def maybe_handle_goal_turn_cancelled(
    *,
    state: State,
    client,
    scope_key: ScopeKey,
    chat_id: int,
    message_thread_id: Optional[int],
    sender_name: str = "Telegram User",
) -> None:
    scope_key = _canonical_goal_scope_key(
        scope_key=scope_key,
        chat_id=chat_id,
        message_thread_id=message_thread_id,
    )
    if sender_name != "Goal Continuation":
        return
    manager = ScopeGoalManager(state, scope_key)
    if not manager.is_active():
        return
    paused = manager.pause_for_interrupt()
    if paused is None:
        return
    client.send_message(
        chat_id,
        "⏸ Goal paused - the active goal turn was canceled or interrupted. "
        "Use /goal resume to continue, or /goal clear to stop.",
        reply_to_message_id=manager.anchor_message_id(),
        message_thread_id=message_thread_id,
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
