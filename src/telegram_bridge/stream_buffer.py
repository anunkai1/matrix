from collections import deque
from typing import Deque, List


class BoundedTextBuffer:
    """Keep bounded stream text while preserving head context and tail output."""

    def __init__(
        self,
        max_chars: int,
        *,
        head_chars: int,
        truncation_marker: str,
    ) -> None:
        self.max_chars = max(1, max_chars)
        self.head_chars = min(max(0, head_chars), self.max_chars)
        self.truncation_marker = truncation_marker
        self.head_parts: List[str] = []
        self.head_len = 0
        self.tail_parts: Deque[str] = deque()
        self.tail_len = 0
        self.truncated = False

    def append(self, text: str) -> None:
        if not text:
            return

        if self.head_len < self.head_chars:
            remaining_head = self.head_chars - self.head_len
            head_chunk = text[:remaining_head]
            if head_chunk:
                self.head_parts.append(head_chunk)
                self.head_len += len(head_chunk)
            text = text[remaining_head:]

        if text:
            self.tail_parts.append(text)
            self.tail_len += len(text)
            self._trim_tail()

    def _trim_tail(self) -> None:
        allowed_tail_len = max(0, self.max_chars - self.head_len)
        while self.tail_len > allowed_tail_len and self.tail_parts:
            overflow = self.tail_len - allowed_tail_len
            front = self.tail_parts[0]
            if len(front) <= overflow:
                self.tail_parts.popleft()
                self.tail_len -= len(front)
                self.truncated = True
                continue
            self.tail_parts[0] = front[overflow:]
            self.tail_len -= overflow
            self.truncated = True
            break

    def render(self) -> str:
        head = "".join(self.head_parts)
        tail = "".join(self.tail_parts)
        if not self.truncated:
            return head + tail

        marker = self.truncation_marker
        if not marker:
            return head + tail
        if len(marker) >= self.max_chars:
            return marker[: self.max_chars]

        available_without_marker = self.max_chars - len(marker)
        head = head[:available_without_marker]
        tail_budget = max(0, available_without_marker - len(head))
        if tail_budget == 0:
            tail = ""
        elif len(tail) > tail_budget:
            tail = tail[-tail_budget:]
        return head + marker + tail
