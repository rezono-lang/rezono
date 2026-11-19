"""Compare an authored declaration with an independently authored public LinkML schema."""

from pathlib import Path

import yaml

from rezono_compiler import rezono_module


ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "examples"


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
    """A public LinkML schema of this repository, read as data."""
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def compare_input(directory, example, declaration, external=()):
    actual = lower_declarations(directory, example, [declaration], external)
    return actual, schema_file(f"examples/{example}/schema/{example}.yaml")
