"""In-memory store of pending clear-list confirmations, keyed by sender.

State is intentionally not persisted: on restart a pending clear is simply
forgotten and the user asks again. No data-loss risk.
"""

import time

# sender -> (expiry_epoch, item_count_at_request_time)
_pending: dict[str, tuple[float, int]] = {}

TTL_SECONDS = 120


def set_pending(sender: str, item_count: int) -> None:
    _pending[sender] = (time.monotonic() + TTL_SECONDS, item_count)


def take_pending(sender: str) -> int | None:
    """Return and consume the pending item-count for sender, or None if there
    is no live pending clear."""
    entry = _pending.pop(sender, None)
    if entry is None:
        return None
    expiry, count = entry
    if time.monotonic() > expiry:
        return None
    return count


def clear_pending(sender: str) -> None:
    _pending.pop(sender, None)


def has_pending(sender: str) -> bool:
    entry = _pending.get(sender)
    if entry is None:
        return False
    if time.monotonic() > entry[0]:
        _pending.pop(sender, None)
        return False
    return True
