"""Check turning points between two neighbouring stops of a sweep (decisions/viewer-slip.md).

This module independently derives the turning points between `before` and `after` from the
stops' rows, witnesses, calculation witnesses, column types, and calculation program, sharing
no code with the publisher. It verifies that `listed` names every turning conclusion and no
other, with the exact sorted causes, in `(relation, key)` order.
"""

from __future__ import annotations

from collections import defaultdict

from . import access
from .canon import canonical_json, number, strict_json_loads

CAUSES = frozenset({
    "rule",
    "version",
    "definition",
    "path",
    "count",
    "contributors",
    "state",
    "presence",
    "value",
    "cap",
})
VALUE_TYPES = frozenset({"reference", "enum", "boolean"})
NON_KNOWN_STATES = frozenset({"unknown", "not_applicable", "invalid"})
BOOLEAN_TEXT = frozenset({"true", "false"})


def _parse_key(key: str) -> tuple[str, ...]:
    parts = strict_json_loads(key)
    if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
        raise ValueError(f"malformed row key: {key!r}")
    return tuple(parts)


def _index_program(
    program: dict | None,
) -> tuple[set[str], dict[tuple[str, str], dict], dict[str, str]]:
    """Index calculation views, versions by `(rule, version)`, and rule value types."""
    calc_views: set[str] = set()
    versions: dict[tuple[str, str], dict] = {}
    rule_types: dict[str, str] = {}
    if not isinstance(program, dict):
        return calc_views, versions, rule_types
    for rule in program.get("rules", ()):
        if isinstance(rule, dict):
            view = rule.get("view")
            if isinstance(view, str):
                calc_views.add(view)
            name, rtype = rule.get("rule"), rule.get("type")
            if isinstance(name, str) and isinstance(rtype, str):
                rule_types[name] = rtype
    for ver in program.get("versions", ()):
        if isinstance(ver, dict):
            view = ver.get("view")
            if isinstance(view, str):
                calc_views.add(view)
            name, version = ver.get("rule"), ver.get("version")
            if isinstance(name, str) and isinstance(version, str):
                versions[(name, version)] = ver
    return calc_views, versions, rule_types


def _find_expr(
    versions: dict[tuple[str, str], dict],
    rule: str,
    version: str,
    path: str,
) -> dict | None:
    """Resolve a calculation step path (`<def>/(when|value)(/<idx>)*`) to its program node."""
    ver = versions.get((rule, version))
    if ver is None:
        return None
    parts = path.split("/")
    if len(parts) < 2 or parts[1] not in ("when", "value"):
        return None
    def_name, root_field = parts[0], parts[1]
    definition = next(
        (d for d in ver.get("definitions", ()) if isinstance(d, dict) and d.get("name") == def_name),
        None,
    )
    if definition is None:
        return None
    expr = definition.get(root_field)
    for raw_idx in parts[2:]:
        if not isinstance(expr, dict):
            return None
        args = expr.get("args")
        if not isinstance(args, list):
            return None
        try:
            idx = int(raw_idx)
        except ValueError:
            return None
        if idx < 0 or idx >= len(args):
            return None
        expr = args[idx]
    return expr if isinstance(expr, dict) else None


def _taken_cap_arg(
    versions: dict[tuple[str, str], dict],
    cw: dict,
    steps: dict[str, dict],
    path: str,
    step: dict,
) -> int | None:
    """Lowest argument index of a known `min`/`max` step whose exact value equals the step value."""
    if step.get("state") != "known":
        return None
    try:
        step_val = number(step.get("value", ""))
    except ValueError:
        return None
    expr = _find_expr(versions, cw.get("rule", ""), cw.get("version", ""), path)
    if expr is None or expr.get("op") != step.get("op"):
        return None
    args = expr.get("args")
    if not isinstance(args, list):
        return None
    for idx, arg_expr in enumerate(args):
        if not isinstance(arg_expr, dict):
            continue
        if "integer" in arg_expr:
            raw = arg_expr["integer"]
            if not isinstance(raw, str):
                continue
            try:
                arg_val = number(raw)
            except ValueError:
                continue
        else:
            child = steps.get(f"{path}/{idx}")
            if child is None or child.get("state") != "known":
                continue
            try:
                arg_val = number(child.get("value", ""))
            except ValueError:
                continue
        if arg_val == step_val:
            return idx
    return None


