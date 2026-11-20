"""Turning points between two neighbouring stops of a sweep (decisions/viewer-slip.md, "Turning points").

A turning point is a conclusion the role reads whose outcome changes in kind between two stops, not only in
size. Rows are paired across the two stops by (relation, subject) for a calculation rule's view, and by exact
key or unique prefix (all columns but the last, for multi-column keys) for any other relation, matching how
`rezono_publisher.difference.entries` reports `changed`.

Only conclusions turn: rows with a witness or a calculation witness at one of the two stops. A fact that
moves is the cause of a turn, never a turning point itself. Only the role's own snapshots and witness sets
are read, so no unreadable row can influence the result.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from fractions import Fraction
import json

from rezono_canon import canonical_json
from rezono_compiler import rank

VALUE_TYPES = frozenset({"reference", "enum", "boolean"})
BOOLEANS = frozenset({"true", "false"})
NON_KNOWN_STATES = frozenset({"unknown", "not_applicable", "invalid"})


def _decode_key(key: str) -> tuple[str, ...] | None:
    try:
        parts = json.loads(key)
    except (TypeError, ValueError):
        return None
    if isinstance(parts, list) and all(isinstance(p, str) for p in parts):
        return tuple(parts)
    return None


def _parse_number(text: str) -> Fraction | None:
    if not isinstance(text, str) or not text or text in BOOLEANS:
        return None
    try:
        return Fraction(text)
    except ValueError:
        return None


def _value_state(value: str) -> str:
    if isinstance(value, str):
        if value.startswith("known:"):
            return "known"
        if value in NON_KNOWN_STATES:
            return value
    return "known"


def _calc_views(program: dict | None, before: dict, after: dict) -> set[str]:
    views: set[str] = set()
    if isinstance(program, dict):
        for rule in program.get("rules") or ():
            if isinstance(rule, dict) and isinstance(rule.get("view"), str):
                views.add(rule["view"])
        for version in program.get("versions") or ():
            if isinstance(version, dict) and isinstance(version.get("view"), str):
                views.add(version["view"])
    for stop in (before, after):
        for cw in stop.get("calc_witnesses") or ():
            rel = cw.get("conclusion", {}).get("relation")
            if isinstance(rel, str):
                views.add(rel)
    return views


def _program_index(
    program: dict | None,
) -> tuple[dict[tuple[str, str], dict], dict[str, dict], dict[str, dict], dict[str, str]]:
    by_rv: dict[tuple[str, str], dict] = {}
    by_id: dict[str, dict] = {}
    by_view: dict[str, dict] = {}
    rule_types: dict[str, str] = {}
    if isinstance(program, dict):
        for rule in program.get("rules") or ():
            if isinstance(rule, dict):
                name, rtype = rule.get("rule"), rule.get("type")
                if isinstance(name, str) and isinstance(rtype, str):
                    rule_types[name] = rtype
        for v in program.get("versions") or ():
            if isinstance(v, dict):
                r, ver = v.get("rule"), v.get("version")
                if isinstance(r, str) and isinstance(ver, str):
                    by_rv[(r, ver)] = v
                if isinstance(v.get("id"), str):
                    by_id[v["id"]] = v
                if isinstance(v.get("view"), str):
                    by_view[v["view"]] = v
    return by_rv, by_id, by_view, rule_types


def _version_of(
    by_rv: dict[tuple[str, str], dict],
    by_id: dict[str, dict],
    by_view: dict[str, dict],
    cw: dict,
) -> dict | None:
    rule = cw.get("rule")
    version = cw.get("version")
    if isinstance(rule, str) and isinstance(version, str) and rule and version:
        found = by_rv.get((rule, version))
        if found is not None:
            return found
        found = by_id.get(f"{rule}@{version}")
        if found is not None:
            return found
    rel = cw.get("conclusion", {}).get("relation")
    if isinstance(rel, str) and rel in by_view:
        return by_view[rel]
    return None


def _find_expr(version_doc: dict | None, path: str) -> dict | None:
    if version_doc is None or not isinstance(path, str):
        return None
    parts = path.split("/")
    if len(parts) < 2 or parts[1] not in ("when", "value"):
        return None
    def_name, branch, rest = parts[0], parts[1], parts[2:]
    defn = next((d for d in version_doc.get("definitions") or () if isinstance(d, dict) and d.get("name") == def_name),
                None)
    if defn is None:
        return None
    node = defn.get(branch)
    for seg in rest:
        if not isinstance(node, dict):
            return None
        args = node.get("args")
        if not isinstance(args, list):
            return None
        try:
            idx = int(seg)
        except ValueError:
            return None
        if idx < 0 or idx >= len(args):
            return None
        node = args[idx]
    return node if isinstance(node, dict) else None


def _taken_arg(version_doc: dict | None, steps_by_path: dict[str, dict], path: str) -> int | None:
    """The lowest-index argument of a known `min` or `max` step whose value equals the step's value."""
    step = steps_by_path.get(path)
    if step is None or step.get("state") != "known":
        return None
    target = _parse_number(step.get("value", ""))
    if target is None:
        return None
    expr = _find_expr(version_doc, path)
    if expr is None or expr.get("op") not in ("min", "max"):
        return None
    for idx, arg_expr in enumerate(expr.get("args") or ()):
        child = steps_by_path.get(f"{path}/{idx}")
        if child is not None:
            if child.get("state") != "known":
                continue
            val = _parse_number(child.get("value", ""))
        elif isinstance(arg_expr, dict) and "integer" in arg_expr:
            val = _parse_number(str(arg_expr["integer"]))
        else:
            val = None
        if val is not None and val == target:
            return idx
    return None


