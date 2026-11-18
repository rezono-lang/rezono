"""Load the validated input of an offline reconciliation run."""

import json
from pathlib import Path
from typing import TypedDict

from loop.typed_recording import TypedRecording, typed_recording


class Recording(TypedDict):
    run: str
    limit: int
    requirements: dict[str, list[str]]
    completion: dict[str, str]
    initial: list[list[str]]
    sweeps: list[list[list[str]]]


def unique_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"duplicate recording key {key!r}")
        data[key] = value
    return data


def nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_evidence(rows, label, run=None):
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a list of observations")
    for row in rows:
        if not isinstance(row, list) or len(row) != 3 or not all(map(nonempty_text, row)):
            raise ValueError(f"{label} observations require a run, token and evidence reference")
        if run is not None and row[0] != run:
            raise ValueError(f"{label} observation belongs to a different run")


def load_recording(path: str | Path) -> Recording | TypedRecording:
    """Validate a trace without evaluating it or changing its recorded order."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    typed_keys = {"run", "limit", "ports", "pack", "records", "initial", "sweeps"}
    if not isinstance(data, dict) or set(data) not in (typed_keys, set(Recording.__annotations__)):
        raise ValueError("recording must contain run, limit, requirements, completion, initial and sweeps")
    run, limit = data["run"], data["limit"]
    if not nonempty_text(run) or type(limit) is not int or limit <= 0:
        raise ValueError("recording requires a run ID and a positive integer round limit")
    if "pack" in data:
        return typed_recording(path.parent, data)

    requirements, completion = data["requirements"], data["completion"]
    if not isinstance(requirements, dict) or not isinstance(completion, dict) or requirements.keys() != completion.keys():
        raise ValueError("requirements and completion must declare the same steps")
    for step, tokens in requirements.items():
        if (not nonempty_text(step) or not isinstance(tokens, list)
                or not all(map(nonempty_text, tokens)) or not nonempty_text(completion[step])):
            raise ValueError("each step requires a token list and a completion token")

    validate_evidence(data["initial"], "initial evidence")
    if not isinstance(data["sweeps"], list):
        raise ValueError("sweeps must be an ordered list")
    for number, sweep in enumerate(data["sweeps"], 1):
        validate_evidence(sweep, f"sweep {number}", run)
    return data