def _column_type(columns: dict | None, rel: str, idx: int) -> str | None:
    if not isinstance(columns, dict):
        return None
    cols = columns.get(rel)
    if not isinstance(cols, list) or idx < 0 or idx >= len(cols):
        return None
    return cols[idx]


def _encoded_state(value: str) -> str | None:
    if value.startswith("known:"):
        return "known"
    if value in NON_KNOWN_STATES:
        return value
    return None


def _agg_state(result: str) -> str:
    return "known" if result.startswith("known:") else result


def _check_row_value(columns: dict | None, rel: str, kb: str, ka: str, causes: set[str]) -> None:
    if kb == ka:
        return
    parts_b, parts_a = _parse_key(kb), _parse_key(ka)
    if not parts_b or len(parts_b) != len(parts_a):
        return
    idx = len(parts_a) - 1
    vb, va = parts_b[idx], parts_a[idx]
    if vb == va:
        return
    col_type = _column_type(columns, rel, idx)
    if col_type in VALUE_TYPES:
        causes.add("value")
    elif col_type in ("number", "date"):
        if _encoded_state(vb) != _encoded_state(va):
            causes.add("state")


def _is_turning_calc_value(
    columns: dict | None,
    rule_types: dict[str, str],
    rel: str,
    cwb: dict,
    cwa: dict,
) -> bool:
    if cwb.get("value", "") in BOOLEAN_TEXT or cwa.get("value", "") in BOOLEAN_TEXT:
        return True
    if rule_types.get(cwb.get("rule", "")) == "boolean" or rule_types.get(cwa.get("rule", "")) == "boolean":
        return True
    return _column_type(columns, rel, 1) in VALUE_TYPES


class _Stop:
    """Indexed view of one stop's rows, chosen rule witnesses, and calculation witnesses."""

    def __init__(self, data: dict):
        self.rows: dict[str, set[str]] = defaultdict(set)
        self.witnesses: dict[tuple[str, str], dict] = {}
        self.calc_witnesses: dict[tuple[str, str], dict] = {}
        self.calc_views: set[str] = set()

        for rel, keys in (data.get("rows") or {}).items():
            for k in keys:
                self.rows[rel].add(k)

        raw_witnesses = list(data.get("witnesses") or ())
        by_head: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for w in raw_witnesses:
            ref = (w["conclusion"]["relation"], w["conclusion"]["key"])
            by_head[ref].append(w)
            self.rows[ref[0]].add(ref[1])
            for p in w.get("premises", ()):
                if p.get("polarity", "positive") == "positive":
                    prow = p["row"]
                    self.rows[prow["relation"]].add(prow["key"])

        if any(len(ws) > 1 for ws in by_head.values()):
            derived = {rel for rel, _ in by_head}
            selected = access.select(raw_witnesses, derived)
            for ref, ws in by_head.items():
                if ref in selected:
                    self.witnesses[ref] = selected[ref]
                else:
                    self.witnesses[ref] = min(
                        ws,
                        key=lambda w: (
                            w.get("rule_id", ""),
                            canonical_json([b.get("value", "") for b in w.get("bindings", ())]),
                        ),
                    )
        else:
            for ref, ws in by_head.items():
                self.witnesses[ref] = ws[0]

        for cw in data.get("calc_witnesses") or ():
            ref = (cw["conclusion"]["relation"], cw["conclusion"]["key"])
            self.calc_witnesses[ref] = cw
            self.calc_views.add(ref[0])
            self.rows[ref[0]].add(ref[1])
            for p in cw.get("premises", ()):
                self.rows[p["relation"]].add(p["key"])

    def is_conclusion(self, ref: tuple[str, str]) -> bool:
        return ref in self.witnesses or ref in self.calc_witnesses


def _group_id(parts: tuple[str, ...], is_calc: bool) -> tuple[bool, tuple[str, ...]]:
    if is_calc and len(parts) == 4:
        return (True, (parts[0],))
    if not is_calc and len(parts) > 1:
        return (True, parts[:-1])
    return (False, parts)


