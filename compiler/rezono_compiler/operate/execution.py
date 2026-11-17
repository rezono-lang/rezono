# --- The whole: apply in place, check, restore on error -------------------------------------------------------

from __future__ import annotations

import dataclasses
import json
import os
import stat
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from rezono_canon import canonical_json

from .. import facts, source_format, sources
from .. import plan as plans
from ..plan import Follow, Keep, Plan, evaluate, owner as plan_owner, pairs as plan_pairs
from .. import pack as packs
from ..writer import check_work_dir

from .spec import IMPACT, PARAMETERS, OperationError, load
from .model import Model, model, engine_names, states
from .text import Edits, read_text
from .rename import Rename, plan_rename, schema_edits
from .maps import Maps, engine_maps
from .records import fact_edits
from .labels import label_edits
from .datalog import rule_edits, access_kind_columns, rule_counts
from .state import embedded, id_map, migrate, bag, difference, text_of
from .migration import migration, dump
from .drop import plan_drop, drop_schema_edits, drop_fact_edits, drop_plan
from .move import plan_move, move_schema_edits, move_fact_edits, move_plan, grants, row_readers, across
from .split_by import (plan_split, split_schema_edits, split_fact_edits, split_plan, split_label_edits,
    split_migration, split_inverse)
from .combine import (plan_combine, combine_schema_edits, combine_fact_edits, combine_plan,
    combine_migration, combine_inverse)
from .checks import violations, new_violations, guarded, grown


# --- Sources through an operation (B12, seam S6) -------------------------------------------------------------

SOURCE_LOSS = "refused, the operation would leave a fact without its exact origin"


@dataclass
class Held:
    """The source companions of the main facts, read before an operation and set aside while it runs (a stale
    companion does not load against the rewritten facts). `refs`: per row of a fact file, (file, its entry, or
    None in a file without a companion, whose sources are pack lines). `companions`: fact file -> companion."""
    refs: dict[tuple[str, str], list[tuple[str, dict | None]]]
    companions: dict[str, bytes]


def companion_of(name: str) -> str:
    return name.removesuffix(".yaml") + ".sources.yaml"


def hold_sources(m: Model, originals: dict[Path, tuple[bytes | None, int]]) -> Held | None:
    """Read the sources of every row of the main facts, then remove the companions (a rollback restores them).
    None when the pack has no companion: the operation then runs as it always did."""
    found = sorted((m.dir / "facts").glob("*.sources.yaml"))
    if not found:
        return None
    refs: dict[tuple[str, str], list[tuple[str, dict | None]]] = {}
    try:
        for path in facts.files(m.dir):
            sourced = path.with_name(companion_of(path.name)).is_file()
            for e in sources.file_entries(m.pack, path):
                refs.setdefault((e["row"]["relation"], e["row"]["key"]), []).append((path.name, e if sourced else None))
    except facts.LoadError as e:
        raise OperationError(f"the source companions do not load, so no operation can carry them:\n{e}") from e
    companions = {}
    for path in found:
        path = destination(m.dir, f"facts/{path.name}")
        data = path.read_bytes()
        companions[path.name.removesuffix(".sources.yaml") + ".yaml"] = data
        originals.setdefault(path, (data, stat.S_IMODE(path.stat().st_mode)))
        path.unlink()
    return Held(refs, companions)


@dataclass(frozen=True)
class Bare:
    """The rows of `of` without their lineage."""
    of: object


class Content(plans.Run):
    """The plan's evaluator, keeping per row only the rows its content came from. A row that selects (an
    element of a semijoin, the arrow a value travels across) routes the value; it is not where the value came
    from, and an inverse operation would not give it back to the value."""

    def eval(self, q):
        if isinstance(q, Bare):
            return [(r, frozenset()) for r, _ in self.eval(q.of)]
        if isinstance(q, Keep):
            among = {plans.text(r[0]) for r, _ in self.eval(q.among)}
            return [(r, s) for r, s in self.eval(q.of) if (plans.text(r[0]) in among) != q.drop]
        if isinstance(q, Follow):
            return self.follow(dataclasses.replace(q, link=Bare(q.link)))
        return super().eval(q)


