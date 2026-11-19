# --- The operation file -------------------------------------------------------------------------------------

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .. import strict_yaml
from ..pack import contract_dir


FORMAT = "rezono.operations/1"
IMPACT = "rezono.impact/1"
OPS = ("rename", "move", "drop", "split_by", "combine", "select")
BUILT = OPS
FIELDS = ("op", "kind", "slot", "enum", "value", "to", "via", "absorb", "key", "cases", "abstract", "world",
          "accept_loss", "accept_access", "keep", "omit")
PARAMETERS = ("minimum", "maximum", "minimum_cardinality", "maximum_cardinality", "constant")
CONDITIONS = ("preconditions", "postconditions", "elseconditions")
REF = re.compile(r"^(?:(?P<module>[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*)#)?(?P<name>[^#./]+)$")
CLASS_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
OUTCOME = re.compile(r"^([ \t]*//[ \t]*@outcome[ \t]+)(\S+)", re.M)
PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-/%]*$")
FACT_DIRS = ("facts", "scenarios", "diagnostics")


class OperationError(Exception):
    pass


@lru_cache(maxsize=1)
def _operation_set_fields() -> frozenset[str]:
    contract = strict_yaml.read(contract_dir() / "operation.yaml")
    return frozenset(contract["classes"]["OperationSet"]["attributes"])


def load(path: str | Path) -> dict:
    doc = strict_yaml.read(path)
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise OperationError(f"{path}: not an operation set ({FORMAT})")
    fields = _operation_set_fields()
    unknown = [f"{path}: unknown operation set field {field!r}" for field in doc if field not in fields]
    if unknown:
        raise OperationError("\n".join(unknown))
    ops = doc.get("operations")
    if not isinstance(ops, list) or not ops:
        raise OperationError(f"{path}: no operations")
    errors = []
    for i, op in enumerate(ops):
        where = f"operation {i}"
        if not isinstance(op, dict):
            errors.append(f"{where}: not a mapping")
            continue
        errors += [f"{where}: unknown field '{k}'" for k in op if k not in FIELDS]
        if op.get("op") != "select":
            errors += [f"{where}: {op.get('op')} takes no '{k}'" for k in ("keep", "omit") if k in op]
        if op.get("op") not in OPS:
            errors.append(f"{where}: op must be one of {', '.join(OPS)}")
        elif op["op"] not in BUILT:
            errors.append(f"{where}: {op['op']} is not built yet")
        elif op["op"] == "select":
            from ..selection import validate
            errors += validate(op, where)
        elif op["op"] == "rename":
            if bool(op.get("kind")) == bool(op.get("enum")):
                errors.append(f"{where}: rename names a kind (with or without a slot) or an enum (with or "
                              f"without a value)")
            if op.get("slot") and not op.get("kind") or op.get("value") is not None and not op.get("enum"):
                errors.append(f"{where}: a slot belongs to a kind, a value to an enum")
            if not isinstance(op.get("to"), str) or not op["to"]:
                errors.append(f"{where}: rename needs 'to'")
            extra = [k for k in ("via", "absorb", "key", "cases", "abstract", "world", "accept_access") if k in op]
            errors += [f"{where}: rename takes no '{k}'" for k in extra]
        elif op["op"] == "drop":
            if not op.get("kind"):
                errors.append(f"{where}: drop needs 'kind' (and 'slot' to drop a slot)")
            if op.get("accept_loss") is not True:
                errors.append(f"{where}: drop always loses data; it needs accept_loss: true")
            extra = [k for k in ("enum", "value", "to", "via", "absorb", "key", "cases", "abstract", "world",
                                 "accept_access") if k in op]
            errors += [f"{where}: drop takes no '{k}'" for k in extra]
        elif op["op"] == "move":
            if not (op.get("kind") and op.get("slot") and isinstance(op.get("to"), str) and op["to"]):
                errors.append(f"{where}: move needs 'kind', 'slot' and 'to'")
            if op.get("world") not in (None, "open", "closed"):
                errors.append(f"{where}: world is open or closed")
            if "accept_access" in op and op["accept_access"] is not True:
                errors.append(f"{where}: accept_access is true or absent")
            extra = [k for k in ("enum", "value", "absorb", "key", "cases", "abstract") if k in op]
            errors += [f"{where}: move takes no '{k}'" for k in extra]
        elif op["op"] == "split_by":
            cases = op.get("cases")
            if not (op.get("kind") and op.get("slot")) or not isinstance(cases, list) or not cases:
                errors.append(f"{where}: split_by needs 'kind', 'slot' and 'cases'")
            else:
                if any(not isinstance(c, dict) or set(c) != {"value", "kind"} for c in cases):
                    errors.append(f"{where}: a case is {{value, kind}}")
                else:
                    for f_ in ("value", "kind"):
                        xs = [str(c[f_]) for c in cases]
                        if len(set(xs)) != len(xs):
                            errors.append(f"{where}: two cases share a {f_}")
            if "abstract" in op and not isinstance(op["abstract"], bool):
                errors.append(f"{where}: abstract is true or false")
            extra = [k for k in ("enum", "value", "to", "via", "absorb", "key", "world", "accept_access") if k in op]
            errors += [f"{where}: split_by takes no '{k}'" for k in extra]
        elif op["op"] == "combine":
            if not (op.get("kind") and op.get("absorb") and isinstance(op.get("via"), str) and op["via"]):
                errors.append(f"{where}: combine needs 'kind', 'absorb' and 'via'")
            if "key" in op and not (isinstance(op["key"], str) and op["key"]):
                errors.append(f"{where}: key is a slot name")
            if op.get("world") not in (None, "open", "closed"):
                errors.append(f"{where}: world is open or closed")
            if "accept_access" in op and op["accept_access"] is not True:
                errors.append(f"{where}: accept_access is true or absent")
            extra = [k for k in ("slot", "enum", "value", "to", "cases", "abstract") if k in op]
            errors += [f"{where}: combine takes no '{k}'" for k in extra]
        if "accept_loss" in op and op["accept_loss"] is not True:
            errors.append(f"{where}: accept_loss is true or absent")
    if errors:
        raise OperationError("\n".join(errors))
    return doc
