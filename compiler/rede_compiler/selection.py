"""Select an explicit submodel in one migration, accounting for every omitted kind and slot (S31)."""

from __future__ import annotations

from . import operate as o
from .pack import Pack, Slot
from .plan import Keep, Owned, Plan, Scan


def validate(op: dict, where: str) -> list[str]:
    """Validate the operation's exact shape without loading or changing a pack."""
    errors = []
    for field in sorted(set(op) - {"op", "keep", "omit", "accept_loss"}, key=str):
        errors.append(f"{where}: select takes no '{field}'")
    if op.get("accept_loss") is not True:
        errors.append(f"{where}: select needs accept_loss: true and a reason for every omission")
    for name, allowed, required in (("keep", {"kind", "slots"}, {"kind"}),
                                    ("omit", {"kind", "slot", "reason"}, {"kind", "reason"})):
        entries = op.get(name, []) if name == "omit" else op.get(name)
        if not isinstance(entries, list) or (name == "keep" and not entries):
            errors.append(f"{where}: select {name} is a list")
            continue
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - allowed or required - set(entry):
                errors.append(f"{where}: select {name} entries have {sorted(required)}, optionally {sorted(allowed - required)}")
                continue
            for field in sorted(set(entry) - {"slots"}):
                if not isinstance(entry[field], str) or not entry[field].strip():
                    errors.append(f"{where}: select {name}.{field} is nonempty text")
            if "slots" in entry:
                slots = entry["slots"]
                if not isinstance(slots, list) or any(not isinstance(s, str) or not s for s in slots):
                    errors.append(f"{where}: select keep.slots is a list of slot names")
                elif len(set(slots)) != len(slots):
                    errors.append(f"{where}: select repeats a slot")
    return errors


def omissions(m: o.Model, op: dict) -> tuple[o.Drop, list[Slot]]:
    """Resolve a complete inventory. Imported definitions stay with their owner and cannot be selected away."""
    p = m.pack
    local = {k for k, kind in p.kinds.items() if kind.module in m.local}
    if not local:
        raise o.OperationError("select needs a local kind inventory")

    def kind(ref):
        return o.resolve(m, ref, m.classes, "class")[2]

    kept, gone, slots, accounted = {}, set(), {}, set()
    for entry in op["keep"]:
        k = kind(entry["kind"])
        if k in kept:
            raise o.OperationError(f"select repeats kind {entry['kind']}")
        kept[k] = set(entry["slots"]) if "slots" in entry else None
    for entry in op.get("omit", []):
        k, name = kind(entry["kind"]), entry.get("slot")
        if (k, name) in accounted:
            raise o.OperationError(f"select repeats an omission of {entry['kind']} {name or ''}")
        accounted.add((k, name))
        if name is None:
            gone.add(k)
        else:
            if name == p.kinds[p.root(k)].identifier:
                raise o.OperationError("select cannot omit an identifier")
            if name not in p.kinds[k].slots:
                raise o.OperationError(f"select: {entry['kind']} declares no slot {name}")
            slots.setdefault(k, set()).add(name)
    if set(kept) & gone:
        raise o.OperationError("select cannot both keep and omit a kind")
    if local - set(kept) - gone:
        raise o.OperationError(f"select needs an omission reason for kinds {sorted(local - set(kept) - gone)}")
    if set(slots) - set(kept):
        raise o.OperationError("select slot omissions belong to a kept kind; a kind omission covers all its slots")
    for k, names in kept.items():
        own, excluded = set(p.kinds[k].slots), slots.get(k, set())
        names = own - excluded if names is None else names
        if names - own:
            raise o.OperationError(f"select: unknown or inherited slots on {k}: {sorted(names - own)}; identifiers stay automatically")
        if names & excluded:
            raise o.OperationError(f"select cannot both keep and omit slots of {k}")
        if own - names - excluded:
            raise o.OperationError(f"select needs an omission reason for slots of {k}: {sorted(own - names - excluded)}")
    removed = [s for k in sorted(local) for s in p.kinds[k].slots.values()
               if k in gone or s.name in slots.get(k, ())]
    d = o.Drop(sorted(local)[0], None, removed, gone)
    for k in sorted(kept):
        if p.kinds[p.root(k)].identifier is None and not any(
                o.owned(p, s) and s.table not in d.tables and s.range in p.ancestors(k)
                for kind in p.kinds.values() for s in kind.slots.values()):
            raise o.OperationError(f"select keeps {k} without a surviving owning slot; omit the kind with a reason")
    return o.validate_drop(m, d, "select"), [s for s in removed if s.kind not in gone]


def plan(p: Pack, d: o.Drop, slot_drops: list[Slot]) -> Plan:
    """One Delta along the inclusion, retaining each surviving row once and reporting every lost origin."""
    owning = tuple((s.table, p.root(s.kind), p.root(s.range), s.element)
                   for kind in p.kinds.values() for s in kind.slots.values() if o.owned(p, s))
    holders = tuple(s.table for s in slot_drops if o.owned(p, s))

    def keep(table, root):
        query = Scan(table)
        for seed in sorted(d.kinds):
            query = Keep(query, Owned(root, seed, p.root(seed), (), owning), drop=True)
        if holders:
            query = Keep(query, Owned(root, None, None, holders, owning), drop=True)
        return query

    forward = {k: keep(k, p.root(k)) for k in p.kinds if k not in d.tables}
    forward.update({s.table: keep(s.table, p.root(s.kind)) for kind in p.kinds.values()
                    for s in kind.slots.values() if s.table not in d.tables})
    return Plan(forward=forward, gone=d.tables)


class SelectOp(o.DropOp):
    """A simultaneous, deliberately lossy selection; the ordinary migration, checks and rollback still apply."""

    def __init__(self, m: o.Model, op: dict):
        o.Operation.__init__(self, m, op)
        self.d, self.slot_drops = omissions(m, op)
        self.gone_tables = self.rule_gone = self.d.tables
        self.gone_elements = self.d.elements

    def schema(self, edits):
        o.drop_schema_edits(self.m, self.d, edits)
        for s in self.slot_drops:
            o.drop_schema_edits(self.m, o.Drop(s.kind, s, [s], self.d.kinds), edits)

    def facts(self, mp, edits):
        o.drop_fact_edits(self.m, self.d, edits)
        for s in self.slot_drops:
            o.drop_fact_edits(self.m, o.Drop(s.kind, s, [s], self.d.kinds), edits)

    def plan(self, mp):
        return plan(self.m.pack, self.d, self.slot_drops)

    def run(self, index, originals):
        impact, files = super().run(index, originals)
        impact["omissions"] = [{"kind": e["kind"], **({"slot": e["slot"]} if "slot" in e else {}), "reason": e["reason"]}
                               for e in sorted(self.op.get("omit", []), key=lambda e: (e["kind"], e.get("slot", "")))]
        return impact, files
