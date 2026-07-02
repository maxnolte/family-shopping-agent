"""Per-sender token-bucket rate limiter (in-memory).

Defaults to 30 messages/minute per sender with a small burst allowance.
"""

import time

RATE_PER_MINUTE = 30
BURST = 10

_refill_per_second = RATE_PER_MINUTE / 60.0

# sender -> (tokens, last_refill_monotonic)
_buckets: dict[str, tuple[float, float]] = {}


def allow(sender: str) -> bool:
    """Consume one token for sender. Return True if allowed, False if the
    sender is over their rate limit."""
    now = time.monotonic()
    tokens, last = _buckets.get(sender, (float(BURST), now))

    tokens = min(BURST, tokens + (now - last) * _refill_per_second)

    if tokens < 1.0:
        _buckets[sender] = (tokens, now)
        return False

    _buckets[sender] = (tokens - 1.0, now)
    return True
