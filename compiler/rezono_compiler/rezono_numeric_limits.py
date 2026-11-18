"""Lower inclusive integer slot limits to the shared LinkML facets."""

import re


INTEGER = re.compile(r"-?(?:0|[1-9][0-9]*)")
FACETS = {"minimum": "minimum_value", "maximum": "maximum_value"}


def lower(constraints: object) -> dict[str, int]:
    if not isinstance(constraints, list) or not constraints:
        raise ValueError("integer limits need a nonempty list of constraints")
    from .pack import BIGINT  # The pack loader also consumes these LinkML facets.

    out: dict[str, int] = {}
    for constraint in constraints:
        if not isinstance(constraint, dict) or len(constraint) != 1:
            raise ValueError("an integer limit needs one minimum or maximum")
        name, raw = next(iter(constraint.items()))
        if name not in FACETS:
            raise ValueError("only minimum and maximum are lowered as integer limits")
        facet = FACETS[name]
        if facet in out:
            raise ValueError(f"the {name} limit is written twice")
        if not isinstance(raw, str) or len(raw) > len(str(BIGINT[0])) or INTEGER.fullmatch(raw) is None:
            raise ValueError(f"the {name} limit must be a decimal whole number within BIGINT")
        value = int(raw)
        if not BIGINT[0] <= value <= BIGINT[1]:
            raise ValueError(f"the {name} limit must be a decimal whole number within BIGINT")
        out[facet] = value
    low, high = out.get("minimum_value"), out.get("maximum_value")
    if low is not None and high is not None and low > high:
        raise ValueError("the minimum limit is above the maximum")
    return out
