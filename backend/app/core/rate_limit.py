import time
from collections import defaultdict


class RateLimitExceededError(Exception):
    """Raised when a key has exceeded its allowed attempts within the current window."""


class FixedWindowRateLimiter:
    """In-memory fixed-window rate limiter.

    Per-process only: resets on restart, and doesn't coordinate across multiple API
    replicas — closes the "no rate limiting at all" gap on register/login, not a
    production-scale guarantee. A real multi-replica deployment needs a shared store
    (Redis/Postgres) instead; tracked as follow-up debt, not attempted here.
    """

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._window_start: dict[str, float] = {}
        self._counts: dict[str, int] = defaultdict(int)

    def check(self, key: str) -> None:
        """Records one attempt for `key`.

        Raises RateLimitExceededError once more than max_attempts have been recorded
        for the key within the current window. The window resets (count back to zero)
        the first time `check` is called after window_seconds has elapsed since it
        started — a fixed window, not a sliding one, so it can allow up to 2x
        max_attempts across a window boundary; acceptable for this pass.
        """
        now = time.monotonic()
        window_start = self._window_start.get(key)
        if window_start is None or now - window_start >= self._window_seconds:
            self._window_start[key] = now
            self._counts[key] = 0

        self._counts[key] += 1
        if self._counts[key] > self._max_attempts:
            raise RateLimitExceededError(key)
