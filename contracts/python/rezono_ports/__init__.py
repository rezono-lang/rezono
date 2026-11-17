"""Port declarations held to contracts/port.yaml at run time (PC3, decision O12a). Written by hand.

A port reads its own declaration with `load` before it does anything, so a declaration that is not a valid
port of its kind never runs: an in-port that would write anything but observations, an out-port on anything
but a checked epoch, an effect without plan, apply and status. `invocation` names one call: the record
PortInvocation of the contract, with the input hash that identifies the attempt.

This module states no rule of the contract's shape. The check is the JSON Schema that contracts/gen-types.sh
makes of contracts/port.yaml (rezono_contracts/port.schema.json), the schema LinkML's own validator checks
against; the contract's fixtures hold this module to their verdicts (tests/test_runtime.py).

What the contract can only name is what a port runs on. `refusal` says it for `checked_epoch` (PC4): a port
that reads a published manifest asks it first, and reads no row of a what-if (`what_if`: the manifest of a
proposal or of a variant is checked, and it is not an epoch of main) or of an epoch the checker did not
accept (`unchecked`).
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from pathlib import Path

import yaml
from jsonschema import validators

# The operation name of a call of an in-port and of an out-port (PortInvocation.operation in the contract).
# An effect's three names come from its declaration.
FIXED = {"in": "read", "out": "write"}

# The statuses of a check in an epoch the checker accepted (contracts/manifest.yaml, CheckStatus). `red` blocks
# publication. `unavailable` is what the gate gives a role that may not read the rows a check is derived from:
# that role does not know the check is green, so neither does a port that reads as that role.
ACCEPTED = ("green", "warning")

# A manifest without check results is refused on purpose: a checked epoch carries the result of every check,
# so one that carries none was not checked, whatever its pack would have needed.
NO_RESULTS = "it carries no check results, and a checked epoch carries the result of every check"


class PortError(ValueError):
    """A declaration or an invocation the port contract refuses."""


@cache
def _validator(cls: str):
    schema = json.loads(resources.files("rezono_contracts").joinpath("port.schema.json").read_text("utf-8"))
    one = {"$schema": schema["$schema"], "$ref": f"#/$defs/{cls}", "$defs": schema["$defs"]}
    return validators.validator_for(one)(one)


def errors(doc, cls: str = "Port") -> list[str]:
    """What the contract has against `doc` as a `cls` (Port or PortInvocation), sorted; empty when valid."""
    return sorted(f"{'/'.join(str(p) for p in e.absolute_path) or '.'}: {e.message}"
                  for e in _validator(cls).iter_errors(doc))


def load(path: str | Path, kind: str | None = None) -> dict:
    """The declaration in `path`. PortError, with everything the contract has against it, when it is no port,
    or when the caller is a port of `kind` and the declaration is of another."""
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise PortError(f"{path}: no readable port declaration: {e}") from e
    found = errors(doc)
    if found:
        raise PortError(f"{path}: not a port (contracts/port.yaml): " + "; ".join(found))
    if kind is not None and doc["kind"] != kind:
        raise PortError(f"{path}: a port of kind {doc['kind']!r}, not {kind!r}")
    return doc


def unchecked(manifest) -> list[str]:
    """Why `manifest` is not a checked epoch (PortInput `checked_epoch`: a published epoch the checker
    accepted), sorted; empty when it is one. A checked epoch carries the result of every check, and none of
    them has a status that blocks publication. A manifest without results was not checked; it is not green."""
    checks = manifest.get("checks") if isinstance(manifest, dict) else None
    if not isinstance(checks, list) or not checks:
        return [NO_RESULTS]
    return sorted(f"check {c.get('name')!r} is {c.get('status')!r}" if isinstance(c, dict)
                  else f"check result {c!r} is no record"
                  for c in checks if not isinstance(c, dict) or c.get("status") not in ACCEPTED)


def what_if(manifest) -> list[str]:
    """Why `manifest` is a what-if and not an epoch of main (contracts/manifest.yaml), sorted; empty when it is
    one of main. `proposal` is empty on main (the publisher leaves the key out there), and `variant` is set
    only on a variant, which is never the current state of main. A what-if can have every check green: it is
    checked, and nobody decided it."""
    if not isinstance(manifest, dict):
        return []
    found = []
    if manifest.get("proposal"):
        found.append(f"it is the manifest of proposal {manifest['proposal']!r}")
    variant = manifest.get("variant")
    if variant is not None:
        # Only the grid position: the variant's role lists are for the access gate and go to no reader.
        found.append(f"it is variant {variant.get('index')!r} of sweep {variant.get('sweep')!r}"
                     if isinstance(variant, dict) else f"it is variant {variant!r}")
    return sorted(found)


def refusal(manifest) -> str:
    """Why a port may not read `manifest`, as one sentence; empty when it is a checked epoch of main. The one
    question every reader of a published manifest asks before it reads a row, for a port of kind `out` and of
    kind `in` alike. A what-if is named as one, and is not called unchecked."""
    found = what_if(manifest)
    if found:
        return "a what-if, not a published epoch: " + "; ".join(found)
    found = unchecked(manifest)
    return "not a checked epoch: " + "; ".join(found) if found else ""


def operations(port: dict) -> tuple[str, ...]:
    """The operation names a call of this port may carry."""
    if port["kind"] == "effect":
        return tuple(port["effect"][step] for step in ("plan", "apply", "status"))
    return (FIXED[port["kind"]],)


def invocation(port: dict, operation: str, unit: str, input_sha256: str) -> dict:
    """The record of one call of a loaded port (PortInvocation). PortError for an operation the port does
    not declare, or a record the contract refuses (an input hash that is not 64 lower-case hex digits)."""
    if operation not in operations(port):
        raise PortError(f"port {port['name']}: no operation {operation!r}; it declares {', '.join(operations(port))}")
    call = {"port": port["name"], "kind": port["kind"], "operation": operation, "unit": unit,
            "input_sha256": input_sha256}
    if port.get("image"):
        call["image"] = port["image"]
    found = errors(call, "PortInvocation")
    if found:
        raise PortError(f"port {port['name']}: not an invocation (contracts/port.yaml): " + "; ".join(found))
    return call
