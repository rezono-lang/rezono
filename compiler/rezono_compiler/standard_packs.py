"""The standard packs: which `std-*` names exist and the pack hash of each (decisions/standard-pack-names.md).

A name `std-*` stands only for the bytes of `packs/<name>` at the compiler's revision. TABLE is generated from
`packs/`; `python -m rezono_compiler.standard_packs <repository root>` prints it. Adding or changing a standard
pack means regenerating TABLE in the same change.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

PREFIX = "std-"

TABLE: dict[str, str] = {
    "std-access": "8e004b9bd062be365acfb3db30d9bb26fe393c3b979bd77e8d69fc60aae111e6",
    "std-budget": "544caa9bfd0dce236640427c3cbce9216122d5f20121c9a38e935ffdd4d6f945",
    "std-decision": "2fd4cc60cc4f1c7dca42da2f5368a08a992de39df7cd7db205b9118dd1b8fe5a",
    "std-explain": "72e2897cd9baaa4962cf2235f83a332262b4da1e6d34e82d5f64d8335e27be0b",
    "std-identity": "129e5321602dea3b58ea5220103c4d313237d0dbf5e640c677b24fc98e5d265b",
    "std-loop": "20808ce966d574b02e11e814f755d6be0539cef3bec1ed5be1bcba69c11b3919",
    "std-order": "6c56982cfaa6535835b594be2fb280655795a96f0308d8e5d423c6040f923495",
    "std-part": "207f4f097f68e6dade792b714754e0f279ce2c948be8adce82108a3abc18cca9",
    "std-review": "e63d22dd816ad23dff6d7b9d3bb222f0a20e11c79126bf4e9c1157998e564c35",
    "std-time": "bb2863a03792228005fa6784ed1022c07ac82139cdbf0ff7914cd273b3e046a7",
    "std-view": "a544468e9e64efbe31dfc5ccf72f1eccbf508dafc55f7087a39ab9b4dd4bff60",
}

# Candidate bytes admitted under a standard name while a converter compares them with that standard pack.
_TRIALS: ContextVar[dict[str, str]] = ContextVar("standard_pack_trials", default={})


@contextmanager
def trial(name: str, digest: str) -> Iterator[None]:
    """Admit `digest` under the standard name `name` within this block, for a conversion trial only.

    A converted standard pack has new bytes before the table is regenerated with them. The converter
    compiles it beside the standard pack to prove the meaning is unchanged; nothing outside the block
    sees the candidate as standard.
    """
    token = _TRIALS.set({**_TRIALS.get(), name: digest})
    try:
        yield
    finally:
        _TRIALS.reset(token)


def is_standard_name(name: str) -> bool:
    return name.startswith(PREFIX)


def refusal(name: str, digest: str) -> str | None:
    """Why a pack named `name` with these bytes may not carry a `std-*` name; None if it may."""
    if not is_standard_name(name):
        return None
    if name not in TABLE:
        return f"{name} is not a standard pack: the name std-* is reserved for the standard packs"
    if TABLE[name] != digest and _TRIALS.get().get(name) != digest:
        return (f"{name} is reserved for the standard pack with hash {TABLE[name]}, "
                f"but these files hash to {digest}")
    return None


def generate(root: Path) -> dict[str, str]:
    from .modules import pack_hash
    return {p.name: pack_hash(p) for p in sorted((root / "packs").glob(PREFIX + "*")) if (p / "pack.yaml").is_file()}


if __name__ == "__main__":
    for key, value in generate(Path(sys.argv[1] if len(sys.argv) > 1 else ".")).items():
        print(f'    "{key}": "{value}",')
