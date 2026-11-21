"""Lower `require` declarations in a `rezono 1` module to `rezono.rules/2` IR.

The decision is decisions/language-requirements.md (sections 1-3):
- Every `require <name>(k1: T1, ..., km: Tm) [invariant]` lowers directly to:
  1. Outcome relation `<name>` (`role: functional`, closed domain, `value: boolean`,
     `conflict_policy: publish`, `empty_state: not_applicable`, `empty_reason: no_match`).
  2. Finding/violation relation `<name>_violation` (`role: derived`, `invariant` per header,
     columns `(k1, ..., km, clause: integer, target: string, bound: string, observed: integer)`).
  3. Scoped helper match and four-state relations at strictly lower strata.
- `means` and `@` lower to bundle rule messages and `source` on `<name>` and `<name>_violation`.
- Open trigger kinds and open `over` domains are refused with `R004` (`functional_open_domain`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from . import modules, rezono_derived, rules_dl, spans
from .diagnostics import Diagnostic

REZONO_1_FORMAT = rezono_derived.REZONO_1_FORMAT
KNOWN = rezono_derived.KNOWN
UNKNOWN = rezono_derived.UNKNOWN
INVALID = rezono_derived.INVALID
NOT_APPLICABLE = rezono_derived.NOT_APPLICABLE
RESERVED_FUNC_COLS = frozenset({"state", "reason", "value"})


def is_requirement(decl: object) -> bool:
    """Whether a module declaration is a `rezono 1` `require <name>(...)` block."""
    return isinstance(decl, dict) and isinstance(decl.get("require"), str)


@dataclass
class _ClauseSpec:
    index: int
    binder: str
    target_name: str
    target_open: bool
    bound_op: str
    bound_count: int
    bound_tag: str
    has_explicit_bound: bool
    row_key: list[tuple[str, tuple]]
    row_cols: list[tuple[str, str]]
    row_terms: list[tuple]
    target_lit: tuple
    tuple_binders: dict[str, dict[str, tuple[tuple, str]]]
    where: dict | None


class _ExprLowering(rezono_derived.Lowering):
    """Four-valued expression lowering with customizable domain literals, key columns, and tuple binders."""

    def __init__(
        self,
        signature: rezono_derived.Signature,
        signatures: Mapping[str, rezono_derived.Signature],
        pack,
        names: modules.Names,
        taken: set[str],
        out: tuple[list, list],
        *,
        domain_lits: list[tuple],
        active_key: list[tuple[str, tuple]],
        active_cols: list[tuple[str, str]],
        active_terms: list[tuple] | None = None,
        tuple_binders: Mapping[str, Mapping[str, tuple[tuple, str]]] | None = None,
        helper_counter: list[int] | None = None,
    ):
        self._custom_domain = list(domain_lits)
        self._active_key = list(active_key)
        self._active_terms = list(active_terms) if active_terms is not None else [("var", name) for name, _ in active_key]
        self._tuple_binders = dict(tuple_binders or {})
        super().__init__(signature, signatures, pack, names, taken, out)
        self.env = dict(active_key)
        self.used = {name for name, _ in active_key} | {t[1] for t in self._active_terms if t[0] == "var"}
        self._key_cols = list(active_cols)
        self._state_cols = self._key_cols + [("state", "string"), ("reason", "string")]
        self._counter = helper_counter if helper_counter is not None else [0]

    def domain(self) -> list[tuple]:
        return list(self._custom_domain)

    def key_terms(self) -> list[tuple]:
        return list(self._active_terms)

    def next_helper(self, tag: str) -> str:
        self._counter[0] += 1
        return self.helper(f"h{self._counter[0]}_{tag}")

    def declare_absence(self, name: str, columns: list[tuple[str, str]]) -> None:
        self.statements.append(("decl", name, columns, self.line, None, False, True, None, False, None, False))

    def add_absence_helper(self, name: str, columns: list[tuple[str, str]], terms: list[tuple], body: list[tuple]) -> None:
        if name not in self._declared_helpers:
            self.declare_absence(name, columns)
            self._declared_helpers.add(name)
        self.rule(name, terms, body)

    def eval_path_val(self, at: str, path: list):
        if len(path) == 2 and path[0] in self._tuple_binders:
            cols = self._tuple_binders[path[0]]
            if path[1] not in cols:
                self.site.refuse(at, f"{path[0]} has no column {path[1]}", "R001")
            term, col_type = cols[path[1]]
            return rezono_derived.ValEval(col_type, (rezono_derived.ValBranch((), (), (), term),), None)
        return super().eval_path_val(at, path)


def _opened_relations(pack, native: tuple[rules_dl.NativeSource, ...], derived: tuple[rules_dl.NativeSource, ...]) -> set[str]:
    """All open base tables and non-@absence derived relations that positively read an open relation."""
    opened = {name for name, world in rules_dl.base_worlds(pack).items() if world == "open"}
    absences: set[str] = set()
    all_rules = []
    for src in (*native, *derived):
        for stmt in src.statements:
            if stmt[0] == "decl" and stmt[6]:
                absences.add(stmt[1])
            elif stmt[0] == "rule":
                all_rules.append(stmt)
    changed = True
    while changed:
        changed = False
        for _, (head, _, _), body, _ in all_rules:
            if head in opened or head in absences:
                continue
            if any(item[0] == "lit" and item[1] == "positive" and item[2][0] in opened for item in body):
                opened.add(head)
                changed = True
    return opened


def _derived_sets(
    native: tuple[rules_dl.NativeSource, ...],
    derived: tuple[rules_dl.NativeSource, ...],
    pack,
    mods: Iterable[modules.Module],
    names: modules.Names,
) -> dict[str, rezono_derived.Signature]:
    """Build Bool set signatures declared by native/derived rezono 1 sources."""
    sigs: dict[str, rezono_derived.Signature] = {}
    dummy_site = rezono_derived.Site("", "", {})
    mod_by_stem = {m.file.stem: m for m in mods}
    for src in (*native, *derived):
        module = mod_by_stem.get(src.stem)
        for stmt in src.statements:
            if stmt[0] != "decl":
                continue
            name, cols = stmt[1], stmt[2]
            key = [(col_name, ("scalar", col_type)) for col_name, col_type in cols]
            sigs[name] = rezono_derived.Signature(name, "/decls/0", {}, dummy_site, module, key, "set")
    return sigs


def _safe_key_col_names(param_names: list[str]) -> list[str]:
    used = set(RESERVED_FUNC_COLS)
    out: list[str] = []
    for name in param_names:
        col = name
        if col in used:
            col = f"key_{name}"
            while col in used:
                col = f"key_{col}"
        used.add(col)
        out.append(col)
    return out


def _open_domain_diag(name: str, site: rezono_derived.Site, at: str, domain: str, is_over: bool) -> Diagnostic:
    line, column = site.place(at)
    what = f"its domain {domain} reads an open world" if is_over else f"its kind {domain} is open"
    message = (
        f"functional_open_domain: {name} has no finite closed domain, because {what}; "
        "a functional requirement needs a closed one (decisions/language-requirements.md section 2)"
    )
    return Diagnostic("R004", message, f"{site.file}#{at}", (site.file, line, column))


def _lower_requirement(
    site: rezono_derived.Site,
    module: modules.Module,
    names: modules.Names,
    pack,
    at: str,
    decl: dict,
    set_signatures: Mapping[str, rezono_derived.Signature],
    opened: set[str],
    taken: set[str],
    out: tuple[list, list],
) -> tuple[rezono_derived.Note | None, list[Diagnostic]]:
    name = decl["require"]
    viol_name = f"{name}_violation"
    if name in taken:
        site.refuse(at, f"{name} is already declared in this pack")
    if viol_name in taken:
        site.refuse(at, f"{viol_name} is already declared in this pack")
    taken.add(name)
    taken.add(viol_name)

    params = decl.get("params") or []
    if not isinstance(params, list) or not params:
        site.refuse(at, "a `require` declaration needs at least one parameter", "R000")
    key_params: list[tuple[str, tuple]] = []
    seen_params: set[str] = set()
    for idx, param in enumerate(params):
        pname = param.get("name")
        if not isinstance(pname, str) or not pname or pname in seen_params:
            site.refuse(f"{at}/params/{idx}", "distinct parameter names are required", "R000")
        seen_params.add(pname)
        ptyp = rezono_derived._type(site, names, pack, module, f"{at}/params/{idx}", param.get("type"))
        key_params.append((pname, ptyp))

    over = decl.get("over")
    if over is not None:
        if not isinstance(over, dict) or list(over.get("args") or ()) != [p for p, _ in key_params]:
            site.refuse(f"{at}/over", "the arguments of `over` are the parameters, in their order", "R000")
        raw_dom = over.get("relation")
        if not isinstance(raw_dom, str):
            site.refuse(f"{at}/over", "`over` needs a relation name", "R000")
        domain = raw_dom if raw_dom in set_signatures else names.resolve(module.id, raw_dom)
        if len(key_params) == 1 and domain in pack.kinds:
            if key_params[0][1] != ("kind", domain):
                site.refuse(f"{at}/over", f"`over {raw_dom}` does not match parameter type", "R003")
        elif domain in set_signatures:
            dom_cols = set_signatures[domain].key
            if [rezono_derived.ir_type(pack, t) for _, t in key_params] != [rezono_derived.ir_type(pack, t) for _, t in dom_cols]:
                site.refuse(f"{at}/over", f"`over {raw_dom}` columns do not match requirement parameters", "R003")
        else:
            site.refuse(f"{at}/over", f"`over` names a kind or derived Bool set of this pack, not {raw_dom}", "R001")
    else:
        if len(key_params) != 1:
            site.refuse(at, "a multi-key `require` declaration needs `over <relation>(...)`", "R000")
        if key_params[0][1][0] != "kind":
            site.refuse(f"{at}/params/0", "a single-key `require` without `over` needs a kind parameter", "R000")
        domain = key_params[0][1][1]

    if domain in opened:
        return None, [_open_domain_diag(name, site, at, domain, over is not None)]

    exists_list = decl.get("exists") or []
    if not isinstance(exists_list, list) or not exists_list:
        site.refuse(at, "a `require` declaration needs at least one `exists` clause", "R000")

    options = decl.get("options") or []
    is_invariant = any(isinstance(opt, dict) and opt.get("invariant") is True for opt in options)

    line, column = site.place(at)
    key_col_names = _safe_key_col_names([p for p, _ in key_params])
    key_cols = [(col, rezono_derived.ir_type(pack, typ)) for col, (_, typ) in zip(key_col_names, key_params)]
    key_terms = [("var", p) for p, _ in key_params]
    domain_lits = [("lit", "positive", (domain, key_terms, line))]

    clauses: list[_ClauseSpec] = []
    for idx, raw_clause in enumerate(exists_list):
        cat = f"{at}/exists/{idx}"
        binder = raw_clause.get("binder")
        if not isinstance(binder, str) or not binder:
            site.refuse(cat, "an `exists` clause needs a binder name", "R000")
        if binder in seen_params:
            site.refuse(cat, f"{binder} is already a requirement parameter", "R011")
        bound = raw_clause.get("bound")
        if bound is None:
            bound_op, bound_count, has_explicit_bound = "at_least", 1, False
        else:
            bound_op = bound["op"]
            bound_count = int(bound["count"])
            has_explicit_bound = True
        bound_tag = f"{bound_op}:{bound_count}"

        if "kind" in raw_clause:
            raw_target = raw_clause["kind"]
            t_kind = names.resolve(module.id, raw_target)
            if t_kind not in pack.kinds:
                site.refuse(cat, f"{raw_target} is not a kind of the pack", "R001")
            target_name = t_kind
            target_open = t_kind in opened
            r_col = f"row_{binder}" if binder in RESERVED_FUNC_COLS or binder in key_col_names else binder
            row_key = [(binder, ("kind", t_kind))]
            row_cols = [(r_col, rezono_derived.ir_type(pack, ("kind", t_kind)))]
            row_terms = [("var", binder)]
            target_lit = ("lit", "positive", (t_kind, row_terms, line))
            tuple_binders: dict[str, dict[str, tuple[tuple, str]]] = {}
        elif "relation" in raw_clause:
            raw_target = raw_clause["relation"]
            t_rel = raw_target if raw_target in set_signatures else names.resolve(module.id, raw_target)
            if t_rel not in set_signatures:
                site.refuse(cat, f"{raw_target} is not a Bool set derived in this pack", "R001")
            target_name = t_rel
            target_open = t_rel in opened
            target_cols = set_signatures[t_rel].key
            row_key = []
            row_cols = []
            row_terms = []
            tb: dict[str, tuple[tuple, str]] = {}
            for c_idx, (col_name, col_typ) in enumerate(target_cols):
                var_name = f"{binder}__{col_name}_{idx}_{c_idx}"
                col_ir = rezono_derived.ir_type(pack, col_typ)
                row_cols.append((f"row_{col_name}", col_ir))
                term = ("var", var_name)
                row_terms.append(term)
                tb[col_name] = (term, col_ir)
            target_lit = ("lit", "positive", (t_rel, row_terms, line))
            tuple_binders = {binder: tb}
        else:
            site.refuse(cat, "an `exists` clause needs a kind or relation target", "R000")
            raise AssertionError("unreachable")

        clauses.append(_ClauseSpec(
            index=idx,
            binder=binder,
            target_name=target_name,
            target_open=target_open,
            bound_op=bound_op,
            bound_count=bound_count,
            bound_tag=bound_tag,
            has_explicit_bound=has_explicit_bound,
            row_key=row_key,
            row_cols=row_cols,
            row_terms=row_terms,
            target_lit=target_lit,
            tuple_binders=tuple_binders,
            where=raw_clause.get("where"),
        ))

    statements, columns = out
    helper_counter = [0]
    req_sig = rezono_derived.Signature(
        name, at, decl, site, module, key_params, "functional",
        value_type="boolean", domain=domain,
    )
    ctx = _ExprLowering(
        req_sig, set_signatures, pack, names, taken, out,
        domain_lits=domain_lits, active_key=key_params, active_cols=key_cols,
        helper_counter=helper_counter,
    )

    # Declare `<name>` (functional) and `<name>_violation` (derived).
    func_meta = {
        "domain": domain,
        "value": {"name": "value", "type": "boolean"},
        "conflict_policy": "publish",
        "empty_state": "not_applicable",
        "empty_reason": "no_match",
    }
    statements.append(("functional", name, key_cols, line, func_meta))
    viol_cols = key_cols + [
        ("clause", "integer"),
        ("target", "string"),
        ("bound", "string"),
        ("observed", "integer"),
    ]
    statements.append(("decl", viol_name, viol_cols, line, None, is_invariant, False, None, False, None, False))

    # Step 1: evaluate `when P(k)`.
    trig_t_all = True
    trig_lits: list[tuple] = []
    trig_st_rel: str | None = None
    if "when" in decl:
        trig_eval = ctx.eval_bool(f"{at}/when", decl["when"])
        if trig_eval.s_rel is not None:
            trig_st_name = ctx.next_helper("trig_st")
            rsn_v = ("var", ctx.fresh("rsn"))
            for st_lit in (UNKNOWN, INVALID):
                ctx.add_helper(
                    trig_st_name, ctx._state_cols, key_terms + [st_lit, rsn_v],
                    domain_lits + [ctx.lit(trig_eval.s_rel, key_terms + [st_lit, rsn_v])],
                )
            trig_st_rel = ctx.helper_or_none(trig_st_name)
        if trig_eval.f_all or (not trig_eval.t_all and trig_eval.t_rel is None):
            trig_t_all = False
        elif not trig_eval.t_all and trig_eval.t_rel is not None:
            trig_lits = [ctx.lit(trig_eval.t_rel, key_terms)]

    sat_rels: list[str] = []
    viol_rels: list[str] = []
    clause_states: list[str] = []
    viol_rules_emitted = 0
    func_rules_emitted = 0

    if trig_t_all:
        for c in clauses:
            match_rel = ctx.next_helper(f"c{c.index}_match")
            match_cols = key_cols + c.row_cols
            match_terms = key_terms + c.row_terms

            w_inv_rel: str | None = None
            w_unk_rel: str | None = None
            if c.where is not None:
                c_sig = rezono_derived.Signature(
                    name, at, decl, site, module, key_params + c.row_key, "functional",
                    value_type="boolean", domain=domain,
                )
                w_ctx = _ExprLowering(
                    c_sig, set_signatures, pack, names, taken, out,
                    domain_lits=domain_lits + trig_lits + [c.target_lit],
                    active_key=key_params + c.row_key,
                    active_cols=match_cols,
                    active_terms=match_terms,
                    tuple_binders=c.tuple_binders,
                    helper_counter=helper_counter,
                )
                # Ensure `row_terms` are in `w_ctx.env` / `w_ctx.used` for relation targets.
                for t in c.row_terms:
                    w_ctx.used.add(t[1])
                w_eval = w_ctx.eval_bool(f"{at}/exists/{c.index}/where", c.where)
                if w_eval.t_all:
                    ctx.add_helper(match_rel, match_cols, match_terms, domain_lits + trig_lits + [c.target_lit])
                elif w_eval.t_rel is not None:
                    ctx.add_helper(
                        match_rel, match_cols, match_terms,
                        domain_lits + trig_lits + [c.target_lit, ctx.lit(w_eval.t_rel, match_terms)],
                    )
                else:
                    ctx.add_helper(
                        match_rel, match_cols, match_terms,
                        domain_lits + trig_lits + [c.target_lit, ("cmp", "eq", ("const", "1", "integer"), ("const", "0", "integer"))],
                    )
                if w_eval.s_rel is not None:
                    inv_name = ctx.next_helper(f"c{c.index}_w_inv")
                    unk_name = ctx.next_helper(f"c{c.index}_w_unk")
                    rsn_v = ("var", ctx.fresh("rsn"))
                    ctx.add_helper(
                        inv_name, ctx._state_cols, key_terms + [INVALID, rsn_v],
                        domain_lits + trig_lits + [ctx.lit(w_eval.s_rel, match_terms + [INVALID, rsn_v])],
                    )
                    ctx.add_helper(
                        unk_name, ctx._state_cols, key_terms + [UNKNOWN, rsn_v],
                        domain_lits + trig_lits + [ctx.lit(w_eval.s_rel, match_terms + [UNKNOWN, rsn_v])],
                    )
                    w_inv_rel = ctx.helper_or_none(inv_name)
                    w_unk_rel = ctx.helper_or_none(unk_name)
            else:
                ctx.add_helper(match_rel, match_cols, match_terms, domain_lits + trig_lits + [c.target_lit])

            has_inv_rel: str | None = None
            if w_inv_rel is not None:
                has_inv_name = ctx.next_helper(f"c{c.index}_has_inv")
                ctx.add_helper(
                    has_inv_name, key_cols, key_terms,
                    domain_lits + [ctx.lit(w_inv_rel, key_terms + [INVALID, ("var", ctx.fresh("rsn"))])],
                )
                has_inv_rel = ctx.helper_or_none(has_inv_name)

            has_match_rel: str | None = None
            if not c.has_explicit_bound or c.target_open:
                has_match_name = ctx.next_helper(f"c{c.index}_has_match")
                ctx.add_helper(
                    has_match_name, key_cols, key_terms,
                    domain_lits + trig_lits + [ctx.lit(match_rel, match_terms)],
                )
                has_match_rel = ctx.helper_or_none(has_match_name)

            c_state_name = ctx.next_helper(f"c{c.index}_state")
            if c.target_open:
                # Plain `world open` target without `complete by`: never emits a violation.
                no_inv_rel: str | None = None
                if has_inv_rel is not None:
                    rsn_v = ("var", ctx.fresh("rsn"))
                    ctx.add_helper(
                        c_state_name, ctx._state_cols, key_terms + [INVALID, rsn_v],
                        domain_lits + trig_lits + [ctx.lit(w_inv_rel, key_terms + [INVALID, rsn_v])],
                    )
                    no_inv_name = ctx.next_helper(f"c{c.index}_no_inv")
                    ctx.add_absence_helper(
                        no_inv_name, key_cols, key_terms,
                        domain_lits + trig_lits + [ctx.lit(has_inv_rel, key_terms, False)],
                    )
                    no_inv_rel = ctx.helper_or_none(no_inv_name)
                inv_guard = [] if no_inv_rel is None else [ctx.lit(no_inv_rel, key_terms)]
                open_unk_const = ("const", "open_world", "string")
                if not c.has_explicit_bound and has_match_rel is not None:
                    c_sat_name = ctx.next_helper(f"c{c.index}_sat")
                    ctx.add_helper(
                        c_sat_name, key_cols, key_terms,
                        domain_lits + trig_lits + [ctx.lit(has_match_rel, key_terms)] + inv_guard,
                    )
                    sat_rels.append(c_sat_name)
                    no_match_name = ctx.next_helper(f"c{c.index}_no_match")
                    ctx.add_absence_helper(
                        no_match_name, key_cols, key_terms,
                        domain_lits + trig_lits + [ctx.lit(has_match_rel, key_terms, False)],
                    )
                    ctx.add_helper(
                        c_state_name, ctx._state_cols, key_terms + [UNKNOWN, open_unk_const],
                        domain_lits + trig_lits + [ctx.lit(no_match_name, key_terms)] + inv_guard,
                    )
                else:
                    ctx.add_helper(
                        c_state_name, ctx._state_cols, key_terms + [UNKNOWN, open_unk_const],
                        domain_lits + trig_lits + inv_guard,
                    )
                if c_state_rel := ctx.helper_or_none(c_state_name):
                    clause_states.append(c_state_rel)
                continue

            # Closed target: complete for every key `k`.
            if w_inv_rel is not None:
                rsn_v = ("var", ctx.fresh("rsn"))
                ctx.add_helper(
                    c_state_name, ctx._state_cols, key_terms + [INVALID, rsn_v],
                    domain_lits + trig_lits + [ctx.lit(w_inv_rel, key_terms + [INVALID, rsn_v])],
                )
            if w_unk_rel is not None:
                rsn_v = ("var", ctx.fresh("rsn"))
                unk_body = domain_lits + trig_lits + [ctx.lit(w_unk_rel, key_terms + [UNKNOWN, rsn_v])]
                if has_inv_rel is not None:
                    unk_body.append(ctx.lit(has_inv_rel, key_terms, False))
                if not c.has_explicit_bound and has_match_rel is not None:
                    unk_body.append(ctx.lit(has_match_rel, key_terms, False))
                ctx.add_helper(c_state_name, ctx._state_cols, key_terms + [UNKNOWN, rsn_v], unk_body)

            c_state_rel = ctx.helper_or_none(c_state_name)
            if c_state_rel is not None:
                clause_states.append(c_state_rel)
                und_name = ctx.next_helper(f"c{c.index}_und")
                ctx.add_helper(
                    und_name, key_cols, key_terms,
                    domain_lits + [ctx.lit(c_state_rel, key_terms + [("var", ctx.fresh("st")), ("var", ctx.fresh("rsn"))])],
                )
                und_guard = [ctx.lit(und_name, key_terms, False)]
            else:
                und_guard = []

            inv_guard = [] if has_inv_rel is None else [ctx.lit(has_inv_rel, key_terms, False)]

            c_sat_name = ctx.next_helper(f"c{c.index}_sat")
            c_viol_name = ctx.next_helper(f"c{c.index}_viol")
            if not c.has_explicit_bound:
                assert has_match_rel is not None
                ctx.add_helper(
                    c_sat_name, key_cols, key_terms,
                    domain_lits + trig_lits + [ctx.lit(has_match_rel, key_terms)] + inv_guard,
                )
                viol_body = domain_lits + trig_lits + [ctx.lit(has_match_rel, key_terms, False)] + und_guard
                ctx.add_helper(c_viol_name, key_cols, key_terms, viol_body)
                ctx.rule(
                    viol_name,
                    key_terms + [
                        ("const", str(c.index), "integer"),
                        ("const", c.target_name, "string"),
                        ("const", c.bound_tag, "string"),
                        ("const", "0", "integer"),
                    ],
                    viol_body,
                )
                viol_rules_emitted += 1
            else:
                sat_cmp = {"at_least": "ge", "at_most": "le", "exactly": "eq"}[c.bound_op]
                viol_cmp = {"at_least": "lt", "at_most": "gt", "exactly": "ne"}[c.bound_op]
                wild_rows = [("wild",)] * len(c.row_terms)
                bound_const = ("const", str(c.bound_count), "integer")
                obs_sat = ctx.fresh("obs")
                ctx.add_helper(
                    c_sat_name, key_cols, key_terms,
                    domain_lits + trig_lits + und_guard + [
                        ("agg", obs_sat, "count", None, (match_rel, key_terms + wild_rows, line)),
                        ("cmp", sat_cmp, ("var", obs_sat), bound_const),
                    ],
                )
                obs_viol = ctx.fresh("obs")
                ctx.add_helper(
                    c_viol_name, key_cols, key_terms,
                    domain_lits + trig_lits + und_guard + [
                        ("agg", obs_viol, "count", None, (match_rel, key_terms + wild_rows, line)),
                        ("cmp", viol_cmp, ("var", obs_viol), bound_const),
                    ],
                )
                obs_rule = ctx.fresh("obs")
                ctx.rule(
                    viol_name,
                    key_terms + [
                        ("const", str(c.index), "integer"),
                        ("const", c.target_name, "string"),
                        ("const", c.bound_tag, "string"),
                        ("var", obs_rule),
                    ],
                    domain_lits + trig_lits + und_guard + [
                        ("agg", obs_rule, "count", None, (match_rel, key_terms + wild_rows, line)),
                        ("cmp", viol_cmp, ("var", obs_rule), bound_const),
                    ],
                )
                viol_rules_emitted += 1

            sat_rels.append(c_sat_name)
            viol_rels.append(c_viol_name)

        # Combine clause outcomes for `<name>`:
        # 1. All clauses known true -> known true.
        if len(sat_rels) == len(clauses):
            ctx.rule(
                name, key_terms + [("const", "true", "boolean")],
                domain_lits + trig_lits + [ctx.lit(rel, key_terms) for rel in sat_rels],
            )
            func_rules_emitted += 1

        # 2. Any clause known false -> known false.
        any_viol_rel: str | None = None
        if viol_rels:
            any_viol_name = ctx.next_helper("any_viol")
            for vrel in viol_rels:
                ctx.add_helper(any_viol_name, key_cols, key_terms, domain_lits + [ctx.lit(vrel, key_terms)])
            any_viol_rel = ctx.helper_or_none(any_viol_name)
            if any_viol_rel is not None:
                ctx.rule(
                    name, key_terms + [("const", "false", "boolean")],
                    domain_lits + [ctx.lit(any_viol_rel, key_terms)],
                )
                func_rules_emitted += 1
    else:
        any_viol_rel = None

    # 3. Remaining non-known states (trigger unknown/invalid, or clause unknown/invalid when no clause is false).
    state_sources: list[str | None] = [trig_st_rel]
    if any_viol_rel is not None:
        viol_guard = [ctx.lit(any_viol_rel, key_terms, False)]
        state_sources.extend(ctx.gate_state(cs, viol_guard) for cs in clause_states)
    else:
        state_sources.extend(clause_states)
    combined_st = ctx.combine_states(state_sources)
    if combined_st is not None:
        ctx.emit_state_rule(at, combined_st)
        func_rules_emitted += 1

    # Ensure both `<name>` and `<name>_violation` always have at least one rule in IR.
    false_cmp = ("cmp", "eq", ("const", "1", "integer"), ("const", "0", "integer"))
    if func_rules_emitted == 0:
        ctx.rule(name, key_terms + [("const", "false", "boolean")], domain_lits + [false_cmp])
    if viol_rules_emitted == 0:
        ctx.rule(
            viol_name,
            key_terms + [
                ("const", "0", "integer"),
                ("const", clauses[0].target_name, "string"),
                ("const", clauses[0].bound_tag, "string"),
                ("const", "0", "integer"),
            ],
            domain_lits + [false_cmp],
        )

    note: rezono_derived.Note | None = None
    if "means" in decl or "source" in decl:
        if "means" in decl and not isinstance(decl["means"], str):
            site.refuse(f"{at}/means", "a sentence is text", "R000")
        if "source" in decl and not isinstance(decl["source"], str):
            site.refuse(at, "a source is text", "R000")
        note_line, note_col = site.place(f"{at}/means" if "means" in decl else at)
        note = rezono_derived.Note(
            decl.get("means"), decl.get("source"), site.file, note_line, note_col, f"{at}/means",
        )
    return note, []


def lower_pack(
    root: str,
    mods: Iterable[modules.Module],
    names: modules.Names,
    pack,
    *,
    native: tuple[rules_dl.NativeSource, ...] = (),
    derivations: rezono_derived.Lowered | None = None,
) -> rezono_derived.Lowered:
    """Lower every `rezono 1` `require` declaration of the pack into `rezono.rules/2` NativeSources."""
    from .pack import CompileError

    mod_list = list(mods)
    found = [
        m for m in mod_list
        if m.form is not None
        and m.form.get("format") == REZONO_1_FORMAT
        and any(is_requirement(decl) for decl in m.form["module"]["decls"])
    ]
    if not found:
        return rezono_derived.Lowered()

    derived_sources = derivations.sources if derivations is not None else ()
    set_signatures = _derived_sets(native, derived_sources, pack, mod_list, names)
    opened = _opened_relations(pack, native, derived_sources)
    taken = set(rules_dl.base_tables(pack))
    for src in (*native, *derived_sources):
        for stmt in src.statements:
            if stmt[0] in ("decl", "functional"):
                taken.add(stmt[1])

    lowered = rezono_derived.Lowered()
    refused: list[Diagnostic] = []
    sources: list[rules_dl.NativeSource] = []
    for module in found:
        where = spans.where(module.pack, root, module.rel)
        try:
            text = module.file.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as error:
            message = f"{where}: cannot read the positions of its requirements"
            raise CompileError(message, [Diagnostic("R000", message, where)]) from error
        site = rezono_derived.Site(where, text, {place["at"]: place["start"] for place in module.form["spans"]})
        out: tuple[list, list] = ([], [])
        for idx, decl in enumerate(module.form["module"]["decls"]):
            if not is_requirement(decl):
                continue
            at = f"/decls/{idx}"
            try:
                if module.pack != root:
                    site.refuse(at, "a requirement of an imported rezono 1 pack is not lowered yet")
                note, diags = _lower_requirement(
                    site, module, names, pack, at, decl, set_signatures, opened, taken, out,
                )
                if diags:
                    refused.extend(diags)
                    continue
                if note is not None:
                    req_name = decl["require"]
                    lowered.notes[req_name] = note
                    lowered.notes[f"{req_name}_violation"] = note
            except rezono_derived.Refused as error:
                refused.append(error.diagnostic)
        if out[0]:
            sources.append(rules_dl.NativeSource(
                module.pack, module.file.stem, site.file, site.text,
                tuple(out[0]), tuple(out[1]),
            ))
    if refused:
        raise CompileError("\n".join(map(str, refused)), refused)
    lowered.sources = tuple(sources)
    return lowered
