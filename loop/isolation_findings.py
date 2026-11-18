"""Compare recorded isolation witnesses with independent fixture expectations."""

from collections import defaultdict
from collections.abc import Iterable, Mapping


_LAYERS = ("router", "service")
_VERDICTS = ("allow", "deny")


def findings(
    cases: Iterable[Mapping[str, object]], witnesses: Iterable[Mapping[str, str]]
) -> list[dict[str, str]]:
    """Report mismatches per case, enforcement layer and distinct observation."""
    expected: dict[tuple[str, str], str] = {}
    case_ids: set[str] = set()
    for case in cases:
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in case_ids:
            raise ValueError(f"invalid or duplicate fixture case ID: {case_id!r}")
        case_ids.add(case_id)
        for layer in _LAYERS:
            verdict = case.get(layer)
            if verdict in _VERDICTS:
                expected[case_id, layer] = verdict
            elif verdict != "inapplicable":
                raise ValueError(f"invalid {layer} expectation for {case_id!r}")

    observed: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for witness in witnesses:
        key = (witness["case"], witness["layer"])
        verdict, reference = witness["verdict"], witness["ref"]
        if key not in expected or verdict not in _VERDICTS or not reference:
            raise ValueError(f"invalid isolation witness for {key!r}")
        observed[key].add((verdict, reference))

    result = []
    for key, desired in sorted(expected.items()):
        records = observed[key]
        if len({verdict for verdict, _ in records}) != 1:
            raise ValueError(f"missing or conflicting isolation evidence for {key!r}")
        case_id, layer = key
        for verdict, reference in sorted(records):
            if verdict != desired:
                result.append({"case": case_id, "layer": layer, "expected": desired,
                               "observed": verdict, "evidence": reference})
    return result