def _select_witnesses(
    raw_witnesses: list[dict],
    by_head: dict[tuple[str, str], list[dict]],
) -> dict[tuple[str, str], dict]:
    if not any(len(ws) > 1 for ws in by_head.values()):
        return {ref: ws[0] for ref, ws in by_head.items()}
    derived = {rel for rel, _ in by_head}
    inst = [
        (
            (w["conclusion"]["relation"], w["conclusion"]["key"]),
            {
                (p["row"]["relation"], p["row"]["key"])
                for p in w.get("premises") or ()
                if p.get("polarity", "positive") == "positive" and p["row"]["relation"] in derived
            },
            (w.get("rule_id", ""), json.dumps([b.get("value", "") for b in w.get("bindings") or ()])),
        )
        for w in raw_witnesses
    ]
    chosen = rank.choose(inst)
    selected: dict[tuple[str, str], dict] = {}
    for ref, ws in by_head.items():
        if ref in chosen:
            selected[ref] = raw_witnesses[chosen[ref][1]]
        else:
            selected[ref] = min(
                ws,
                key=lambda w: (
                    w.get("rule_id", ""),
                    canonical_json([b.get("value", "") for b in w.get("bindings") or ()]),
                ),
            )
    return selected


def _index_stop(stop: dict) -> tuple[dict[str, set[str]], dict[tuple[str, str], dict], dict[tuple[str, str], dict]]:
    rows: dict[str, set[str]] = {}
    for rel, keys in (stop.get("rows") or {}).items():
        rows.setdefault(rel, set()).update(keys)
    raw_witnesses = list(stop.get("witnesses") or ())
    by_head: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for w in raw_witnesses:
        c = w["conclusion"]
        ref = (c["relation"], c["key"])
        by_head[ref].append(w)
        rows.setdefault(c["relation"], set()).add(c["key"])
        for p in w.get("premises") or ():
            if p.get("polarity", "positive") == "positive":
                pr = p["row"]
                rows.setdefault(pr["relation"], set()).add(pr["key"])
    witnesses = _select_witnesses(raw_witnesses, by_head)
    calc_witnesses: dict[tuple[str, str], dict] = {}
    for cw in stop.get("calc_witnesses") or ():
        c = cw["conclusion"]
        ref = (c["relation"], c["key"])
        calc_witnesses[ref] = cw
        rows.setdefault(c["relation"], set()).add(c["key"])
        for pr in cw.get("premises") or ():
            rows.setdefault(pr["relation"], set()).add(pr["key"])
    return rows, witnesses, calc_witnesses


