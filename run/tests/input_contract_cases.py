"""Independent replay contracts specified by decisions/run-external-evidence.md."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
DIGEST = "1" * 64


def verify(name, accepted, rejected):
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for record in accepted:
        validator.validate(record)
    for record in rejected:
        assert not validator.is_valid(record), record
    for key in accepted[0]:
        assert not validator.is_valid({k: v for k, v in accepted[0].items() if k != key})