def _pair_rows(
    before_rows: dict[str, set[str]],
    after_rows: dict[str, set[str]],
    calc_views: set[str],
) -> tuple[list[tuple[str, str | None, str | None]], dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    """Pair rows across two stops following the same-row rules of decisions/viewer-slip.md."""
    pairs: list[tuple[str, str | None, str | None]] = []
    from_before: dict[tuple[str, str], str] = {}
    from_after: dict[tuple[str, str], str] = {}

    for rel in sorted(set(before_rows) | set(after_rows)):
        is_calc = rel in calc_views
        b_groups: dict[tuple[bool, tuple[str, ...]], set[str]] = defaultdict(set)
        a_groups: dict[tuple[bool, tuple[str, ...]], set[str]] = defaultdict(set)
        for k in before_rows.get(rel, ()):
            b_groups[_group_id(_parse_key(k), is_calc)].add(k)
        for k in after_rows.get(rel, ()):
            a_groups[_group_id(_parse_key(k), is_calc)].add(k)

        for gid in set(b_groups) | set(a_groups):
            o = b_groups.get(gid, set())
            n = a_groups.get(gid, set())
            if gid[0] and len(o) == 1 and len(n) == 1:
                kb, ka = next(iter(o)), next(iter(n))
                pairs.append((rel, kb, ka))
                from_before[(rel, kb)] = ka
                from_after[(rel, ka)] = kb
                continue
            for k in o & n:
                pairs.append((rel, k, k))
                from_before[(rel, k)] = k
                from_after[(rel, k)] = k
            for k in o - n:
                pairs.append((rel, k, None))
            for k in n - o:
                pairs.append((rel, None, k))

    return pairs, from_before, from_after


def _compare_aggregates(aggs_b, aggs_a, causes: set[str]) -> None:
    map_b = {(a["relation"], a.get("position", 0), a["group_key"]): a for a in aggs_b}
    map_a = {(a["relation"], a.get("position", 0), a["group_key"]): a for a in aggs_a}
    common = set(map_b) & set(map_a)
    for key in common:
        ab, aa = map_b[key], map_a[key]
        if ab.get("count") != aa.get("count"):
            causes.add("count")
        if ab.get("contributors_sha256") != aa.get("contributors_sha256"):
            causes.add("contributors")
        if _agg_state(ab.get("result", "")) != _agg_state(aa.get("result", "")):
            causes.add("state")

    rem_b: dict[tuple[str, int], list[dict]] = defaultdict(list)
    rem_a: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for k, a in map_b.items():
        if k not in common:
            rem_b[(k[0], k[1])].append(a)
    for k, a in map_a.items():
        if k not in common:
            rem_a[(k[0], k[1])].append(a)
    for slot in set(rem_b) | set(rem_a):
        lb, la = rem_b.get(slot, ()), rem_a.get(slot, ())
        if len(lb) == 1 and len(la) == 1:
            ab, aa = lb[0], la[0]
            if ab.get("count") != aa.get("count"):
                causes.add("count")
            if (
                ab.get("group_key") != aa.get("group_key")
                or ab.get("contributors_sha256") != aa.get("contributors_sha256")
            ):
                causes.add("contributors")
            if _agg_state(ab.get("result", "")) != _agg_state(aa.get("result", "")):
                causes.add("state")
        else:
            causes.add("presence")


def _compare_negative_premises(
    columns: dict | None,
    neg_b: set[tuple[str, str]],
    neg_a: set[tuple[str, str]],
    causes: set[str],
) -> None:
    if neg_b == neg_a:
        return
    by_rel_b: dict[str, set[str]] = defaultdict(set)
    by_rel_a: dict[str, set[str]] = defaultdict(set)
    for rel, key in neg_b:
        by_rel_b[rel].add(key)
    for rel, key in neg_a:
        by_rel_a[rel].add(key)
    neg_pairs, _, _ = _pair_rows(by_rel_b, by_rel_a, set())
    for rel, kb, ka in neg_pairs:
        if kb is None or ka is None:
            causes.add("presence")
        else:
            _check_row_value(columns, rel, kb, ka, causes)


def derive(columns: dict | None, program: dict | None, before: dict, after: dict) -> list[dict]:
    """Derive turning points between two stops, sorted by `(relation, key)` with sorted causes."""
    prog_views, versions, rule_types = _index_program(program)
    stop_b, stop_a = _Stop(before), _Stop(after)
    calc_views = prog_views | stop_b.calc_views | stop_a.calc_views
    pairs, from_before, from_after = _pair_rows(stop_b.rows, stop_a.rows, calc_views)

    memo: dict[tuple[str, str, str], frozenset[str]] = {}
    active: set[tuple[str, str, str]] = set()

    def compare_positive_premises(
        prem_b: set[tuple[str, str]],
        prem_a: set[tuple[str, str]],
        causes: set[str],
    ) -> bool:
        hit_cycle = False
        for pr, pk_b in prem_b:
            pk_a = from_before.get((pr, pk_b))
            if pk_a is not None and (pr, pk_a) in prem_a:
                sub, cycled = causes_of(pr, pk_b, pk_a)
                causes.update(sub)
                hit_cycle = hit_cycle or cycled
            else:
                causes.add("presence")
        for pr, pk_a in prem_a:
            pk_b = from_after.get((pr, pk_a))
            if pk_b is None or (pr, pk_b) not in prem_b:
                causes.add("presence")
        return hit_cycle

    def causes_of(rel: str, kb: str, ka: str) -> tuple[frozenset[str], bool]:
        cache_key = (rel, kb, ka)
        if cache_key in memo:
            return memo[cache_key], False
        if cache_key in active:
            return frozenset(), True
        active.add(cache_key)
        try:
            causes: set[str] = set()
            hit_cycle = False
            wb = stop_b.witnesses.get((rel, kb))
            wa = stop_a.witnesses.get((rel, ka))
            cwb = stop_b.calc_witnesses.get((rel, kb))
            cwa = stop_a.calc_witnesses.get((rel, ka))

            if cwb is not None and cwa is not None:
                if cwb.get("rule", "") != cwa.get("rule", ""):
                    causes.add("rule")
                if cwb.get("version", "") != cwa.get("version", ""):
                    causes.add("version")
                if cwb.get("definition", "") != cwa.get("definition", ""):
                    causes.add("definition")
                if cwb.get("state", "") != cwa.get("state", ""):
                    causes.add("state")
                elif (
                    cwb.get("state") == "known"
                    and cwb.get("value", "") != cwa.get("value", "")
                    and _is_turning_calc_value(columns, rule_types, rel, cwb, cwa)
                ):
                    causes.add("value")

                steps_b = {s["path"]: s for s in cwb.get("steps", ())}
                steps_a = {s["path"]: s for s in cwa.get("steps", ())}
                if set(steps_b) != set(steps_a):
                    causes.add("path")
                for path in sorted(set(steps_b) & set(steps_a)):
                    sb, sa = steps_b[path], steps_a[path]
                    if sb.get("state") != sa.get("state"):
                        causes.add("state")
                    elif sb.get("state") == "known":
                        vb, va = sb.get("value", ""), sa.get("value", "")
                        if vb != va and (vb in BOOLEAN_TEXT or va in BOOLEAN_TEXT):
                            causes.add("value")
                    if sb.get("op") in ("min", "max") and sb.get("op") == sa.get("op"):
                        tb = _taken_cap_arg(versions, cwb, steps_b, path, sb)
                        ta = _taken_cap_arg(versions, cwa, steps_a, path, sa)
                        if tb is not None and ta is not None and tb != ta:
                            causes.add("cap")

                prem_b = {(p["relation"], p["key"]) for p in cwb.get("premises", ())}
                prem_a = {(p["relation"], p["key"]) for p in cwa.get("premises", ())}
                hit_cycle = compare_positive_premises(prem_b, prem_a, causes)

            elif wb is not None and wa is not None:
                _check_row_value(columns, rel, kb, ka, causes)
                if wb.get("rule_id") != wa.get("rule_id"):
                    causes.add("rule")
                _compare_aggregates(wb.get("aggregates", ()), wa.get("aggregates", ()), causes)
                pos_b = {
                    (p["row"]["relation"], p["row"]["key"])
                    for p in wb.get("premises", ())
                    if p.get("polarity", "positive") == "positive"
                }
                pos_a = {
                    (p["row"]["relation"], p["row"]["key"])
                    for p in wa.get("premises", ())
                    if p.get("polarity", "positive") == "positive"
                }
                hit_cycle = compare_positive_premises(pos_b, pos_a, causes)
                neg_b = {
                    (p["row"]["relation"], p["row"]["key"])
                    for p in wb.get("premises", ())
                    if p.get("polarity") == "negative"
                }
                neg_a = {
                    (p["row"]["relation"], p["row"]["key"])
                    for p in wa.get("premises", ())
                    if p.get("polarity") == "negative"
                }
                _compare_negative_premises(columns, neg_b, neg_a, causes)

            elif wb is None and wa is None and cwb is None and cwa is None:
                if rel in calc_views:
                    pb, pa = _parse_key(kb), _parse_key(ka)
                    if len(pb) == 4 and len(pa) == 4:
                        if pb[2] != pa[2]:
                            causes.add("state")
                        elif pb[2] == "known" and pb[1] != pa[1] and (
                            pb[1] in BOOLEAN_TEXT or pa[1] in BOOLEAN_TEXT
                            or _column_type(columns, rel, 1) in VALUE_TYPES
                        ):
                            causes.add("value")
                else:
                    _check_row_value(columns, rel, kb, ka, causes)

            else:
                causes.add("rule")
                if rel not in calc_views:
                    _check_row_value(columns, rel, kb, ka, causes)

            result = frozenset(causes)
            if not hit_cycle:
                memo[cache_key] = result
            return result, hit_cycle
        finally:
            active.discard(cache_key)

    turns: list[dict] = []
    for rel, kb, ka in pairs:
        concl_b = kb is not None and stop_b.is_conclusion((rel, kb))
        concl_a = ka is not None and stop_a.is_conclusion((rel, ka))
        if not (concl_b or concl_a):
            continue
        if kb is None or ka is None:
            causes = frozenset({"presence"})
        else:
            causes, _ = causes_of(rel, kb, ka)
        if causes:
            key = ka if ka is not None else kb
            turns.append({"relation": rel, "key": key, "causes": sorted(causes)})

    turns.sort(key=lambda entry: (entry["relation"], entry["key"]))
    return turns


def _validate_causes(causes: object) -> str | None:
    if not isinstance(causes, list) or not causes:
        return "causes must be a non-empty list"
    if not all(isinstance(c, str) for c in causes):
        return "causes must contain strings"
    unknown = sorted(set(causes) - CAUSES)
    if unknown:
        return f"unknown causes {unknown}"
    if len(set(causes)) != len(causes):
        return f"duplicate causes {causes}"
    if causes != sorted(causes):
        return f"unsorted causes {causes}"
    return None


def check(
    columns: dict | None,
    program: dict | None,
    before: dict,
    after: dict,
    listed: list[dict],
) -> list[str]:
    """Check `listed` turning points against the turns independently derived from `before` and `after`."""
    expected = derive(columns, program, before, after)
    if not isinstance(listed, list):
        return ["turns: listed must be a list"]

    problems: list[str] = []
    seen: dict[tuple[str, str], object] = {}
    bad_causes: set[tuple[str, str]] = set()
    prev_ref: tuple[str, str] | None = None

    for i, entry in enumerate(listed):
        if not isinstance(entry, dict) or set(entry) != {"relation", "key", "causes"}:
            problems.append(f"turns[{i}]: malformed entry")
            continue
        rel, key, causes = entry["relation"], entry["key"], entry["causes"]
        if not isinstance(rel, str) or not rel or not isinstance(key, str):
            problems.append(f"turns[{i}]: malformed relation or key")
            continue
        ref = (rel, key)
        if prev_ref is not None and ref < prev_ref:
            problems.append(f"turns[{i}]: {rel} {key} is out of (relation, key) order")
        if ref in seen:
            problems.append(f"turns[{i}]: duplicate entry for {rel} {key}")
            continue
        cause_err = _validate_causes(causes)
        if cause_err is not None:
            problems.append(f"turns[{i}]: {rel} {key} has {cause_err}")
            bad_causes.add(ref)
        seen[ref] = causes
        prev_ref = ref

    want = {(e["relation"], e["key"]): e["causes"] for e in expected}
    for ref in sorted(want.keys() - seen.keys()):
        problems.append(f"turns: missing {ref[0]} {ref[1]} (expected causes {want[ref]})")
    for ref in sorted(seen.keys() - want.keys()):
        problems.append(f"turns: unexpected {ref[0]} {ref[1]} (listed causes {seen[ref]})")
    for ref in sorted(want.keys() & seen.keys()):
        if ref not in bad_causes and seen[ref] != want[ref]:
            problems.append(f"turns: {ref[0]} {ref[1]} has causes {seen[ref]}, expected {want[ref]}")

    return problems
