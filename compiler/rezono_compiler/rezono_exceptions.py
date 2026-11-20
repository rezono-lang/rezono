"""Lower ordered `unless` exception blocks to `rezono.calc/1` definitions (decisions/language-exceptions.md).

Each `unless` block lowers after the base value: lines in block `i` override `base` and every
definition from earlier blocks `1 .. i-1`, while sibling lines within block `i` do not override
one another. That preserves v0 section 5b precedence, sibling conflict (`invalid`), and
unknown-condition propagation (`unknown`) using `rezono.calc/1` `overrides`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def lower_unless(
    rule_id: str,
    base_value: Any,
    unless_blocks: Sequence[Sequence[Mapping[str, Any]]],
    lower_expr: Callable[[Any], dict],
) -> list[dict]:
    """Lower a derived value's base expression and ordered `unless` blocks to `rezono.calc/1` definitions."""
    definitions: list[dict] = [
        {"name": "base", "when": {"boolean": True}, "value": lower_expr(base_value)},
    ]
    earlier = ["base"]
    for block_idx, block in enumerate(unless_blocks, start=1):
        block_names: list[str] = []
        for line_idx, line in enumerate(block, start=1):
            name = f"unless_{block_idx}_{line_idx}"
            reason = line.get("source") or "unless"
            definitions.append({
                "name": name,
                "when": lower_expr(line["when"]),
                "value": lower_expr(line["then"]),
                "overrides": [
                    {"definition": f"{rule_id}#{target}", "reason": reason}
                    for target in earlier
                ],
            })
            block_names.append(name)
        earlier.extend(block_names)
    return definitions
