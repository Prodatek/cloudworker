import time
from unittest.mock import patch

import pytest

from app.core.rate_limit import FixedWindowRateLimiter, RateLimitExceededError


def test_allows_up_to_max_attempts_within_window() -> None:
    limiter = FixedWindowRateLimiter(max_attempts=3, window_seconds=60.0)

    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")


def test_blocks_the_attempt_past_max_within_window() -> None:
    limiter = FixedWindowRateLimiter(max_attempts=3, window_seconds=60.0)
    for _ in range(3):
        limiter.check("1.2.3.4")

    with pytest.raises(RateLimitExceededError):
        limiter.check("1.2.3.4")


def test_keys_are_independent() -> None:
    limiter = FixedWindowRateLimiter(max_attempts=1, window_seconds=60.0)

    limiter.check("1.2.3.4")
    limiter.check("5.6.7.8")  # different key, its own budget — must not raise


def test_resets_after_the_window_elapses() -> None:
    limiter = FixedWindowRateLimiter(max_attempts=1, window_seconds=10.0)
    start = time.monotonic()

    with patch("app.core.rate_limit.time.monotonic", return_value=start):
        limiter.check("1.2.3.4")
        with pytest.raises(RateLimitExceededError):
            limiter.check("1.2.3.4")

    with patch("app.core.rate_limit.time.monotonic", return_value=start + 10.1):
        limiter.check("1.2.3.4")  # new window, budget is back
