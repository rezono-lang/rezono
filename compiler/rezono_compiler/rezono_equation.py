"""Lower named path equalities to the existing LinkML path equations."""

from .names import NAME
from .rezono_lowering import Refuse


def lower(equations: object, at: str, refuse: Refuse) -> list[dict[str, str]] | None:
    """Preserve the authored directions. The pack checks both paths against its resolved kinds."""
    if not isinstance(equations, list):
        refuse(at, "expected a list of named path equations", "§5.1")
        return None
    result: list[dict[str, str]] = []
    names: set[str] = set()
    for index, equation in enumerate(equations):
        here = f"{at}/{index}"
        if not isinstance(equation, dict) or equation.keys() != {"equal", "left", "right"}:
            refuse(here, "expected a named equality with left and right paths", "§5.1")
            continue
        name = equation["equal"]
        if not isinstance(name, str) or not NAME.fullmatch(name):
            refuse(here, "a path equation needs a valid name", "§5.1")
            continue
        if name in names:
            refuse(here, f"path equation {name} is written twice", "§5.1")
            continue
        names.add(name)
        left, right = equation["left"], equation["right"]
        if not all(isinstance(path, list) and path
                   and all(isinstance(step, str) and NAME.fullmatch(step) for step in path)
                   for path in (left, right)):
            refuse(here, f"path equation {name} needs two nonempty paths of slot names", "§5.1")
            continue
        result.append({"name": name, "left": ".".join(left), "right": ".".join(right)})
    return result if len(result) == len(equations) else None
