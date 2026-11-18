"""Check the literal flag values left open by the native module LinkML shape."""

import json
from functools import lru_cache

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


NATIVE_FORMAT = "rezono.module/3"
LITERALS_SCHEMA = "rezono-module-literals.schema.json"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    from .pack import contract_dir

    schema = json.loads((contract_dir() / LITERALS_SCHEMA).read_bytes())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def native_literal_errors(document: object) -> list[str]:
    """Report native marker errors with JSON paths, using the packaged contract when installed."""
    if not isinstance(document, dict) or document.get("format") != NATIVE_FORMAT:
        return []

    from .pack import CompileError

    try:
        validator = _validator()
    except (CompileError, OSError, ValueError, SchemaError):
        return [f"cannot read or validate the {LITERALS_SCHEMA} contract"]
    return sorted(f"{error.json_path}: {error.message}" for error in validator.iter_errors(document))