def _pair_rows(
    rows_b: dict[str, set[str]],
    rows_a: dict[str, set[str]],
    calc_views: set[str],
) -> tuple[dict[tuple[str, str], tuple[str, str, str]], dict[tuple[str, str], tuple[str, str, str]], list[tuple[str, str, str]]]:
    pair_b: dict[tuple[str, str], tuple[str, str, str]] = {}
    pair_a: dict[tuple[str, str], tuple[str, str, str]] = {}
    pairs: list[tuple[str, str, str]] = []

    def link(rel: str, kb: str, ka: str) -> None:
        entry = (rel, kb, ka)
        pair_b[(rel, kb)] = entry
        pair_a[(rel, ka)] = entry
        pairs.append(entry)

    for rel in sorted(set(rows_b) | set(rows_a)):
        keys_b = rows_b.get(rel, set())
        keys_a = rows_a.get(rel, set())
        same = keys_b & keys_a
        for k in sorted(same):
            link(rel, k, k)
        rem_b = keys_b - same
        rem_a = keys_a - same
        if not rem_b or not rem_a:
            continue
        if rel in calc_views:
            decoded_b = {k: p for k in keys_b if (p := _decode_key(k)) is not None and len(p) == 4}
            decoded_a = {k: p for k in keys_a if (p := _decode_key(k)) is not None and len(p) == 4}
            count_b = Counter(p[0] for p in decoded_b.values())
            count_a = Counter(p[0] for p in decoded_a.values())
            by_subj_b = {
                decoded_b[k][0]: k
                for k in rem_b
                if k in decoded_b and count_b[decoded_b[k][0]] == 1 and count_a[decoded_b[k][0]] == 1
            }
            for ka in sorted(rem_a):
                if ka in decoded_a and decoded_a[ka][0] in by_subj_b:
                    link(rel, by_subj_b[decoded_a[ka][0]], ka)
        else:
            decoded_b = {k: p for k in keys_b if (p := _decode_key(k)) is not None and len(p) > 1}
            decoded_a = {k: p for k in keys_a if (p := _decode_key(k)) is not None and len(p) > 1}
            count_b = Counter(p[:-1] for p in decoded_b.values())
            count_a = Counter(p[:-1] for p in decoded_a.values())
            by_pref_b = {
                decoded_b[k][:-1]: k
                for k in rem_b
                if k in decoded_b and count_b[decoded_b[k][:-1]] == 1 and count_a[decoded_b[k][:-1]] == 1
            }
            for ka in sorted(rem_a):
                if ka in decoded_a and decoded_a[ka][:-1] in by_pref_b:
                    link(rel, by_pref_b[decoded_a[ka][:-1]], ka)
    return pair_b, pair_a, pairs


def _key_value_causes(columns: dict, rel: str, kb: str, ka: str) -> set[str]:
    if kb == ka:
        return set()
    col_types = columns.get(rel)
    if not col_types:
        return set()
    pb, pa = _decode_key(kb), _decode_key(ka)
    if pb is None or pa is None or len(pb) != len(pa):
        return set()
    found: set[str] = set()
    for i, (vb, va) in enumerate(zip(pb, pa)):
        if vb == va or i >= len(col_types):
            continue
        col_type = col_types[i]
        if col_type in VALUE_TYPES:
            found.add("value")
        elif col_type in ("number", "date"):
            if _value_state(vb) != _value_state(va):
                found.add("state")
    return found


def _compare_negative_premises(
    columns: dict,
    neg_b: set[tuple[str, str]],
    neg_a: set[tuple[str, str]],
    causes: set[str],
) -> None:
    if neg_b == neg_a:
        return
    rows_b: dict[str, set[str]] = {}
    rows_a: dict[str, set[str]] = {}
    for rel, key in neg_b:
        rows_b.setdefault(rel, set()).add(key)
    for rel, key in neg_a:
        rows_a.setdefault(rel, set()).add(key)
    pair_b, pair_a, neg_pairs = _pair_rows(rows_b, rows_a, set())
    if len(pair_b) < len(neg_b) or len(pair_a) < len(neg_a):
        causes.add("presence")
    for rel, kb, ka in neg_pairs:
        causes |= _key_value_causes(columns, rel, kb, ka)