def carry_sources(held: Held, m: Model, new: Model, plan: Plan, mp: Maps, ids: dict, values: dict, x: dict,
                  name: str, originals: dict[Path, tuple[bytes | None, int]]) -> dict:
    """Write the companions again along the plan: a row after the operation takes the sources of the rows its
    content came from. A fact file has a companion after when it had one before or receives a row with an
    exact origin; then each of its rows needs exactly one origin, the same for every row it came from. A row
    that only routes others (an absorbed element, the arrow a value travelled across) keeps its origin only in
    what it routes, so that must have the same one. Otherwise (a row from a file without a companion, a row
    with no origin, rows of different origins merged, an origin only routed, a row of two files) the operation
    refuses: no undo could give those sources back. A row the operation loses (no row after came from it)
    takes its sources with it; the impact lists it. Returns the impact's `sources`."""
    arrows = {s.table for k in m.pack.kinds.values() for s in k.slots.values() if s.arrow}

    def origin(ref):
        where = held.refs.get(ref, [])
        if len({f for f, _ in where}) > 1 and any(e is not None for _, e in where):
            return "a row of two files"
        if where and where[0][1] is None:
            return "a row of a file without a companion"
        if where:
            e = where[0][1]
            return canonical_json({"sources": e["sources"], **({"reason": e["reason"]} if "reason" in e else {})})
        return None  # a row no fact file gives (a seal hash): no origin of its own

    full, content = plans.Run(x), Content(x)
    out = [(t, r, frozenset({(t, i)}), frozenset({(t, i)})) for t, rs in x.items()
           if t not in plan.gone and t not in plan.forward for i, r in enumerate(rs)]
    for t, q in plan.forward.items():
        why, what = full.eval(q), content.eval(q)
        if [r for r, _ in why] != [r for r, _ in what]:
            raise OperationError(f"{name}: the lineage of {t} differs between evaluations (a bug, please report)")
        out += [(t, r, s, c) for (r, s), (_, c) in zip(why, what)]
    carried: dict[tuple[str, str], set] = {}  # a row after -> the origins its content came from
    routes: dict[tuple[str, str], set] = {}  # a row before that only routes -> the rows after it routes
    used, through = set(), set()  # the rows before that some row after came from; its content came from
    for t, r, why, lineage in out:
        ((t2, (r2,)),) = migrate({t: [r]}, mp.tables, values, ids, arrows).items()
        after = (t2, canonical_json(r2))
        got = carried.setdefault(after, set())
        for t1, i in why:
            ref = (t1, canonical_json(x[t1][i]))
            used.add(ref)
            if (t1, i) in lineage:
                through.add(ref)
                if (o := origin(ref)) is not None:
                    got.add(o)
            else:
                routes.setdefault(ref, set()).add(after)
    real = lambda g: g.startswith("{")
    rows = {path.name: [(e["row"]["relation"], e["row"]["key"])
                        for e in sources.text_entries(new.pack, path.name, path.read_text("utf-8"))]
            for path in facts.files(new.dir)}
    files_of = Counter(ref for refs in rows.values() for ref in set(refs))
    texts, problems = {}, []
    for fname, refs in sorted(rows.items()):
        if fname not in held.companions and not any(real(g) for ref in refs for g in carried.get(ref, ())):
            continue  # pack lines only, as before
        entries = []
        for ref in sorted(set(refs)):
            got = (carried.get(ref) or {"no origin"}) | ({"a row of two files"} if files_of[ref] > 1 else set())
            if len(got) == 1 and real(next(iter(got))):
                entries.append({"row": {"relation": ref[0], "key": ref[1]}, **json.loads(next(iter(got)))})
            else:
                why = sorted(g for g in got if not real(g)) or ["rows of different origins merged into one"]
                problems.append(f"facts/{fname}: {ref[0]} {ref[1]}: {', '.join(why)}")
        if not problems:
            try:
                texts[fname] = sources.canonical_sidecar_text(new.pack, fname, (new.dir / "facts" / fname).read_text("utf-8"),
                                                              entries)
            except facts.LoadError as e:
                problems.append(f"facts/{fname}: {e}")
    for ref, afters in sorted(routes.items()):
        o = origin(ref)
        if ref not in through and o is not None and real(o) and not any(carried.get(a) == {o} for a in afters):
            where = held.refs[ref][0][0]
            problems.append(f"facts/{where}: {ref[0]} {ref[1]}: an origin only routed into rows of another origin")
    if problems:
        raise OperationError(f"{name}: {SOURCE_LOSS}:\n" + "\n".join(problems[:20])
                             + (f"\n(and {len(problems) - 20} more)" if len(problems) > 20 else ""))
    for fname, text in texts.items():
        path = m.dir / "facts" / companion_of(fname)
        if path.is_symlink() or path.parent.is_symlink():
            raise OperationError(f"{path}: refused, a symbolic link in the work dir")
        originals.setdefault(path, (None, 0o644))
        replace(path, text.encode("utf-8"), originals[path][1])
    lost = sorted(ref for ref, where in held.refs.items() if ref not in used and any(e is not None for _, e in where))
    return {"companions": [f"facts/{companion_of(f)}" for f in sorted(texts)],
            "lost": [{"relation": t, "key": k} for t, k in lost]}


