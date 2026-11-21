"""Compare an authored declaration with an independently authored public LinkML schema."""

from functools import cache
import importlib.util
from pathlib import Path

import yaml

from rezono_compiler import rezono_module


ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"
LEGACY_HELPERS_PATH = ROOT / "examples" / "fixtures" / "rezono-1-legacy" / "helpers.py"


@cache
def legacy_helpers():
    """Load the shared legacy-pack archive helper module."""
    spec = importlib.util.spec_from_file_location("rezono_1_legacy_helpers", LEGACY_HELPERS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@cache
def _legacy_archive_files() -> dict[str, bytes]:
    """Flatten the shared legacy archive to `{repo_relative_posix: bytes}`."""
    by_pack = legacy_helpers().read_legacy_archive()
    return {
        f"{pack_rel}/{file_rel}": data
        for pack_rel, files in by_pack.items()
        for file_rel, data in files.items()
    }


@cache
def _legacy_archive_pack_roots() -> tuple[str, ...]:
    """Archived legacy pack roots, longest first so nested packs match before parents."""
    return tuple(sorted(legacy_helpers().read_legacy_archive(), key=len, reverse=True))


def legacy_file_bytes(relative: str) -> bytes:
    """Return raw bytes for `relative`, preferring live files until the owning pack converts to `rezono 1`."""
    key = Path(relative).as_posix()
    helpers = legacy_helpers()
    owner = next((pack_rel for pack_rel in _legacy_archive_pack_roots() if key.startswith(pack_rel + "/")), None)
    if owner is not None:
        live_pack = ROOT / owner
        live_file = ROOT / key
        if live_pack.is_dir() and not helpers.pack_is_rezono_1(live_pack) and live_file.is_file():
            return live_file.read_bytes()
    archived = _legacy_archive_files().get(key)
    if archived is not None:
        return archived
    return (ROOT / key).read_bytes()


def kind(name, *slots, **properties):
    return {"kind": name, "world": "closed", "slots": list(slots), "derived": [], **properties}


def slot(name, type_name, **properties):
    return {"slot": name, "type": type_name, **properties}


def lower_declarations(directory, pack_name, declarations, external=(), header=None):
    """Lower hand-written declarations through the ordinary module lowering; return the LinkML schema."""
    form = {
        "format": "rezono.module/2", "spans": [],
        "module": {"rezono": "0", "pack": pack_name, "use": [], **(header or {}), "decls": list(declarations)},
    }
    entry = rezono_module.Declared("rezono/part.rezono", "rezono/part.json", "facts")
    errors = []
    result = rezono_module.lower(directory, entry, form, pack_name, {name: ["context"] for name in external}, errors)
    assert not errors, errors
    return result.schema


def schema_file(relative):
    """A public LinkML schema of this repository (read from the shared legacy archive when frozen), as data."""
    return yaml.safe_load(legacy_file_bytes(relative).decode("utf-8"))


def compare_input(directory, example, declaration, external=()):
    actual = lower_declarations(directory, example, [declaration], external)
    return actual, schema_file(f"examples/{example}/schema/{example}.yaml")
