"""Stable boot and data disk identities from lsblk output and /dev/disk/by-id links."""

import json
from collections.abc import Mapping

_BY_ID = "/dev/disk/by-id/"


def _mounts(node: dict) -> list[str]:
    values = node.get("mountpoints") or []
    if not isinstance(values, list):
        raise ValueError("mountpoints must be a list")
    return [value for value in values if value is not None]


def _has_root(node: dict) -> bool:
    if "/" in _mounts(node):
        return True
    return any(_has_root(child) for child in node.get("children") or [])


def _free(node: dict) -> bool:
    return not node.get("children") and not node.get("fstype") and not _mounts(node)


def _identity(name: str, by_id: Mapping[str, str]) -> str:
    links = sorted(link for link, target in by_id.items() if target == name)
    if not links:
        raise ValueError(f"disk {name} has no by-id link")
    return _BY_ID + links[0]


def disks(lsblk_bytes: bytes, by_id: Mapping[str, str]) -> tuple[str, str]:
    """Return the by-id paths of the boot disk and the one free data disk."""
    try:
        devices = json.loads(lsblk_bytes)
        candidates = [d for d in devices["blockdevices"] if d.get("type") == "disk"]
        boot = [d for d in candidates if _has_root(d)]
        if len(boot) != 1:
            raise ValueError("expected exactly one root disk")
        free = [d for d in candidates if d is not boot[0] and _free(d)]
        if len(free) != 1:
            raise ValueError("expected exactly one free disk")
        return _identity(boot[0]["name"], by_id), _identity(free[0]["name"], by_id)
    except ValueError:
        raise
    except (TypeError, KeyError, AttributeError) as error:
        raise ValueError("unexpected lsblk structure") from error
