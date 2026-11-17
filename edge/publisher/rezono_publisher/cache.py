"""A sweep's immutable base and current variant, kept locally for its difference reader.

This is not a storage policy: every write still reaches conditional put_new. Heads and lists are never
cached, and a missing object only under the base: the base is published before its sweep and the sweep writes
nothing under it, so what it lacks is asked once, not once per variant. The cache lives for one sweep, and
drops the previous variant at each value.
"""

from __future__ import annotations

import json
import re
from threading import Lock


class SweepStore:
    def __init__(self, st, pack: str, base: str):
        self.st, self.pack, self.base = st, pack, base
        self.variant: str | None = None
        self._cache: dict[str, bytes | None] = {}
        self._lock = Lock()  # publish.put_all writes different objects concurrently
        self._counts = {"get": 0, "hit": 0, "put": 0, "get_bytes": 0, "put_bytes": 0}

    def _cacheable(self, key: str) -> bool:
        if key.startswith((f"{self.pack}/bundles/", f"{self.pack}/objects/")):
            return True  # archived compiler output and published objects, addressed by hashes: never changed
        for mid in (self.base, self.variant):
            if mid and (key.startswith(f"{self.pack}/{mid}/") or
                        key == f"{self.pack}/manifests/{mid}.json" or
                        (mid == self.variant and key == f"{self.pack}/diagnoses/{mid}.json")):
                return True
        return False

    def _base_objects(self) -> set[str]:
        """The keys of the objects the base's manifest names (shared, so outside the base's prefix)."""
        data = self._cache.get(f"{self.pack}/manifests/{self.base}.json")
        if not data:
            return set()
        from .publish import named

        try:
            return {re.sub(r"^s3://[^/]+/", "", uri) for uri in named(json.loads(data))}
        except (ValueError, TypeError, KeyError, AttributeError):
            return set()  # not a manifest the cache can read: keep none of the objects, which is only slower

    def begin(self, variant: str) -> dict[str, int]:
        """Retain the base, forget the previous variant; return counters before the next value."""
        with self._lock:
            self.variant = variant
            base = self._base_objects()
            self._cache = {k: v for k, v in self._cache.items() if self._cacheable(k) and
                           (not k.startswith(f"{self.pack}/objects/") or k in base)}
            return dict(self._counts)

    def counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def uri(self, key: str) -> str:
        return self.st.uri(key)

    def list(self, prefix: str) -> list[str]:
        return self.st.list(prefix)

    def get(self, key: str) -> bytes | None:
        with self._lock:
            if key in self._cache:
                self._counts["hit"] += 1
                return self._cache[key]
            self._counts["get"] += 1
        data = self.st.get(key)
        with self._lock:
            if data is not None:
                self._counts["get_bytes"] += len(data)
                if self._cacheable(key):
                    self._cache[key] = data
            elif key.startswith(f"{self.pack}/{self.base}/"):
                self._cache.setdefault(key, None)  # the base lacks it (a role's view index, for one): asked once a sweep; never over a write that came meanwhile
        return data

    def put_new(self, key: str, data: bytes) -> None:
        with self._lock:
            self._counts["put"] += 1
            self._counts["put_bytes"] += len(data)
        self.st.put_new(key, data)  # never skip the store's conflict check, even on a cache hit
        with self._lock:
            if self._cacheable(key):
                self._cache[key] = data
