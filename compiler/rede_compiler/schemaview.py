"""LinkML's SchemaView with its memo kept on the instance, so the memo goes when the view goes.

linkml-runtime decorates about seventy SchemaView methods with `functools.lru_cache` on the class. That cache is
keyed on the instance and every instance hashes by its own uuid, so each SchemaView ever made, with every answer it
gave, stays alive as long as the process: a test that reads 5,000 generated packs kept some 30 MiB per pack and
lost its runner at 8 GiB (nightly `compiler`, 15-11-2026). This subclass gives each instance its own caches of
the same sizes, wrapping the same functions, so answers are unchanged and the memory is freed with the view.
"""
from __future__ import annotations

import functools
import types

from linkml_runtime import SchemaView as _SchemaView

# The memoized methods of the class: name -> (undecorated function, maxsize). Read once, at import.
_MEMOIZED = {name: (attr.__wrapped__, attr.cache_parameters()["maxsize"])
             for cls in reversed(_SchemaView.__mro__) for name, attr in vars(cls).items()
             if callable(getattr(attr, "cache_clear", None)) and hasattr(attr, "__wrapped__")}


class SchemaView(_SchemaView):
    def __init__(self, *args, **kwargs) -> None:
        self._own_caches()  # before the base reads anything, so no answer lands in the class's cache
        super().__init__(*args, **kwargs)

    def _own_caches(self) -> None:
        for name, (fn, maxsize) in _MEMOIZED.items():
            setattr(self, name, functools.lru_cache(maxsize)(types.MethodType(fn, self)))

    def set_modified(self) -> None:
        """A change to the schema invalidates every answer, as the base's new hash does for the class's cache."""
        super().set_modified()
        for name in _MEMOIZED:
            cached = self.__dict__.get(name)
            if cached is not None:
                cached.cache_clear()

    def __getstate__(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in _MEMOIZED}

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._own_caches()