def operate(pack_dir: str | Path, ops_path: str | Path, out: str | Path) -> dict:
    pack_dir = Path(pack_dir)
    check_work_dir(pack_dir)
    doc = load(ops_path)
    m = model(pack_dir)
    if doc.get("pack") != m.meta["name"]:
        raise OperationError(f"the operation set is for pack '{doc.get('pack')}', not '{m.meta['name']}'")
    if source_format.YAML_DATALOG.calc_files(pack_dir):  # no source format edits calculations yet (B13)
        raise OperationError("calc/ and sweeps.yaml do not move along yet; an operation would leave their names "
                             "behind")
    originals: dict[Path, tuple[bytes | None, int]] = {}  # None: the file was not there
    results, outputs, written = [], {}, []
    out = Path(out)
    try:
        for i, op in enumerate(doc["operations"]):
            impact, files = apply_one(m, op, i, originals)
            results.append(impact)
            outputs.update(files)
            m = model(pack_dir)
        impact = {"format": IMPACT, "pack": m.meta["name"], "operations": results}
        outputs["impact.json"] = json.dumps(impact, indent=2, ensure_ascii=False) + "\n"
        out.mkdir(parents=True, exist_ok=True)
        for name, text in sorted(outputs.items()):
            try:  # a new file, never through a link
                fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
            except FileExistsError:
                raise OperationError(f"{out / name}: exists; give an empty output directory") from None
            written.append(out / name)
            with os.fdopen(fd, "wb") as f:
                f.write(text.encode("utf-8"))
    except BaseException:
        for path, (data, mode) in originals.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                replace(path, data, mode)
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return impact


