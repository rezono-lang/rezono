"""Retry delivery status publication through an injected status port."""

from collections.abc import Callable, Mapping
from threading import Lock
from weakref import WeakValueDictionary

StatusKey = tuple[str, str]
Status = Mapping[str, str]

_locks = WeakValueDictionary()
_locks_guard = Lock()


def publish(
    key: StatusKey,
    value: Status,
    read: Callable[[StatusKey], Status | None],
    write: Callable[[StatusKey, Status], None],
    *,
    supersedes: Callable[[Status], bool] | None = None,
) -> None:
    """Read before writing, including after a write with an uncertain outcome."""
    with _locks_guard:
        key_lock = _locks.setdefault(key, Lock())

    with key_lock:
        latest = read(key)
        if latest is not None and (all(latest.get(field) == item for field, item in value.items())
                                   or (supersedes is not None and supersedes(latest))):
            return
        write(key, value)
