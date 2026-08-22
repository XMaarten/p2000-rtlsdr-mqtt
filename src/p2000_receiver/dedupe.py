from __future__ import annotations

import time
from collections import OrderedDict

from .models import P2000Message


class DedupeCache:
    def __init__(self, window_seconds: int, max_entries: int):
        self.window_seconds = max(0, window_seconds)
        self.max_entries = max(1, max_entries)
        self._entries: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, message: P2000Message) -> bool:
        if self.window_seconds <= 0:
            return False
        now = time.monotonic()
        cutoff = now - self.window_seconds
        while self._entries:
            key, ts = next(iter(self._entries.items()))
            if ts >= cutoff:
                break
            self._entries.pop(key, None)
        key = message.message_id
        if key in self._entries:
            self._entries.move_to_end(key)
            self._entries[key] = now
            return True
        self._entries[key] = now
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return False
