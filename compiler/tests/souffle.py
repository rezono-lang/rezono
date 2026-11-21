"""Rule IR -> Soufflé, the oracle (tests only). Runs `souffle` and reads every derived relation as a set.

The IR as a program (`program`), or a pack's rule text as written, over its import closure (`pack_source`).
What the compiler lowers a view to has no text: those rules come from the IR (`lowered`, `view_bound`).
A value column is an extra column at the end of the Soufflé relation; a literal leaves it out with '_'.
An aggregate over a key column puts the aggregated variable at that position.
Soufflé has 32-bit numbers by default; the generated programs stay far below that.
"""

import datetime
import re
import subprocess
import tempfile
from itertools import accumulate, count
from pathlib import Path

from rezono_compiler.rules import COMPARE_AS, DAYS, const_type, is_var

TYPE = {"string": "symbol", "integer": "number", "boolean": "symbol", "date": "symbol"}
_BOOL = {"TRUE": "true", "FALSE": "false"}
INPUT = ("base", "calc")  # what the rules read: a table, and a calculation selection with the rows given
OPS = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "add": "+", "sub": "-", "mul": "*", "div": "/"}
_DAY_SHAPE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
_UTC_SHAPE = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?Z"
_UTC_WHOLE = 20  # characters of YYYY-MM-DDTHH:mm:ssZ
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
# Uppercase helper relation names stay out of pack_source's lowercase `.decl` checks and cannot clash with Rezono names.
_PROBE = "SymbolOrderProbe"
_PROBE_SYMBOLS = sorted({
    "-", ".", "0", "00", "09", "0a", "9", ":", "T", "Z",
    "a", "a-", "a0", "alpha", "alpha-next", "z",
    "e\u0301", "\u00e9", "\ue000", "\U00010000",
}, key=lambda s: s.encode("utf-8"), reverse=True)


