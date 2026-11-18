"""Lower bounded lists to the cardinality facets shared by both compiler engines."""

import re


COUNT = re.compile(r"0|[1-9][0-9]*")


def bounded_list(card: str | None, constraints: object) -> dict[str, int | bool]:
    """Read one authored cardinality range on a multivalued slot."""
    if card not in ("*", "+"):
        raise ValueError("a cardinality range needs a list slot (`*` or `+`)")
    if not isinstance(constraints, list) or len(constraints) != 1:
        raise ValueError("a bounded list needs one cardinality range")
    constraint = constraints[0]
    if not isinstance(constraint, dict) or constraint.keys() != {"cardinality"}:
        raise ValueError("only a cardinality range is lowered on a bounded list")
    limits = constraint["cardinality"]
    if not isinstance(limits, list) or len(limits) != 2:
        raise ValueError("a cardinality range needs a minimum and a maximum")
    from .pack import BIGINT  # Pack lowering imports this component before defining the engine range.

    maximum = BIGINT[1]
    if not all(isinstance(limit, str) and len(limit) <= len(str(maximum)) and COUNT.fullmatch(limit)
               and int(limit) <= maximum for limit in limits):
        raise ValueError("cardinality bounds must be nonnegative whole numbers in the engine range")
    low, high = (int(limit) for limit in limits)
    if low > high:
        raise ValueError("the minimum cardinality is above the maximum")
    if card == "+" and low == 0:
        raise ValueError("a `+` list needs a minimum cardinality of at least one")
    result = {"multivalued": True, "minimum_cardinality": low, "maximum_cardinality": high}
    if card == "+":
        result["required"] = True
    return result