def _compare_aggregates(aggs_b, aggs_a, causes: set[str]) -> None:
    map_b = {(a["relation"], a.get("position", 0), a["group_key"]): a for a in aggs_b}
    map_a = {(a["relation"], a.get("position", 0), a["group_key"]): a for a in aggs_a}
    common = set(map_b) & set(map_a)
    for ak in common:
        ab, aa = map_b[ak], map_a[ak]
        if ab.get("count") != aa.get("count"):
            causes.add("count")
        if ab.get("contributors_sha256") != aa.get("contributors_sha256"):
            causes.add("contributors")
        if _value_state(ab.get("result", "")) != _value_state(aa.get("result", "")):
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
            if _value_state(ab.get("result", "")) != _value_state(aa.get("result", "")):
                causes.add("state")
        else:
            causes.add("presence")


def between(columns: dict, program: dict | None, before: dict, after: dict) -> list[dict]:
    """Conclusions the role reads that turn between `before` and `after`, with sorted causes.

    Returns `[{"relation", "key", "causes"}]` in `(relation, key)` order, using the key at `after` when
    the row is present there, else the key at `before`.
    """
    cols = columns or {}
    calc_views = _calc_views(program, before, after)
    by_rv, by_id, by_view, rule_types = _program_index(program)
    rows_b, wits_b, calc_b = _index_stop(before)
    rows_a, wits_a, calc_a = _index_stop(after)
    pair_b, pair_a, pairs = _pair_rows(rows_b, rows_a, calc_views)

    def row_id_b(rel: str, key: str) -> tuple:
        paired = pair_b.get((rel, key))
        return ("paired", *paired) if paired is not None else ("before", rel, key)

    def row_id_a(rel: str, key: str) -> tuple:
        paired = pair_a.get((rel, key))
        return ("paired", *paired) if paired is not None else ("after", rel, key)

    memo: dict[tuple[str, str, str], frozenset[str]] = {}
    active: set[tuple[str, str, str]] = set()

    def causes_of_pair(rel: str, kb: str, ka: str) -> tuple[frozenset[str], bool]:
        key = (rel, kb, ka)
        if key in memo:
            return memo[key], False
        if key in active:
            return frozenset(), True
        active.add(key)
        try:
            causes: set[str] = set()
            hit_cycle = False
            wb, wa = wits_b.get((rel, kb)), wits_a.get((rel, ka))
            cb, ca = calc_b.get((rel, kb)), calc_a.get((rel, ka))

            if cb is not None and ca is not None:
                if cb.get("rule") != ca.get("rule"):
                    causes.add("rule")
                if cb.get("version", "") != ca.get("version", ""):
                    causes.add("version")
                if cb.get("definition", "") != ca.get("definition", ""):
                    causes.add("definition")
                if cb.get("state") != ca.get("state"):
                    causes.add("state")
                elif cb.get("state") == "known" and cb.get("value") != ca.get("value"):
                    col_types = cols.get(rel)
                    if (
                        cb.get("value") in BOOLEANS
                        or ca.get("value") in BOOLEANS
                        or rule_types.get(cb.get("rule", "")) == "boolean"
                        or rule_types.get(ca.get("rule", "")) == "boolean"
                        or (col_types and len(col_types) > 1 and col_types[1] in VALUE_TYPES)
                    ):
                        causes.add("value")
                steps_b = {s["path"]: s for s in cb.get("steps") or ()}
                steps_a = {s["path"]: s for s in ca.get("steps") or ()}
                if set(steps_b) != set(steps_a):
                    causes.add("path")
                ver_b = _version_of(by_rv, by_id, by_view, cb)
                ver_a = _version_of(by_rv, by_id, by_view, ca)
                for path in sorted(set(steps_b) & set(steps_a)):
                    sb, sa = steps_b[path], steps_a[path]
                    if sb.get("state") != sa.get("state"):
                        causes.add("state")
                    elif sb.get("state") == "known":
                        if (sb.get("value") != sa.get("value")
                                and (sb.get("value") in BOOLEANS or sa.get("value") in BOOLEANS)):
                            causes.add("value")
                        if sb.get("op") in ("min", "max") and sa.get("op") == sb.get("op"):
                            tb = _taken_arg(ver_b, steps_b, path)
                            ta = _taken_arg(ver_a, steps_a, path)
                            if tb is not None and ta is not None and tb != ta:
                                causes.add("cap")
                prem_b = {row_id_b(p["relation"], p["key"]) for p in cb.get("premises") or ()}
                prem_a = {row_id_a(p["relation"], p["key"]) for p in ca.get("premises") or ()}
                if prem_b != prem_a:
                    causes.add("presence")
                for pid in prem_b & prem_a:
                    sub, cycled = causes_of_pair(pid[1], pid[2], pid[3])
                    causes |= sub
                    hit_cycle = hit_cycle or cycled
            elif wb is not None and wa is not None:
                causes |= _key_value_causes(cols, rel, kb, ka)
                if wb.get("rule_id") != wa.get("rule_id"):
                    causes.add("rule")
                pos_b = {
                    row_id_b(p["row"]["relation"], p["row"]["key"])
                    for p in wb.get("premises") or ()
                    if p.get("polarity", "positive") == "positive"
                }
                pos_a = {
                    row_id_a(p["row"]["relation"], p["row"]["key"])
                    for p in wa.get("premises") or ()
                    if p.get("polarity", "positive") == "positive"
                }
                if pos_b != pos_a:
                    causes.add("presence")
                for pid in pos_b & pos_a:
                    sub, cycled = causes_of_pair(pid[1], pid[2], pid[3])
                    causes |= sub
                    hit_cycle = hit_cycle or cycled
                neg_b = {
                    (p["row"]["relation"], p["row"]["key"])
                    for p in wb.get("premises") or ()
                    if p.get("polarity") == "negative"
                }
                neg_a = {
                    (p["row"]["relation"], p["row"]["key"])
                    for p in wa.get("premises") or ()
                    if p.get("polarity") == "negative"
                }
                _compare_negative_premises(cols, neg_b, neg_a, causes)
                _compare_aggregates(wb.get("aggregates") or (), wa.get("aggregates") or (), causes)
            elif wb is None and wa is None and cb is None and ca is None:
                if rel in calc_views:
                    pb, pa = _decode_key(kb), _decode_key(ka)
                    if pb is not None and pa is not None and len(pb) == 4 and len(pa) == 4:
                        if pb[2] != pa[2]:
                            causes.add("state")
                        elif pb[2] == "known" and pb[1] != pa[1]:
                            col_types = cols.get(rel)
                            if (pb[1] in BOOLEANS or pa[1] in BOOLEANS
                                    or (col_types and len(col_types) > 1 and col_types[1] in VALUE_TYPES)):
                                causes.add("value")
                else:
                    causes |= _key_value_causes(cols, rel, kb, ka)
            else:
                causes.add("rule")
                if rel not in calc_views:
                    causes |= _key_value_causes(cols, rel, kb, ka)

            result = frozenset(causes)
            if not hit_cycle:
                memo[key] = result
            return result, hit_cycle
        finally:
            active.discard(key)

    conclusions_b = set(wits_b) | set(calc_b)
    conclusions_a = set(wits_a) | set(calc_a)
    out: list[dict] = []

    for rel, kb, ka in pairs:
        if (rel, kb) not in conclusions_b and (rel, ka) not in conclusions_a:
            continue
        found, _ = causes_of_pair(rel, kb, ka)
        if found:
            out.append({"relation": rel, "key": ka, "causes": sorted(found)})

    for rel, kb in sorted(conclusions_b - set(pair_b)):
        out.append({"relation": rel, "key": kb, "causes": ["presence"]})

    for rel, ka in sorted(conclusions_a - set(pair_a)):
        out.append({"relation": rel, "key": ka, "causes": ["presence"]})

    out.sort(key=lambda item: (item["relation"], item["key"]))
    return out
