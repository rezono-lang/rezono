"""Compare an authored declaration with an independently authored public LinkML schema."""

from pathlib import Path

import yaml

from rezono_compiler import rezono_module


EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def kind(name, *slots, **properties):
    return {"kind": name, "world": "closed", "slots": list(slots), "derived": [], **properties}


def slot(name, type_name, **properties):
    return {"slot": name, "type": type_name, **properties}


def compare_input(directory, example, declaration, external=()):
    form = {
        "format": "rezono.module/2", "spans": [],
        "module": {"rezono": "0", "pack": example, "use": [], "decls": [declaration]},
    }
    entry = rezono_module.Declared("rezono/part.rezono", "rezono/part.json", "facts")
    errors = []
    result = rezono_module.lower(directory, entry, form, example, {name: ["context"] for name in external}, errors)
    assert not errors, errors
    source = EXAMPLES / example / "schema" / f"{example}.yaml"
    return result.schema, yaml.safe_load(source.read_text(encoding="utf-8"))
