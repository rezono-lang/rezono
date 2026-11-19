"""Load an admission binding and validate it against its JSON Schema.

See decisions/k8s-admission-binding-checks.md, "Schema".
"""

import json
from pathlib import Path

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).parent / "resources" / "admission-binding.schema.json"


def _place(error):
    return "/".join(str(part) for part in error.absolute_path) or "(document)"


def load_binding(text: str) -> dict:
    """Parse YAML text and return the binding; raise ValueError naming the offending key."""
    try:
        binding = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"Admission binding is not valid YAML: {error}") from error
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(binding),
        key=lambda error: (_place(error), error.message),
    )
    if errors:
        raise ValueError("; ".join(f"{_place(error)}: {error.message}" for error in errors))
    return binding