def _quote(text):
    escaped = (text.replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return f'"{escaped}"'


def _bool_text(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower()
    return _BOOL.get(value, str(value))


def _fact_cell(value, typ):
    if typ == "boolean" or isinstance(value, bool):
        return _bool_text(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def _term(t, typ):
    if t == "_":
        return "_"
    if isinstance(t, str) and is_var(t):
        return "V_" + t[1:]
    if typ == "boolean" or isinstance(t, bool):
        return _quote(_bool_text(t))
    if typ == "integer":
        return str(t)
    return _quote(t)


def _atom(prog, atom, over=None, *, is_head=False):
    rel = prog.relations[atom.relation]
    cols = rel.head_columns if is_head else rel.row_columns
    terms = ["W_" if over == c.name and t == "_" else _term(t, c.type) for t, c in zip(atom.terms, cols)]
    terms += ["W_" if over == c.name else "_" for c in rel.values]
    return f"{atom.relation}({', '.join(terms)})"


def _decl(rel):
    cols = rel.row_columns + rel.values
    for c in cols:
        if c.type not in TYPE:
            raise ValueError(f"Soufflé oracle does not support column type {c.type!r} ({rel.name}.{c.name})")
    return f".decl {rel.name}({', '.join(f'{c.name}:{TYPE[c.type]}' for c in cols)})"


def _string_candidates(prog, target, extra_literals=(), *, types=("string",)):
    """Stratum-0 rules feeding every candidate value of `types` that can reach `target` from inputs and rule literals."""
    rules = []
    for rel in sorted(prog.relations.values(), key=lambda r: r.name):
        if rel.role not in INPUT:
            continue
        cols = rel.key + rel.values
        for i, col in enumerate(cols):
            if col.type not in types:
                continue
            terms = ["x" if j == i else "_" for j in range(len(cols))]
            rules.append(f"{target}(x) :- {rel.name}({', '.join(terms)}).")
    literals = set(extra_literals)
    for r in prog.rules.values():
        for atom, is_head in ((r.head, True), *((b.atom, False) for b in r.body), *((a.atom, False) for a in r.aggregates)):
            rel = prog.relations[atom.relation]
            cols = rel.head_columns if is_head else rel.row_columns
            for t, col in zip(atom.terms, cols):
                if col.type == "string" and t != "_" and not is_var(t):
                    literals.add(_term(t, "string"))
        for s in r.assignments:
            if s.op == DAYS:
                for t in (s.left, s.right):
                    if not is_var(t):
                        literals.add(_term(t, "string"))
        for c in r.conditions:
            if c.compare_as in COMPARE_AS:
                for t in (c.left, c.right):
                    if not is_var(t):
                        literals.add(_term(t, "string"))
    for lit in sorted(literals):
        rules.append(f"{target}({lit}).")
    return rules


def _day_rules(prog, extra_literals=()):
    """`DayNum(x, n)`: x is a valid Gregorian YYYY-MM-DD date (years 0001..9999) and n its proleptic day ordinal.
    Invalid spellings, non-existent calendar days and year 0000 derive nothing (decisions/rule-day-numbers.md)."""
    return [
        ".decl DayIn(x: symbol)",
        ".decl DayShape(x: symbol)",
        ".decl DayMonth(m: number, last: number)",
        ".decl DayFields(x: symbol, y: number, m: number, d: number)",
        ".decl DayOk(x: symbol, y: number, m: number, d: number)",
        ".decl DayNum(x: symbol, n: number)",
        *_string_candidates(prog, "DayIn", extra_literals, types=("string", "date")),
        *(f"DayMonth({month}, {last})." for month, last in enumerate(_MONTH_DAYS, 1)),
        f'DayShape(x) :- DayIn(x), match("{_DAY_SHAPE}", x).',
        ("DayFields(x, Y, M, D) :- DayShape(x), "
         "Y = to_number(substr(x, 0, 4)), M = to_number(substr(x, 5, 2)), D = to_number(substr(x, 8, 2))."),
        "DayOk(x, Y, M, D) :- DayFields(x, Y, M, D), Y >= 1, DayMonth(M, L), D >= 1, D <= L.",
        "DayOk(x, Y, 2, 29) :- DayFields(x, Y, 2, 29), Y >= 1, Y % 4 = 0, Y % 100 != 0.",
        "DayOk(x, Y, 2, 29) :- DayFields(x, Y, 2, 29), Y >= 1, Y % 400 = 0.",
        ("DayNum(x, V) :- DayOk(x, Y, M, D), S = Y - (14 - M) / 12, N = (M + 9) % 12, "
         "V = 365 * S + S / 4 - S / 100 + S / 400 + (153 * N + 2) / 5 + D."),
    ]


def _utc_rules(prog, extra_literals=()):
    """`UtcKey(x, k)`: x is a valid UTC instant and k its comparison key (decisions/ordered-rule-scalars.md)."""
    return [
        ".decl UtcIn(x: symbol)",
        ".decl UtcShape(x: symbol)",
        ".decl UtcMonth(m: number, last: number)",
        ".decl UtcFields(x: symbol, y: number, m: number, d: number, h: number, i: number, s: number)",
        ".decl UtcOk(x: symbol)",
        ".decl UtcCut(x: symbol, t: symbol)",
        ".decl UtcKey(x: symbol, k: symbol)",
        *_string_candidates(prog, "UtcIn", extra_literals),
        *(f"UtcMonth({month}, {last})." for month, last in enumerate(_MONTH_DAYS, 1)),
        f'UtcShape(x) :- UtcIn(x), match("{_UTC_SHAPE}", x).',
        ("UtcFields(x, Y, M, D, H, I, S) :- UtcShape(x), "
         "Y = to_number(substr(x, 0, 4)), M = to_number(substr(x, 5, 2)), D = to_number(substr(x, 8, 2)), "
         "H = to_number(substr(x, 11, 2)), I = to_number(substr(x, 14, 2)), S = to_number(substr(x, 17, 2))."),
        "UtcOk(x) :- UtcFields(x, Y, M, D, H, I, S), Y >= 1, H <= 23, I <= 59, S <= 59, UtcMonth(M, L), D >= 1, D <= L.",
        "UtcOk(x) :- UtcFields(x, Y, 2, 29, H, I, S), Y >= 1, H <= 23, I <= 59, S <= 59, Y % 4 = 0, Y % 100 != 0.",
        "UtcOk(x) :- UtcFields(x, Y, 2, 29, H, I, S), Y >= 1, H <= 23, I <= 59, S <= 59, Y % 400 = 0.",
        f"UtcKey(x, substr(x, 0, {_UTC_WHOLE - 1})) :- UtcOk(x), strlen(x) = {_UTC_WHOLE}.",
        f"UtcCut(x, substr(x, 0, strlen(x) - 1)) :- UtcOk(x), strlen(x) > {_UTC_WHOLE}.",
        'UtcCut(x, substr(t, 0, strlen(t) - 1)) :- UtcCut(x, t), substr(t, strlen(t) - 1, 1) = "0".',
        'UtcKey(x, substr(t, 0, strlen(t) - 1)) :- UtcCut(x, t), substr(t, strlen(t) - 1, 1) = ".".',
        'UtcKey(x, t) :- UtcCut(x, t), substr(t, strlen(t) - 1, 1) != "0", substr(t, strlen(t) - 1, 1) != ".".',
    ]


def _probe_rules():
    """Prove on every typed run that the Soufflé binary orders symbols by their unsigned UTF-8 bytes."""
    return [
        f".decl {_PROBE}Symbol(x: symbol)",
        f".input {_PROBE}Symbol",
        f".decl {_PROBE}(x: symbol, y: symbol)",
        f"{_PROBE}(x, y) :- {_PROBE}Symbol(x), {_PROBE}Symbol(y), x < y.",
        f".output {_PROBE}",
    ]


def _rule_body_parts(prog, r, *, include_aggregates=True, include_assignments=True, include_conditions=True):
    types = {}
    for b in r.body:
        for t, c in zip(b.atom.terms, prog.relations[b.atom.relation].row_columns):
            types.setdefault(t, c.type)
    parts = []
    for b in r.body:
        parts.append(("!" if b.polarity == "negative" else "") + _atom(prog, b.atom))
    if include_aggregates:
        for a in r.aggregates:
            inner = _atom(prog, a.atom, over=a.over)
            fn = "count" if a.function == "count" else f"{a.function} W_"
            parts.append(f"{_term(a.var, 'integer')} = {fn} : {{ {inner} }}")
    if include_assignments:
        for idx, s in enumerate(r.assignments):
            if s.op == DAYS:
                left_d, right_d = f"DayLeft_{idx}_", f"DayRight_{idx}_"
                parts.append(
                    f"DayNum({_term(s.left, 'string')}, {left_d}), "
                    f"DayNum({_term(s.right, 'string')}, {right_d}), "
                    f"{_term(s.var, 'integer')} = {left_d} - {right_d}"
                )
                continue
            parts.append(f"{_term(s.var, 'integer')} = {_term(s.left, 'integer')} {OPS[s.op]} {_term(s.right, 'integer')}")
    if include_conditions:
        for idx, c in enumerate(r.conditions):
            if c.compare_as is not None and c.compare_as not in COMPARE_AS:
                raise ValueError(f"unsupported compare_as {c.compare_as!r}")
            if c.compare_as == "utc_instant":
                left_k, right_k = f"UtcLeft_{idx}_", f"UtcRight_{idx}_"
                parts.append(
                    f"UtcKey({_term(c.left, 'string')}, {left_k}), "
                    f"UtcKey({_term(c.right, 'string')}, {right_k}), "
                    f"{left_k} {OPS[c.op]} {right_k}"
                )
                continue
            if c.compare_as == "binary_text":
                parts.append(f"{_term(c.left, 'string')} {OPS[c.op]} {_term(c.right, 'string')}")
                continue
            t = types.get(c.left) or types.get(c.right) or const_type(c.left)
            if any(a.var in (c.left, c.right) for a in r.aggregates) or any(s.var in (c.left, c.right) for s in r.assignments):
                t = "integer"
            if t == "date" and c.op not in ("eq", "ne"):
                left_d, right_d = f"DayCmpL_{idx}_", f"DayCmpR_{idx}_"
                parts.append(
                    f"DayNum({_term(c.left, 'date')}, {left_d}), "
                    f"DayNum({_term(c.right, 'date')}, {right_d}), "
                    f"{left_d} {OPS[c.op]} {right_d}"
                )
                continue
            parts.append(f"{_term(c.left, t)} {OPS[c.op]} {_term(c.right, t)}")
    return parts


def _rule(prog, r):
    return f"{_atom(prog, r.head, is_head=True)} :- {', '.join(_rule_body_parts(prog, r))}."


def _join_args(*groups):
    items = [item for group in groups for item in group if item]
    return ", ".join(items)


def _state_bearing_agg(prog, a):
    rel = prog.relations[a.atom.relation]
    state_idx = next(
        (i for i, (t, c) in enumerate(zip(a.atom.terms, rel.row_columns))
         if c.name == "state" and c.type == "string" and t == "_"),
        None,
    )
    if state_idx is None:
        return None
    reason_idx = next(
        (i for i, (t, c) in enumerate(zip(a.atom.terms, rel.row_columns))
         if c.name == "reason" and c.type == "string" and t == "_"),
        None,
    )
    return state_idx, reason_idx


def _functional_sentinel(typ):
    if typ == "integer":
        return "0"
    if typ == "boolean":
        return '"false"'
    if typ == "date":
        return '"1970-01-01"'
    return '""'


def _functional_rules(prog, rel):
    """Lower a non-rational `role: functional` relation into stratified Soufflé Datalog relations
    emitting co-located `(key..., state, reason, value)` tuples over its closed domain."""
    name = rel.name
    dom = prog.relations[rel.domain]
    prefix = f"Func_{name}"
    key_decls = [f"{c.name}:{TYPE[c.type]}" for c in rel.key]
    key_vars = [f"K{j}_" for j in range(len(rel.key))]
    val_type = TYPE[rel.value.type]
    sentinel = _functional_sentinel(rel.value.type)
    empty_state = rel.empty_state or "unknown"
    empty_reason = rel.empty_reason or "no_match"

    dom_terms = key_vars + ["_"] * len(dom.values)
    lines = [
        f".decl {prefix}_Dom({_join_args(key_decls)})",
        f"{prefix}_Dom({_join_args(key_vars)}) :- {dom.name}({_join_args(dom_terms)}).",
        f".decl {prefix}_Cand({_join_args(key_decls, ['st:number', 'rsn:symbol', f'val:{val_type}'])})",
    ]

    for r in sorted(prog.rules_for(name), key=lambda x: x.id):
        head_keys = [_term(t, c.type) for t, c in zip(r.head.terms[:-1], rel.key)]
        head_val = _term(r.head.terms[-1], rel.value.type)
        state_aggs = [(idx, a, info) for idx, a in enumerate(r.aggregates)
                      if (info := _state_bearing_agg(prog, a)) is not None]
        if not state_aggs:
            parts = _rule_body_parts(prog, r)
            cand_args = _join_args(head_keys, ["0", '""', head_val])
            lines.append(f"{prefix}_Cand({cand_args}) :- {', '.join(parts)}.")
            continue

        agg_guards = []
        base_parts = _rule_body_parts(prog, r, include_aggregates=False, include_assignments=False, include_conditions=False)
        full_parts = _rule_body_parts(prog, r)
        for idx, a, (state_idx, reason_idx) in state_aggs:
            agg_rel = prog.relations[a.atom.relation]
            ap = f"Func_{r.id}_Agg{idx}"
            seen_vars = {}
            ak_decls, ak_vars, ak_rule_terms = [], [], []
            for t, c in zip(a.atom.terms, agg_rel.row_columns):
                if is_var(t) and t not in seen_vars:
                    k = len(ak_vars)
                    seen_vars[t] = k
                    ak_decls.append(f"k{k}:{TYPE[c.type]}")
                    ak_vars.append(f"AK{k}_")
                    ak_rule_terms.append(_term(t, c.type))

            lines.append(f".decl {ap}_Row({_join_args(ak_decls, ['st:number', 'rsn:symbol'])})")
            for st_name, st_code in (("invalid", 3), ("unknown", 2), ("not_applicable", 1), ("known", 0)):
                atom_terms = []
                for pos, (t, c) in enumerate(zip(a.atom.terms, agg_rel.row_columns)):
                    if pos == state_idx:
                        atom_terms.append(f'"{st_name}"')
                    elif pos == reason_idx:
                        atom_terms.append("Rsn_" if st_code > 0 else "_")
                    elif is_var(t):
                        atom_terms.append(f"AK{seen_vars[t]}_")
                    elif t == "_":
                        atom_terms.append("_")
                    else:
                        atom_terms.append(_term(t, c.type))
                atom_terms += ["_"] * len(agg_rel.values)
                rsn_head = "Rsn_" if (st_code > 0 and reason_idx is not None) else '""'
                lines.append(
                    f"{ap}_Row({_join_args(ak_vars, [str(st_code), rsn_head])}) :- "
                    f"{agg_rel.name}({_join_args(atom_terms)})."
                )
            lines += [
                f".decl {ap}_HasRow({_join_args(ak_decls)})",
                f"{ap}_HasRow({_join_args(ak_vars)}) :- {ap}_Row({_join_args(ak_vars, ['_', '_'])}).",
                f".decl {ap}_Max({_join_args(ak_decls, ['st:number'])})",
                (f"{ap}_Max({_join_args(ak_vars, ['MaxSt_'])}) :- "
                 f"{ap}_HasRow({_join_args(ak_vars)}), "
                 f"MaxSt_ = max St_ : {{ {ap}_Row({_join_args(ak_vars, ['St_', '_'])}) }}."),
                f".decl {ap}_NotMinRsn({_join_args(ak_decls, ['rsn:symbol'])})",
                (f"{ap}_NotMinRsn({_join_args(ak_vars, ['Rsn_'])}) :- "
                 f"{ap}_Max({_join_args(ak_vars, ['MaxSt_'])}), "
                 f"{ap}_Row({_join_args(ak_vars, ['MaxSt_', 'Rsn_'])}), "
                 f"{ap}_Row({_join_args(ak_vars, ['MaxSt_', 'Rsn2_'])}), Rsn2_ < Rsn_."),
                f".decl {ap}_MinRsn({_join_args(ak_decls, ['st:number', 'rsn:symbol'])})",
                (f"{ap}_MinRsn({_join_args(ak_vars, ['MaxSt_', 'Rsn_'])}) :- "
                 f"{ap}_Max({_join_args(ak_vars, ['MaxSt_'])}), "
                 f"{ap}_Row({_join_args(ak_vars, ['MaxSt_', 'Rsn_'])}), "
                 f"!{ap}_NotMinRsn({_join_args(ak_vars, ['Rsn_'])})."),
            ]
            agg_guards.append((ap, a.function, ak_rule_terms))

        # Known branch(es): every state-bearing aggregate is known (or empty for count/sum).
        # Build all combinations of (empty vs max=0) for count/sum, or (max=0) for min/max.
        known_combos = [[]]
        for ap, fn, ak_rule_terms in agg_guards:
            opts = [f"{ap}_Max({_join_args(ak_rule_terms, ['0'])})"]
            if fn in ("count", "sum"):
                opts.append(f"!{ap}_HasRow({_join_args(ak_rule_terms)})")
            known_combos = [combo + [opt] for combo in known_combos for opt in opts]
        known_head = _join_args(head_keys, ["0", '""', head_val])
        for combo in known_combos:
            lines.append(f"{prefix}_Cand({known_head}) :- {', '.join(full_parts + combo)}.")
        # Non-known branches: propagate each state-bearing aggregate's non-known state (and min/max empty).
        for ap, fn, ak_rule_terms in agg_guards:
            min_rsn_args = _join_args(ak_rule_terms, ["AggSt_", "AggRsn_"])
            prop_head = _join_args(head_keys, ["AggSt_", "AggRsn_", sentinel])
            prop_body = ", ".join(base_parts + [f"{ap}_MinRsn({min_rsn_args})", "AggSt_ > 0"])
            lines.append(f"{prefix}_Cand({prop_head}) :- {prop_body}.")
            if fn in ("min", "max"):
                empty_head = _join_args(head_keys, ["1", '"empty"', sentinel])
                empty_body = ", ".join(base_parts + [f"!{ap}_HasRow({_join_args(ak_rule_terms)})"])
                lines.append(f"{prefix}_Cand({empty_head}) :- {empty_body}.")

    inv_head = _join_args(key_vars, ['"invalid"', "Rsn_", sentinel])
    mv_head = _join_args(key_vars, ['"invalid"', '"multiple_values"', sentinel])
    unk_head = _join_args(key_vars, ['"unknown"', "Rsn_", sentinel])
    na_head = _join_args(key_vars, ['"not_applicable"', "Rsn_", sentinel])
    ok_head = _join_args(key_vars, ['"known"', '""', "Val_"])
    lines += [
        f".decl {prefix}_HasCand({_join_args(key_decls)})",
        f"{prefix}_HasCand({_join_args(key_vars)}) :- {prefix}_Dom({_join_args(key_vars)}), {prefix}_Cand({_join_args(key_vars, ['_', '_', '_'])}).",
        f".decl {prefix}_MaxSt({_join_args(key_decls, ['st:number'])})",
        (f"{prefix}_MaxSt({_join_args(key_vars, ['MaxSt_'])}) :- "
         f"{prefix}_HasCand({_join_args(key_vars)}), "
         f"MaxSt_ = max St_ : {{ {prefix}_Cand({_join_args(key_vars, ['St_', '_', '_'])}) }}."),
        f".decl {prefix}_Conflict({_join_args(key_decls)})",
        (f"{prefix}_Conflict({_join_args(key_vars)}) :- "
         f"{prefix}_Dom({_join_args(key_vars)}), "
         f"{prefix}_Cand({_join_args(key_vars, ['0', '_', 'V1_'])}), "
         f"{prefix}_Cand({_join_args(key_vars, ['0', '_', 'V2_'])}), V1_ != V2_."),
        f".decl {prefix}_NotMinRsn({_join_args(key_decls, ['st:number', 'rsn:symbol'])})",
        (f"{prefix}_NotMinRsn({_join_args(key_vars, ['St_', 'Rsn_'])}) :- "
         f"{prefix}_Dom({_join_args(key_vars)}), "
         f"{prefix}_Cand({_join_args(key_vars, ['St_', 'Rsn_', '_'])}), "
         f"{prefix}_Cand({_join_args(key_vars, ['St_', 'Rsn2_', '_'])}), St_ > 0, Rsn2_ < Rsn_."),
        f".decl {prefix}_MinRsn({_join_args(key_decls, ['st:number', 'rsn:symbol'])})",
        (f"{prefix}_MinRsn({_join_args(key_vars, ['St_', 'Rsn_'])}) :- "
         f"{prefix}_Dom({_join_args(key_vars)}), "
         f"{prefix}_Cand({_join_args(key_vars, ['St_', 'Rsn_', '_'])}), "
         f"St_ > 0, !{prefix}_NotMinRsn({_join_args(key_vars, ['St_', 'Rsn_'])})."),
        (f"{name}({_join_args(key_vars, [_quote(empty_state), _quote(empty_reason), sentinel])}) :- "
         f"{prefix}_Dom({_join_args(key_vars)}), !{prefix}_HasCand({_join_args(key_vars)})."),
        (f"{name}({mv_head}) :- "
         f"{prefix}_Conflict({_join_args(key_vars)})."),
        (f"{name}({inv_head}) :- "
         f"{prefix}_MaxSt({_join_args(key_vars, ['3'])}), !{prefix}_Conflict({_join_args(key_vars)}), "
         f"{prefix}_MinRsn({_join_args(key_vars, ['3', 'Rsn_'])})."),
        (f"{name}({unk_head}) :- "
         f"{prefix}_MaxSt({_join_args(key_vars, ['2'])}), !{prefix}_Conflict({_join_args(key_vars)}), "
         f"{prefix}_MinRsn({_join_args(key_vars, ['2', 'Rsn_'])})."),
        (f"{name}({na_head}) :- "
         f"{prefix}_MaxSt({_join_args(key_vars, ['1'])}), !{prefix}_Conflict({_join_args(key_vars)}), "
         f"{prefix}_MinRsn({_join_args(key_vars, ['1', 'Rsn_'])})."),
        (f"{name}({ok_head}) :- "
         f"{prefix}_MaxSt({_join_args(key_vars, ['0'])}), !{prefix}_Conflict({_join_args(key_vars)}), "
         f"{prefix}_Cand({_join_args(key_vars, ['0', '_', 'Val_'])})."),
    ]
    return lines


def _uses_date_order(prog):
    for r in prog.rules.values():
        types = {}
        for b in r.body:
            if b.polarity == "positive":
                for t, c in zip(b.atom.terms, prog.relations[b.atom.relation].row_columns):
                    types.setdefault(t, c.type)
        for c in r.conditions:
            if c.compare_as is None and c.op not in ("eq", "ne") and (types.get(c.left) == "date" or types.get(c.right) == "date"):
                return True
    return False


def program(prog):
    lines = []
    for rel in sorted(prog.relations.values(), key=lambda r: r.name):
        lines.append(_decl(rel))
        lines.append(f".input {rel.name}" if rel.role in INPUT else f".output {rel.name}")
    for r in sorted(prog.rules.values(), key=lambda r: r.id):
        if prog.relations[r.head.relation].role != "functional":
            lines.append(_rule(prog, r))
    for rel in sorted(prog.relations.values(), key=lambda r: r.name):
        if rel.role == "functional":
            lines += _functional_rules(prog, rel)
    if any(s.op == DAYS for r in prog.rules.values() for s in r.assignments) or _uses_date_order(prog):
        lines += _day_rules(prog)
    modes = {c.compare_as for r in prog.rules.values() for c in r.conditions if c.compare_as}
    if "utc_instant" in modes:
        lines += _utc_rules(prog)
    if modes:
        lines += _probe_rules()
    return "\n".join(lines) + "\n"


ACCESS = ("may_read", "may_read_full", "may_propose", "may_review", "may_publish")  # their second column names a kind
_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:[^"\\]|\\.)*"|[A-Za-z_][A-Za-z0-9_]*|:-|<=|>=|!=|\s+|.', re.S)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
COMPARE = ("=", "!=", "<", "<=", ">", ">=")
_DECL = re.compile(r"\.decl\s+([a-z0-9_]+)\s*\(([^)]*)\)")
_DECL_SYMBOL = re.compile(r":\s*(?:boolean|date)\b")
VIEW = "views.yaml"  # the origin of a rule the compiler lowers a view to (view_rules.bind): it is in no rule file


def _code(text):
    """The tokens of a rule text, and which of them are code: no space, no comment."""
    toks = _TOKEN.findall(text)
    return toks, [i for i, t in enumerate(toks) if not t.isspace() and not t.startswith(("//", "/*"))]


def _rules(toks, code):
    """The rules of a text, each as its code tokens. A rule ends at a full stop outside brackets. A full stop
    with a word right behind it starts a directive (.decl, .input, .output); a .decl ends at its closing
    bracket and is no rule."""
    current, depth, decl = [], 0, False
    for k, i in enumerate(code):
        t = toks[i]
        if t == "." and depth == 0:
            if k + 1 < len(code) and code[k + 1] == i + 1 and _NAME.match(toks[i + 1]):
                decl = toks[i + 1] == "decl"
            else:
                yield current
            current = []
            continue
        depth += (t in ("(", "{")) - (t in (")", "}"))
        current.append(i)
        if decl and depth == 0 and t == ")":
            current, decl = [], False


def bound(text, names):
    """The rule text of an imported pack under the names its tables have in the importing pack.
    The compiler binds the statements its parser made (rules_dl.remap_statement); this rewrites the
    text itself, token by token, so that Soufflé still reads what was written and not what the parser read.
    `names` maps a class or enum of the imported pack to its name in the importing pack. What follows it:
    a relation `kind` or `kind__slot`; the kind constant in the second column of an access atom; and a
    constant that a variable in that column is compared with, also through an equality between variables.
    Nothing else: not a value, not a variable."""
    names = {old: new for old, new in names.items() if old != new}
    if not names:
        return text
    toks, code = _code(text)

    def kind(i):
        if toks[i].startswith('"') and toks[i][1:-1] in names:
            toks[i] = '"' + names[toks[i][1:-1]] + '"'

    def var(i):
        return toks[i] != "_" and toks[i] not in _BOOL and _NAME.match(toks[i])

    def rule(s):
        """One rule, `s` its code tokens: the kind constants of its access atoms."""
        kind_vars, compared = set(), []
        for p, i in enumerate(s):
            if toks[i] in ACCESS and p + 1 < len(s) and toks[s[p + 1]] == "(":
                depth, term = 0, 0
                for j in s[p + 1:]:
                    depth += (toks[j] == "(") - (toks[j] == ")")
                    if depth == 0:
                        break
                    if depth == 1 and toks[j] == ",":
                        term += 1
                    elif depth == 1 and term == 1 and var(j):
                        kind_vars.add(toks[j])
                    elif depth == 1 and term == 1:
                        kind(j)
            elif toks[i] in COMPARE and 0 < p < len(s) - 1:
                compared.append((toks[i], s[p - 1], s[p + 1]))
        before = None
        while before != len(kind_vars):  # an equality between variables keeps the meaning of the column
            before = len(kind_vars)
            for op, a, b in compared:
                if op == "=" and var(a) and var(b) and {toks[a], toks[b]} & kind_vars:
                    kind_vars |= {toks[a], toks[b]}
        for _, a, b in compared:
            if toks[a] in kind_vars:
                kind(b)
            if toks[b] in kind_vars:
                kind(a)

    for s in _rules(toks, code):
        rule(s)
    # The relations: a name right before an opening bracket (a declaration, a head, a premise, an aggregate).
    for k, i in enumerate(code[:-1]):
        if (_NAME.match(toks[i]) and toks[code[k + 1]] == "("
                and toks[i] not in COMPARE_AS and not (k > 0 and toks[code[k - 1]] == "@")):
            head, sep, tail = toks[i].partition("__")
            toks[i] = names.get(head, head) + sep + tail
    return "".join(toks)


def view_bound(text, where, prog):
    """The rule text of the file `where` (its name in a rule's origin) with the atoms that the compiler bound
    to a relation of a view under that relation's name (docs/compiler.md, "Views that execute"). The compiler
    lowers a view to rules: per theory table the view maps, a relation that takes in the table and what the
    view supplies; and it binds the rules that read the table to that relation. Which atoms it bound is not
    decided again here. It is read from the compiled rule with the same origin: a relation that the text
    names and the compiled rule does not read stands for the one relation the compiled rule reads that a
    lowered rule fills from it alone. What the rule says still comes from its text."""
    lowered_rules = [r for r in prog.rules.values() if r.origin[0] == VIEW]
    if not lowered_rules:
        return text
    reads = {}
    for r in prog.rules.values():
        atoms = [r.head, *(b.atom for b in r.body), *(a.atom for a in r.aggregates)]
        reads.setdefault(r.origin, set()).update(a.relation for a in atoms)
    toks, code = _code(text)
    line = list(accumulate((t.count("\n") for t in toks), initial=1))  # of each token, as the compiler counts
    for s in _rules(toks, code):
        named = [i for p, i in enumerate(s[:-1])
                 if _NAME.match(toks[i]) and toks[s[p + 1]] == "(" and not (p > 0 and toks[s[p - 1]] == "@")]
        have = reads.get((where, line[named[0]]), set()) if named else set()  # the first name is the head
        for i in named:
            if toks[i] in prog.relations and toks[i] not in have:  # exactly one, or this harness cannot tell
                toks[i], = {r.head.relation for r in lowered_rules
                            if r.head.relation in have and [b.atom.relation for b in r.body] == [toks[i]]}
    return "".join(toks)


def lowered(prog):
    """The rules the compiler lowers a view to, with the declarations of their relations, as one more text
    (none without a view). No rule file holds them, so they come from the IR, written as `program` does."""
    rules = sorted((r for r in prog.rules.values() if r.origin[0] == VIEW), key=lambda r: r.id)
    made = sorted({r.head.relation for r in rules})
    return ["\n".join([_decl(prog.relations[n]) for n in made] + [_rule(prog, r) for r in rules]) + "\n"] if rules else []


def _native_lowered(prog, covered_origins, existing_texts):
    """Emit Soufflé declarations and rules for native rezono 1 derivations not covered by legacy `.dl` or pipe text."""
    declared = {m.group(1) for text in existing_texts for m in _DECL.finditer(text)}
    native_rules = [r for r in sorted(prog.rules.values(), key=lambda r: r.id) if r.origin[0] not in covered_origins]
    native_heads = {r.head.relation for r in native_rules}
    native_rels = [
        rel for rel in sorted(prog.relations.values(), key=lambda r: r.name)
        if rel.role in ("derived", "functional") and (rel.name not in declared or rel.name in native_heads)
    ]
    if not native_rules and not native_rels:
        return []
    lines = [_decl(rel) for rel in native_rels if rel.name not in declared]
    for r in native_rules:
        if prog.relations[r.head.relation].role != "functional":
            lines.append(_rule(prog, r))
    for rel in native_rels:
        if rel.role == "functional":
            lines += _functional_rules(prog, rel)
    return ["\n".join(lines) + "\n"] if lines else []


def closure(pack_dir, prog=None):
    """The rule texts of a pack's import closure (an imported pack brings its rules, and the
    program is the union over the closure): rules/*.dl and authored relational rule blocks in rezono/*.rezono
    of every imported pack, each pack after the packs it imports and under the importing pack's names (`bound`),
    then the pack's own, then the rules of the pack's decision tables (rezono_table, docs/rezono/publication.md
    §9.1): a table is a rule file of its pack whose text the compiler makes, so the oracle runs that text too.
    The names come from the compiler's binding of the schemas, as the tables in `source` do; what a rule says
    comes from its text.
    With `prog`, the compiled program, the texts read the relations of a view where the compiler bound them
    (`view_bound`), and the rules of the view and any native rezono 1 derivations follow."""
    from rezono_compiler import modules, pack, rezono_relational, rezono_table, rules as ir

    pack_dir = Path(pack_dir)
    meta, errors = pack.read_meta(pack_dir), []
    mods, imported = modules.load(pack_dir, meta, errors)
    names = modules.Names(mods, pack.snake, errors)
    assert not errors, errors
    embedded = {}
    for item in rezono_relational.sources(mods):
        embedded.setdefault(item.pack, []).append(item)
    texts = []  # (the file's name in a rule's origin, as rules_dl.read gives it; its text)
    for name in modules.dependency_order(imported, modules.direct(meta)):
        owner = imported[name]
        renames = pack.rename(mods, owner, names)
        entries = [(f.stem, f"{owner.name}:rules/{f.name}", f.read_text(encoding="utf-8"))
                   for f in sorted((owner.dir / "rules").glob("*.dl"))]
        entries += [(item.stem, f"{item.pack}:{item.file}", item.text) for item in embedded.get(owner.name, ())]
        entries.sort(key=lambda entry: entry[0])
        texts += [(where, bound(text, renames)) for _, where, text in entries]
    own = [(f.stem, f"rules/{f.name}", f.read_text(encoding="utf-8"))
           for f in sorted((pack_dir / "rules").glob("*.dl"))]
    own += [(item.stem, item.file, item.text) for item in embedded.get(meta["name"], ())]
    own.sort(key=lambda entry: entry[0])
    texts += [(where, text) for _, where, text in own]
    # A table reads the tables of its kind, never a view, so its text is not bound to one (`view_bound`).
    forms = {m.rel: m.form for m in mods if m.pack_dir == pack_dir and m.form is not None}
    has_tables = any(isinstance(decl, dict) and "extend" in decl
                     for form in forms.values() for decl in form.get("module", {}).get("decls", ()))
    generated_tables = (rezono_table.lower_pack(pack.read(pack_dir), meta, pack_dir, errors, forms=forms)
                        if has_tables else [])
    tables = [g.text for g in generated_tables]
    assert not errors, errors
    has_rezono_1 = any(m.form and m.form.get("format") == "rezono.module/5" for m in mods)
    if prog is None and has_rezono_1:
        prog = ir.load(pack.read(pack_dir).rules)
    if prog is None:
        return [text for _, text in texts] + tables
    covered = {where for where, _ in texts} | {g.module for g in generated_tables} | {VIEW}
    base_texts = [view_bound(text, where, prog) for where, text in texts] + tables + lowered(prog)
    return base_texts + _native_lowered(prog, covered, base_texts)


def _var(tok):
    return tok != "_" and tok not in _BOOL and bool(_NAME.match(tok))


def _operand(tok):
    return _var(tok) or (len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"')


def _rewrite_source(text, counter):
    """Rewrite typed scalar comparisons (`utc_instant`/`binary_text`), `@days(text, origin)`
    assignments, and `TRUE`/`FALSE` boolean literals in rule text into Soufflé constructs,
    preserving comments and surrounding layout."""
    toks, code = _code(text)
    modes = set()
    has_days = False
    literals = {toks[i] for i in code if len(toks[i]) >= 2 and toks[i][0] == '"' and toks[i][-1] == '"'}
    p = 0
    while p < len(code):
        tok0 = toks[code[p]]
        if p + 8 < len(code):
            if (tok0 in COMPARE_AS
                    and toks[code[p + 1]] == "("
                    and _operand(toks[code[p + 2]])
                    and toks[code[p + 3]] == ")"
                    and toks[code[p + 4]] in COMPARE
                    and toks[code[p + 5]] == tok0
                    and toks[code[p + 6]] == "("
                    and _operand(toks[code[p + 7]])
                    and toks[code[p + 8]] == ")"):
                left, op, right = toks[code[p + 2]], toks[code[p + 4]], toks[code[p + 7]]
                modes.add(tok0)
                if tok0 == "utc_instant":
                    n = next(counter)
                    left_k, right_k = f"UtcL_{n}_", f"UtcR_{n}_"
                    replacement = f"UtcKey({left}, {left_k}), UtcKey({right}, {right_k}), {left_k} {op} {right_k}"
                else:
                    replacement = f"{left} {op} {right}"
                toks[code[p]] = replacement
                for j in range(code[p] + 1, code[p + 8] + 1):
                    toks[j] = ""
                p += 9
                continue
            if (_var(tok0)
                    and toks[code[p + 1]] == "="
                    and toks[code[p + 2]] == "@"
                    and toks[code[p + 3]] == DAYS
                    and toks[code[p + 4]] == "("
                    and _operand(toks[code[p + 5]])
                    and toks[code[p + 6]] == ","
                    and _operand(toks[code[p + 7]])
                    and toks[code[p + 8]] == ")"):
                left, right = toks[code[p + 5]], toks[code[p + 7]]
                has_days = True
                n = next(counter)
                left_d, right_d = f"DayL_{n}_", f"DayR_{n}_"
                toks[code[p]] = f"DayNum({left}, {left_d}), DayNum({right}, {right_d}), {tok0} = {left_d} - {right_d}"
                for j in range(code[p] + 1, code[p + 8] + 1):
                    toks[j] = ""
                p += 9
                continue
        if tok0 in _BOOL:
            toks[code[p]] = _quote(_BOOL[tok0])
        p += 1
    return "".join(toks), modes, has_days, literals


def _rewrite_date_orders(text, counter, rel_types):
    """Rewrite native date order comparisons (`<`, `<=`, `>`, `>=`) in rule text to `DayNum` comparisons."""
    toks, code = _code(text)
    has_days = False
    for s in _rules(toks, code):
        sep = next((p for p, i in enumerate(s) if toks[i] == ":-"), None)
        if sep is None:
            continue
        date_vars = set()
        brace = 0
        p = sep + 1
        while p < len(s):
            t = toks[s[p]]
            if t == "{":
                brace += 1
            elif t == "}":
                brace -= 1
            elif (brace == 0 and p + 1 < len(s) and _NAME.match(t) and toks[s[p + 1]] == "("
                  and not (p > sep + 1 and toks[s[p - 1]] in ("!", "@")) and t not in COMPARE_AS):
                col_types = rel_types.get(t)
                depth, arg_idx, arg_tokens = 1, 0, []
                q = p + 2
                while q < len(s) and depth > 0:
                    qt = toks[s[q]]
                    if qt == "(":
                        depth += 1
                        arg_tokens.append(qt)
                    elif qt == ")":
                        depth -= 1
                        if depth == 0:
                            if col_types and arg_idx < len(col_types) and col_types[arg_idx] == "date" and len(arg_tokens) == 1 and _var(arg_tokens[0]):
                                date_vars.add(arg_tokens[0])
                        else:
                            arg_tokens.append(qt)
                    elif qt == "," and depth == 1:
                        if col_types and arg_idx < len(col_types) and col_types[arg_idx] == "date" and len(arg_tokens) == 1 and _var(arg_tokens[0]):
                            date_vars.add(arg_tokens[0])
                        arg_idx += 1
                        arg_tokens = []
                    else:
                        arg_tokens.append(qt)
                    q += 1
                p = q
                continue
            p += 1
        if not date_vars:
            continue
        brace = 0
        paren = 0
        for p in range(sep + 1, len(s)):
            t = toks[s[p]]
            if t == "{":
                brace += 1
            elif t == "}":
                brace -= 1
            elif t == "(":
                paren += 1
            elif t == ")":
                paren -= 1
            elif (brace == 0 and paren == 0 and t in ("<", "<=", ">", ">=")
                  and p >= sep + 2 and p + 1 < len(s)
                  and toks[s[p - 2]] in (",", ":-")
                  and (p + 2 == len(s) or toks[s[p + 2]] == ",")
                  and toks[s[p - 1]] in date_vars and toks[s[p + 1]] in date_vars):
                left, right = toks[s[p - 1]], toks[s[p + 1]]
                n = next(counter)
                left_d, right_d = f"DayL_{n}_", f"DayR_{n}_"
                toks[s[p - 1]] = f"DayNum({left}, {left_d}), DayNum({right}, {right_d}), {left_d} {t} {right_d}"
                for j in range(s[p - 1] + 1, s[p + 1] + 1):
                    toks[j] = ""
                has_days = True
    return "".join(toks), has_days


def source(prog, texts):
    """Rule files as one Soufflé program: declarations and inputs for the tables they read (from the IR, as
    the compiler binds them), the files as written, and an output per derived relation. So the oracle also
    sees what the parser read, not only the IR it made. `texts` is the whole program: for a pack, the rule
    files of its import closure (`closure`, `pack_source`). A relation that an importing pack declares
    again (`// @extend`, with the same columns) is declared once; any other second declaration stays, and
    Soufflé refuses it."""
    lines, columns, kept, modes, has_days, literals, counter = [], {}, [], set(), False, set(), count()
    rel_types = {name: tuple(c.type for c in rel.row_columns) for name, rel in prog.relations.items()}
    for text in texts:
        earlier = dict(columns)  # what the files before this one declare

        def once(m):
            name, cols = m.group(1), re.sub(r"\s+", "", m.group(2))
            columns.setdefault(name, cols)
            if earlier.get(name) == cols:
                return ""
            return f".decl {name}({_DECL_SYMBOL.sub(': symbol', m.group(2))})"
        rewritten, found, found_days, lits = _rewrite_source(_DECL.sub(once, text), counter)
        rewritten, found_date_order = _rewrite_date_orders(rewritten, counter, rel_types)
        kept.append(rewritten)
        modes |= found
        has_days = has_days or found_days or found_date_order
        literals |= lits
    if any("UtcKey(" in text for text in kept):
        modes.add("utc_instant")
    modes |= {c.compare_as for r in prog.rules.values() for c in r.conditions if c.compare_as}
    uses_days = (has_days or any("DayNum(" in text for text in kept)
                 or any(s.op == DAYS for r in prog.rules.values() for s in r.assignments)
                 or _uses_date_order(prog))
    declared = set(columns)
    for rel in sorted(prog.relations.values(), key=lambda r: r.name):
        if rel.role in INPUT and rel.name not in declared:
            lines += [_decl(rel), f".input {rel.name}"]
    for text in kept:
        lines.append(re.sub(r"^\s*\.(input|output)\b[^\n]*$", "", text, flags=re.M))
    lines += [f".input {n}" for n in sorted(declared) if prog.relations.get(n) and prog.relations[n].role == "base"]
    lines += [f".output {r.name}" for r in sorted(prog.relations.values(), key=lambda r: r.name)
              if r.role in ("derived", "functional")]
    if uses_days:
        lines += _day_rules(prog, literals)
    if "utc_instant" in modes:
        lines += _utc_rules(prog, literals)
    if modes:
        lines += _probe_rules()
    return "\n".join(lines) + "\n"


def pack_source(prog, pack_dir):
    """A pack's rules as written, over its import closure, as one Soufflé program (`closure`, `source`), with
    the rules of a view the pack reads a theory through as the compiler lowers them."""
    return source(prog, closure(pack_dir, prog))


def run(prog, data, workdir=None, program_text=None):
    """Evaluate with Soufflé: {relation: set of tuples of str} for every derived relation."""
    if workdir is not None:
        Path(workdir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir) as d:
        d = Path(d)
        (d / "facts").mkdir()
        (d / "out").mkdir()
        for name, rel in prog.relations.items():
            if rel.role in INPUT:
                cols = rel.key + rel.values
                rows = data.get(name, [])
                (d / "facts" / f"{name}.facts").write_text(
                    "".join("\t".join(_fact_cell(v, c.type) for v, c in zip(r, cols)) + "\n" for r in rows),
                    encoding="utf-8",
                )
        text = program_text if program_text is not None else program(prog)
        if f".input {_PROBE}Symbol" in text:
            (d / "facts" / f"{_PROBE}Symbol.facts").write_text("\n".join(_PROBE_SYMBOLS) + "\n", encoding="utf-8")
        (d / "p.dl").write_text(text, encoding="utf-8")
        subprocess.run(["souffle", "-j", "1", "-F", str(d / "facts"), "-D", str(d / "out"), str(d / "p.dl")],
                       check=True, capture_output=True, text=True, encoding="utf-8")
        probe = d / "out" / f"{_PROBE}.csv"
        if probe.is_file():
            got = {tuple(line.split("\t")) for line in probe.read_text(encoding="utf-8").splitlines() if line}
            want = {(a, b) for a in _PROBE_SYMBOLS for b in _PROBE_SYMBOLS if a.encode("utf-8") < b.encode("utf-8")}
            if got != want:
                raise AssertionError("Soufflé did not order symbols by their UTF-8 bytes")
        out = {}
        for name, rel in prog.relations.items():
            if rel.role in ("derived", "functional"):
                text = (d / "out" / f"{name}.csv").read_text(encoding="utf-8")
                out[name] = {tuple(line.split("\t")) for line in text.splitlines() if line}
        return out


def version():
    return subprocess.run(["souffle", "--version"], capture_output=True, text=True).stdout.split("\n")[1].strip()