def destination(pack_dir: Path, rel: str) -> Path:
    """The file `rel` of the pack, to be rewritten: a plain file below the pack dir, reached without a
    symbolic link. check_work_dir already holds for the route from the work dir to the pack dir."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or any(x in ("", ".", "..") for x in parts):
        raise OperationError(f"{rel}: refused, not a path inside the pack")
    cur = pack_dir
    for x in parts:
        cur = cur / x
        if cur.is_symlink():
            raise OperationError(f"{cur}: refused, a symbolic link in the work dir")
    if not cur.is_file():
        raise OperationError(f"{cur}: refused, not a plain file")
    return cur


def write_all(m: Model, edits: Edits, originals: dict[Path, tuple[bytes, int]]):
    """Check every destination first, then replace each file at once (a temporary file, then os.replace)."""
    texts = {}
    for rel in sorted(edits.by_file):
        path = destination(m.dir, rel)
        texts[path] = edits.apply(rel, read_text(path))
    for path, text in texts.items():
        originals.setdefault(path, (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)))
        replace(path, text.encode("utf-8"), originals[path][1])


def replace(path: Path, data: bytes, mode: int):
    """Write `data` to `path` at once, with `mode`: also a read-only file is replaced, never opened for writing."""
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def apply_one(m: Model, op: dict, index: int, originals: dict[Path, tuple[bytes, int]]) -> tuple[dict, dict[str, str]]:
    if op["op"] == "select":
        from ..selection import SelectOp
        return SelectOp(m, op).run(index, originals)
    return {"rename": RenameOp, "drop": DropOp, "move": MoveOp, "split_by": SplitOp,
            "combine": CombineOp}[op["op"]](m, op).run(index, originals)


def reload(m: Model, name: str) -> Model:
    try:
        return model(m.dir)
    except (packs.CompileError, facts.LoadError, ValueError) as e:
        raise OperationError(f"{name}: the pack after the operation does not compile:\n{e}") from e


def row_text(r: tuple) -> dict:
    return {"id": text_of(r[0])} | ({"value": text_of(r[1])} if len(r) == 2 else {})


WORD = {"rename": "rename", "drop": "drop", "move": "move", "split_by": "split", "combine": "combine", "select": "select"}


def check_states(m: Model, new: Model, op: dict, plan: Plan, mp: Maps, ids: dict, before: list, after: list,
                 access_cols: dict | None = None, values: dict | None = None, checks: dict | None = None,
                 implied: dict | None = None) -> tuple[list, list, list]:
    """The one check path, on every fact state: M(X) as the plan gives it against the rewritten files reloaded,
    the loss, M⁻¹ against X as multisets when nothing is lost and nothing conflicts, and, but for a rename (an
    isomorphism), no new violations, no wider access and no new invariant or outcome rows. `checks` maps a check
    that moved to its new name, `implied` a new subkind to its kind (a duplicate there is the kind's own).
    Returns (problems, loss, widened access)."""
    p = m.pack
    word = WORD[op["op"]]
    values = values or {}
    arrows = {s_.table for k in p.kinds.values() for s_ in k.slots.values() if s_.arrow}
    inv_tables = {b: a for a, b in mp.tables.items()}
    inv_ids = {b: a for a, b in ids.items()}
    inv_arrows = {mp.tables[t] for t in arrows if t in mp.tables}
    inv_values = {mp.tables[t]: {b: a for a, b in vm.items()} for t, vm in values.items()}
    problems, loss, access = [], [], []
    if [s_[:3] for s_ in before] != [s_[:3] for s_ in after]:
        problems.append("the fact states before and after differ in number or name")
    for (what, sname, file_, x), (_, _, _, y) in zip(before, after):
        out, lost, conflicts = evaluate(plan.forward, plan.gone, x, plan.checks)
        problems += [f"state {sname}: conflict, {c}" for c in conflicts]
        mx = migrate(out, mp.tables, values, ids, arrows)
        if not conflicts and bag(mx) != bag(y):
            problems.append(f"state {sname}: the rewritten files do not load to M(X): missing "
                            f"{difference(mx, y)[:3]}, extra {difference(y, mx)[:3]}")
        where = {"state": what} | ({"file": file_} if file_ else {})
        for t, rs in difference(lost, {}):
            loss.append(where | {"table": t, "rows": sorted((row_text(r) for r in rs),
                                                             key=lambda r: (r["id"], r.get("value", "")))})
        if plan.backward is not None and not lost and not conflicts:
            back, _, _ = evaluate(plan.backward, plan.back_gone,
                                  migrate(y, inv_tables, inv_values, inv_ids, inv_arrows))
            if bag(back) != bag(x):
                problems.append(f"state {sname}: the round trip does not give the state back" if word == "rename"
                                else f"state {sname}: conflict, the round trip invents rows: "
                                     f"{difference(back, x)[:3]}")
        if word == "rename":
            continue
        targets = {key: (to, None if q is None else plan_pairs(q, x, swap))
                   for key, (to, q, swap, *_) in plan.carry.items()}
        image: Counter = Counter()
        for (c, k, sub, pth, r), n in violations(p, x).items():  # a check of a moved slot goes with its values
            if (k, sub) in targets:
                to, tg = targets[(k, sub)]
                lands = (plan.carry[(k, sub)][3:] or (sub,))[0]  # a check may land under another subject
                for ty in ([r[0]] if tg is None else tg.get(text_of(r[0]), [])):
                    image[(c, to, lands, pth, (ty,) + r[1:])] += n
            else:
                image[(c, k, sub, pth, r)] += n
        now = violations(new.pack, y)
        for key_ in [k_ for k_ in now if k_[0] == "identification" and k_[1] in (implied or {})]:
            if ("identification", implied[key_[1]]) + key_[2:] in now:  # the same duplicate in the kind itself
                del now[key_]
        fresh = new_violations(p, image, now, mp, ids, checks)
        if fresh:
            problems.append(f"state {sname}: new violations after the {word}, for example {fresh[:3]}")
        wider, broken = grown(guarded(p, x), guarded(new.pack, y), mp, access_cols)
        if wider and word == "drop":
            problems.append(f"state {sname}: the drop widens access (a rule reads what goes through negation or "
                            f"another relation), for example {wider[:3]}; change the rules first")
        elif wider:  # the rules grant more (negation over values left behind); accept_access covers moved values only
            problems.append(f"state {sname}: the rules grant more access after the {word}, for example "
                            f"{wider[:3]}; change the rules first")
        if broken:
            problems.append(f"state {sname}: new invariant or outcome violations after the {word}, for example "
                            f"{broken[:3]}")
        for a in plan.access:
            access += widened(m, new, a, mp, x, y, where, targets, conflicts)
    if access and op.get("accept_access") is not True:
        problems.append("access widens (a conflict unless accept_access: true): " + "; ".join(
            f"{a['role']} reads {len(a['rows'])} more rows of {a['table']} in {a['state']} {a.get('file', '')}".strip()
            for a in access))
    return problems, loss, access


def widened(m: Model, new: Model, a: dict, mp: Maps, x: dict, y: dict, where: dict, targets: dict,
            conflicts: list) -> list:
    """Per role, the rows of a moved table it may read after but could not read from any source row before
    (O7, typed: a right on a kind holds for its subkinds, never the reverse). `a`: the moved table, the kind and
    slot it was on, the kind it lands on, its range when the values are elements, and `new`, the table after
    when it is not the moved table renamed (a combine's key, whose rows come from the absorbed kind's)."""
    was, now = grants(m, x), grants(new, y)
    if was is None or now is None or conflicts:
        return []
    _, tg = targets[(a["kind"], a["slot"])]
    src: dict = {}
    for tx in sorted({text_of(r[0]) for r in x.get(a["table"], [])}):
        for ty in ([tx] if tg is None else tg.get(tx, [])):
            src.setdefault(ty, []).append(tx)
    rng = a["range"]
    rng_new = mp.tables.get(rng, rng) if rng else None
    table = a.get("new") or mp.tables[a["table"]]
    out: dict = {}
    for row in y.get(table, []):
        ty = text_of(row[0])
        before_roles = set().union(*(row_readers(m.pack, was, a["kind"], tx, rng, row[1]) for tx in src.get(ty, [])))
        for role in sorted(row_readers(new.pack, now, mp.tables[a["to"]], ty, rng_new, row[1]) - before_roles):
            out.setdefault(role, []).append(row_text(row))
    return [{"role": role} | where | {"table": table, "rows": sorted(rs, key=lambda r: (r["id"], r.get("value", "")))}
            for role, rs in sorted(out.items())]


# --- The steps every operation takes ------------------------------------------------------------------------

class Operation:
    """One operation, in the same steps for each (run): rewrite the schema; derive the name maps and the plan;
    rewrite the facts, labels and rules; reload; check every state (check_states); report the impact and write
    the migrations. A subclass gives what differs."""
    header = "conflict"  # the error when a state does not hold
    loss_text: str | None = None  # the error when values go without accept_loss (None: load already asks)
    gone_tables: set = frozenset()  # engine kinds and tables that go
    gone_elements: set = frozenset()  # element ids whose labels and channel rows go
    rule_gone: set = frozenset()  # tables and kinds the rules may no longer read or name
    rule_keep: set = frozenset()  # parameter predicates of tables in rule_gone that stay, renamed
    new_kinds: set = frozenset()

    def __init__(self, m: Model, op: dict):
        self.m, self.op = m, op

    def schema(self, edits: Edits): raise NotImplementedError

    def maps(self, new_classes: dict, new_enums: dict) -> Maps:
        return engine_maps(self.m, Rename(), new_classes, new_enums, self.gone_tables)

    def plan(self, mp: Maps) -> Plan: raise NotImplementedError

    def facts(self, mp: Maps, edits: Edits): pass
    def labels(self, edits: Edits): pass

    def check_args(self, mp: Maps) -> dict: return {}

    def ids(self, emb: set, mp: Maps) -> tuple[dict, dict]:
        """(the id map, the ids that change for the rules): derived ids follow the element names."""
        ids = id_map(emb, mp.elements)
        return ids, ids

    def back(self, plan: Plan) -> dict | None:
        """The backward queries the rules read as definitions."""
        return plan.backward

    def lossless(self, loss: list) -> bool: return not loss

    def tables(self, mp: Maps, main: dict) -> list:
        return [{"before": a, "after": b, "rows": len(main.get(b, []))} for a, b in sorted(mp.tables.items()) if a != b]

    def files(self, new: Model, mp: Maps, name: str, lossless: bool) -> dict:
        out = {f"{name}.yaml": dump(migration(self.m, new, Rename(), name, False))}
        if lossless:
            out[f"{name}.inverse.yaml"] = dump(migration(self.m, new, Rename(), f"{name}.inverse", True))
        return out

    def run(self, index: int, originals: dict[Path, tuple[bytes, int]]) -> tuple[dict, dict[str, str]]:
        m, op = self.m, self.op
        name = f"{index}-{op['op']}"
        held = hold_sources(m, originals)
        before = states(m)
        ids_before = rule_counts(m)
        edits = Edits()
        self.schema(edits)
        write_all(m, edits, originals)
        mp = self.maps(*engine_names(m.dir))
        ids, changed = self.ids(embedded(m, before), mp)  # a class no longer ambiguous loses its prefix
        plan = self.plan(mp)
        edits = Edits()
        fact_edits(m, mp, {text_of(a): text_of(b) for a, b in ids.items()}, edits)
        self.facts(mp, edits)
        label_edits(m, mp, edits, self.gone_elements)
        self.labels(edits)
        rules = rule_edits(m, mp, ids_before, changed, edits, self.rule_gone, self.new_kinds, self.back(plan),
                           keep=self.rule_keep)
        access_cols = access_kind_columns(m)
        write_all(m, edits, originals)
        new = reload(m, name)
        after = states(new)
        problems, loss, access = check_states(m, new, op, plan, mp, ids, before, after, access_cols,
                                              **self.check_args(mp))
        if problems:
            raise OperationError(f"{name}: {self.header}:\n" + "\n".join(problems))
        if loss and self.loss_text and op.get("accept_loss") is not True:
            raise OperationError(f"{name}: {self.loss_text}; accept it with accept_loss: true:\n" + "\n".join(
                f"{x['state']} {x.get('file', '')} {x['table']}: {len(x['rows'])} rows" for x in loss))
        main = after[0][3] if after and after[0][0] == "facts" else {}
        carried = None
        if held is not None:
            x = before[0][3] if before and before[0][0] == "facts" else {}
            carried = carry_sources(held, m, new, plan, mp, ids, self.check_args(mp).get("values") or {}, x, name,
                                    originals)
        lossless = self.lossless(loss)
        impact = {"index": index, "op": op["op"], "lossless": lossless, "migration": f"{name}.yaml"}
        impact |= {"inverse": f"{name}.inverse.yaml"} if lossless else {}
        elements = [{"before": e} for e in sorted(self.gone_elements)]
        elements += [{"before": a, "after": b} for a, b in sorted(mp.elements.items())]
        impact |= {"tables": self.tables(mp, main), "loss": loss, "rules": rules, "access": access,
                   "elements": sorted(elements, key=lambda e: e["before"])}
        impact |= {"sources": carried} if carried is not None else {}
        return impact, self.files(new, mp, name, lossless)


class RenameOp(Operation):
    """rename: an isomorphism; any difference on a state is a bug and blocks."""
    header = "conflict (a bug in the operation, please report)"

    def __init__(self, m: Model, op: dict):
        super().__init__(m, op)
        self.r = plan_rename(m, op)

    def schema(self, edits: Edits): schema_edits(self.m, self.r, edits)

    def maps(self, new_classes: dict, new_enums: dict) -> Maps:
        return engine_maps(self.m, self.r, new_classes, new_enums)

    def plan(self, mp: Maps) -> Plan: return Plan(backward={})

    def check_args(self, mp: Maps) -> dict:
        return {"values": {s.table: mp.values[s.enum] for k in self.m.pack.kinds.values() for s in k.slots.values()
                           if s.enum in mp.values}}

    def files(self, new: Model, mp: Maps, name: str, lossless: bool) -> dict:
        return {f"{name}.yaml": dump(migration(self.m, new, self.r, name, False)),
                f"{name}.inverse.yaml": dump(migration(self.m, new, self.r, f"{name}.inverse", True))}


class DropOp(Operation):
    """drop (docs/compiler.md#what-an-operation-means): Δ along an inclusion, with the rows of the elements that
    go. Never lossless; the impact lists every lost row. A violation after that is not the image of one before
    (a reference to an element that went) blocks."""

    def __init__(self, m: Model, op: dict):
        super().__init__(m, op)
        self.d = plan_drop(m, op)
        self.gone_tables = self.rule_gone = self.d.tables
        self.gone_elements = self.d.elements

    def schema(self, edits: Edits): drop_schema_edits(self.m, self.d, edits)

    def plan(self, mp: Maps) -> Plan: return drop_plan(self.m.pack, self.d)

    def facts(self, mp: Maps, edits: Edits): drop_fact_edits(self.m, self.d, edits)

    def lossless(self, loss: list) -> bool: return False

    def tables(self, mp: Maps, main: dict) -> list:
        gone = [{"before": t, "rows": 0} for t in sorted(self.d.tables)]
        return sorted(gone + super().tables(mp, main), key=lambda t: t["before"])


class MoveOp(Operation):
    """move (docs/compiler.md#what-an-operation-means): up and down along is_a, or across a single-valued arrow.
    Lossless when no value is left behind; a loss needs accept_loss, widened access accept_access, and a
    conflict (two values of the arrow, sources that differ, invented rows, new violations) always blocks."""
    loss_text = "the move loses values"

    def __init__(self, m: Model, op: dict):
        super().__init__(m, op)
        self.mv = plan_move(m, op)
        self.gone_tables = {self.mv.table}

    def schema(self, edits: Edits): move_schema_edits(self.m, self.mv, edits)

    def maps(self, new_classes: dict, new_enums: dict) -> Maps:
        mv, mp = self.mv, super().maps(new_classes, new_enums)
        new_table = f"{mp.tables[mv.to]}__{mv.slot.name}"
        mp.tables[mv.table] = mp.predicates[mv.table] = new_table
        mp.elements[mv.slot.element] = f"{mp.tables[mv.to]}.{mv.slot.name}"
        for b in PARAMETERS:
            mp.predicates[f"{mv.table}__{b}"] = f"{new_table}__{b}"
        return mp

    def plan(self, mp: Maps) -> Plan:
        mv = self.mv
        plan = move_plan(mv)
        plan.access = [{"table": mv.table, "kind": mv.kind, "slot": mv.slot.name, "to": mv.to,
                        "range": mv.slot.range if mv.slot.arrow else None}]
        return plan

    def facts(self, mp: Maps, edits: Edits): move_fact_edits(self.m, self.mv, edits)

    def files(self, new: Model, mp: Maps, name: str, lossless: bool) -> dict:
        m, mv = self.m, self.mv
        out = super().files(new, mp, name, lossless)
        if mv.mode not in ("source", "target"):
            return out
        ident = lambda model, k: model.pack.kinds[model.pack.root(k)].identifier
        a = mv.slot.name
        forward = migration(m, new, Rename(), name, False)
        if mv.mode == "source":  # to.f -> kind
            across(forward, new, mp.tables[mv.to], mp.tables[mv.kind], a, mv.via.name, ident(m, mv.kind))
        else:  # kind.f -> to
            across(forward, new, mp.tables[mv.to], mp.tables[mv.kind], a, ident(m, mv.to), mv.via.name)
        out[f"{name}.yaml"] = dump(forward)
        if lossless:
            inverse = migration(m, new, Rename(), f"{name}.inverse", True)
            if mv.mode == "source":
                across(inverse, m, mv.kind, mv.to, a, ident(m, mv.kind), mv.via.name)
            else:
                across(inverse, m, mv.kind, mv.to, a, mv.via.name, ident(m, mv.to))
            out[f"{name}.inverse.yaml"] = dump(inverse)
        return out


class SplitOp(Operation):
    """split_by (docs/compiler.md#what-an-operation-means): one subkind per case, the attribute goes. Lossless
    when every value has a case; a value without one is a loss (not abstract) or a conflict (abstract), as is an
    element with two values."""
    loss_text = "values without a case go"

    def __init__(self, m: Model, op: dict):
        super().__init__(m, op)
        self.sp = plan_split(m, op)
        self.gone_tables = {self.sp.slot.table}
        self.gone_elements = {self.sp.slot.element}
        self.rule_gone = {f"{self.sp.slot.table}__{b}" for b in PARAMETERS}

    def schema(self, edits: Edits): split_schema_edits(self.m, self.sp, edits)

    def maps(self, new_classes: dict, new_enums: dict) -> Maps:
        sp = self.sp
        self.names = {c: new_classes[(self.m.pack.kinds[sp.kind].module, c)] for c in sp.cases.values()}
        self.new_kinds = set(self.names.values())
        return super().maps(new_classes, new_enums)

    def plan(self, mp: Maps) -> Plan: return split_plan(self.sp, self.names)

    def facts(self, mp: Maps, edits: Edits):
        split_fact_edits(self.m, self.sp, {c: mp.tables.get(n, n) for c, n in self.names.items()}, edits)

    def labels(self, edits: Edits): split_label_edits(self.m, self.sp, self.names, edits)

    def check_args(self, mp: Maps) -> dict:
        sp, rules = self.sp, self.m.pack.kinds[self.sp.kind].rules
        k_new = mp.tables[sp.kind]
        kept = [i for i in range(len(rules)) if i not in sp.rules]
        checks = {(sp.kind, rules[i].name): (k_new, f"rule_{n}") for n, i in enumerate(kept, 1)}
        for c, n_ in self.names.items():
            mine = [i for i in sorted(sp.rules) if sp.rules[i] == c]
            checks |= {(sp.kind, rules[i].name): (n_, f"rule_{n}") for n, i in enumerate(mine, 1)}
        return {"checks": checks, "implied": {n_: k_new for n_ in self.names.values()}}

    def tables(self, mp: Maps, main: dict) -> list:
        return ([{"before": self.sp.slot.table, "rows": 0}]
                + [{"after": n, "rows": len(main.get(n, []))} for n in sorted(self.names.values())]
                + super().tables(mp, main))

    def files(self, new: Model, mp: Maps, name: str, lossless: bool) -> dict:
        out = {f"{name}.yaml": dump(split_migration(self.m, new, self.sp, self.names, name))}
        if lossless:
            out[f"{name}.inverse.yaml"] = dump(split_inverse(self.m, new, self.sp, self.names, f"{name}.inverse"))
        return out


class CombineOp(Operation):
    """combine (docs/compiler.md#what-an-operation-means): Δ along the path k.f -> a, or across a.f -> k.
    Lossless when every absorbed element is reached, has a value and keeps (key) or derives its identifier. A
    loss needs accept_loss, widened access accept_access; an element reached twice, invented rows, new
    violations and rules that grant more always block."""
    loss_text = "the combine loses rows"

    def __init__(self, m: Model, op: dict):
        super().__init__(m, op)
        cb = self.cb = plan_combine(m, op)
        self.gone_tables = cb.tables
        self.gone_elements = {cb.absorb, cb.via.element}
        self.rule_gone = {cb.absorb, cb.via.table} | (set() if cb.key else {s.table for s in cb.slots})
        self.rule_keep = {f"{s.table}__{b}" for s in cb.slots for b in PARAMETERS}

    def schema(self, edits: Edits): combine_schema_edits(self.m, self.cb, edits)

    def maps(self, new_classes: dict, new_enums: dict) -> Maps:
        cb, mp = self.cb, super().maps(new_classes, new_enums)
        k_new = mp.tables[cb.kind]
        self.key_table = f"{k_new}__{cb.key}" if cb.key else None
        for s in cb.slots:
            mp.tables[s.table] = mp.predicates[s.table] = f"{k_new}__{s.name}"
            mp.elements[s.element] = f"{k_new}.{s.name}"
            for b in PARAMETERS:
                mp.predicates[f"{s.table}__{b}"] = f"{k_new}__{s.name}__{b}"
        for n, _ in cb.unique_keys:
            mp.elements[f"{cb.absorb}.{n}"] = f"{k_new}.{n}"
        return mp

    def ids(self, emb: set, mp: Maps) -> tuple[dict, dict]:
        """An absorbed derived id goes into its owner, and what it held hangs on the owner; a constant equal to
        an absorbed id blocks in the rules, as one equal to any id that changes."""
        cb = self.cb
        ids = id_map(emb, mp.elements, cb.via.element if cb.derived else None)
        absorbed = {x: x for x in emb if cb.derived and plan_owner(x, cb.via.element) is not None}
        return ids, ids | absorbed

    def plan(self, mp: Maps) -> Plan: return combine_plan(self.m.pack, self.cb, self.key_table)

    def back(self, plan: Plan) -> dict | None:
        return plan.backward if self.cb.key else None  # derived ids have no definition: no function symbols

    def facts(self, mp: Maps, edits: Edits): combine_fact_edits(self.m, self.cb, edits)

    def lossless(self, loss: list) -> bool: return not loss and (self.cb.key is not None or self.cb.derived)

    def tables(self, mp: Maps, main: dict) -> list:
        cb = self.cb
        out = [{"before": t, "rows": 0} for t in sorted({cb.absorb, cb.via.table})]
        out += [{"after": self.key_table, "rows": len(main.get(self.key_table, []))}] if cb.key else []
        return sorted(out + super().tables(mp, main), key=lambda t: (t.get("before", ""), t.get("after", "")))

    def files(self, new: Model, mp: Maps, name: str, lossless: bool) -> dict:
        out = {f"{name}.yaml": dump(combine_migration(self.m, new, self.cb, name))}
        if lossless:
            out[f"{name}.inverse.yaml"] = dump(combine_inverse(self.m, new, self.cb, f"{name}.inverse"))
        return out
