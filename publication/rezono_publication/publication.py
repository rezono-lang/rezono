"""A role's form of a published Rezono epoch as a publication (docs/publication/l0.md): schema, rows and hashes.

The publisher writes one form per role beside the role's own files (rezono_publisher.forms); the RD probes
read it (probes/publication-thin). Input is what one role's part of a publication holds, never more:

- the role-neutral definition (the epoch's archived schema bundle);
- the role's rows per Rezono relation (its snapshots), and the relations it reads in full (`full`; None for the
  complete role, whose every relation is complete);
- the role's witnesses and fact sources.

Out come a schema document (§2), the rows in row JSON (§3) with every absent value as its state (§3.3), `$why`
per derived row and `$src` per base row, and every hash of §6.2. Rows are never filtered here: what a role may
read is the publisher's decision, made once. Where the role does not read a relation in full, an absence in
its files proves nothing, so the form does not close the world over it: the kind or the many-valued slot is
`world: open`, and a single-valued slot also takes `unknown`, written `{"$unknown": "not_read_in_full"}` for every
element without a readable value, withheld or none (its files cannot tell the two apart). `full` follows from the
shape of the role's read rules, never from the data, so the schema of a role's form depends on no hidden row.

A derived relation is a kind of its own: its element id is Rezono's canonical row key `CJ([parts])`, so the id is
the row, and `tuple_key` keeps the column order that key follows. Each column is a known slot marked `derived`, of
the type the bundle checked for it: its semantic type where the bundle gives one (a reference to a kind), else its
physical rule type (`string` is `Text`, `integer` is `Integer`). A column of any other type is no publication.
An enum relation is schema (`enums`), not data.
Exact values only: an integer is `Integer` with Rezono's BIGINT bounds; nothing is ever a float.

A subkind (`is_a`) is a kind with a `parent` that restates its parent's slots (§2.1). In Rezono an element of a
subkind is also a row of every kind above it; the form writes it once, at its most specific kind
(§3.1), with every slot. A role that reads an element as the subkind only gets the slots of the kinds above as
any slot it does not read in full.

`relations` maps a form back onto Rezono relations, so a reader can check that a form says exactly what the
role's files say: no element and no value more or less. That an element of a subkind is an element of the kinds
above is what the definition says, so both sides of that check are closed under it.
"""

from __future__ import annotations

import json

from rezono_canon import canonical_json, canonical_sha256

from . import l0
from .hash import hashes
from .l0 import _number_spelling

COMPLETE = "checker"  # the role whose snapshots are complete (contracts/manifest.yaml, Snapshot.complete)
NOT_READ_IN_FULL = "not_read_in_full"  # the reason of an absence in a relation the role does not read in full
BIGINT = ("-9223372036854775808", "9223372036854775807")  # Rezono's integer storage (docs/compiler.md, Tables)
RULE_COLUMN_TYPES = {"string": "Text", "integer": "Integer", "boolean": "Bool"}  # contracts/bundle.yaml RuleColumnType
ID_STORAGE = {"text": "string", "integer": "integer"}  # a kind's `id_type` as the rule column that names it
BASE = "https://rezono.example/{pack}/"  # §2.1 `base` of a pack whose pack.yaml declares no `iri:`
MANIFEST_KEYS = ("id", "epoch", "knowledge_time", "definition_sha256", "compiled")
SWEEPS_FILE = "ir/sweeps.json"  # the compiled sweep grid: per role at the gate, never in a role's form


class FormError(ValueError):
    """An epoch that cannot be written as a publication, or a form that does not say what the role's files say."""


def role_manifest(m: dict, role: str) -> dict:
    """What of a manifest the role's form carries: the epoch's names and its definition, never another role's
    entries and never what is for the server side only (`pack_sha256`, `counts`, `sources`). The compiled sweep
    grid is left out too: a role that cannot read the swept cell learns no sweep exists (the gate scopes it so)."""
    out = {k: m[k] for k in MANIFEST_KEYS if k in m}
    if "compiled" in out:
        out["compiled"] = [c for c in out["compiled"] if c.get("file") != SWEEPS_FILE]
    return {**out, "role": role}


# --- the schema document ---------------------------------------------------------------------------------------

def pascal(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in name.split("_") if p)


def schema_document(bundle: dict, full=None) -> tuple[dict, dict]:
    """The publication schema document (§2) of a bundle, and the plan of how each Rezono table maps onto it.

    `full` is the set of Rezono tables the role reads in full (None: all, the complete role). A kind, slot or derived
    relation over any other table is open, and a single-valued slot over one also takes `unknown`."""
    def partial(table: str) -> bool:
        return full is not None and table not in full

    def define(name: str, typ: dict, a: dict):
        # A type is named after the schema type of its slot. Two slots with another pattern each on one schema
        # type (an inline pattern on a plain string) would share one type: no form, never a form that holds
        # one slot to the other's pattern (l0.md Q22; the bounds of an integer type are still the last slot's).
        if types.setdefault(name, typ) != typ:
            raise FormError(f"{a['id']}: a second type named {name} is not written as a publication yet")

    pack = bundle["pack"]["id"]
    kinds, types, plan = {}, {}, {"kinds": {}, "slots": {}, "derived": {}, "partial": set(), "family": {}}
    enums = {e["id"]: [v.split(".", 1)[1] for v in e["values"]] for e in bundle.get("enums", [])}
    base = bundle["pack"].get("base") or BASE.format(pack=pack)
    by_id = {k["id"]: k for k in bundle["kinds"]}
    cls = {k["id"]: k["class"] for k in bundle["kinds"]}
    chains = {i: _chain(by_id, i) for i in by_id}
    for k in bundle["kinds"]:
        # The world sits on the root kind: a subkind shares its parent's tables (docs/compiler.md, W6).
        world = next((by_id[c]["world"] for c in chains[k["id"]] if "world" in by_id[c]), None) or k["world"]
        kinds[k["class"]] = {"world": "open" if partial(k["id"]) else world, "id": {"type": "Text"}, "slots": {}}
        if k.get("iri", f"{base}{k['class']}") != f"{base}{k['class']}":  # the default is never written (§2.1)
            kinds[k["class"]]["iri"] = k["iri"]
        if k.get("parent"):
            kinds[k["class"]]["parent"] = cls[k["parent"]]
        plan["kinds"][k["id"]] = k["class"]
        # The kind and every kind below it, by class name: the kinds whose rows carry a slot of this kind.
        plan["family"][k["class"]] = [cls[i] for i in by_id if k["id"] in chains[i]]
    control = {k["id"]: k for k in bundle["kinds"] if k.get("plane") == "control"}
    for a in sorted(bundle.get("attributes", []) + bundle.get("arrows", []), key=lambda a: a["id"]):
        slot = {"card": ("+" if a["required"] else "*") if a["multivalued"] else ("1" if a["required"] else "?")}
        if "target" in a:
            slot["ref"] = cls[a["target"]]
        elif a["type"] == "enum":
            name = pascal(a["enum"])
            types[name] = {"of": "Enum", "enum": a["enum"]}
            slot["type"] = name
        elif a["type"] == "integer":
            name = pascal(a["schema_type"]) if a["schema_type"] != "integer" else f"{cls[a['kind']]}{pascal(a['name'])}"
            types[name] = {"of": "Integer", "min": a.get("minimum") or BIGINT[0], "max": a.get("maximum") or BIGINT[1]}
            slot["type"] = name
        elif a["type"] == "date":
            slot["type"] = "Date"
        elif a["type"] == "boolean":
            slot["type"] = "Bool"
        elif a["type"] == "text":
            if a.get("patterns"):
                if len(a["patterns"]) != 1:
                    raise FormError(f"{a['id']}: more than one pattern")
                name = pascal(a["schema_type"])
                define(name, {"of": "Text", "pattern": a["patterns"][0]}, a)
                slot["type"] = name
            else:
                slot["type"] = "Text"
        else:
            raise FormError(f"{a['id']}: type {a['type']} is not written as a publication yet")
        world = a["world"]
        if partial(a["table"]):  # what the role cannot read in full is never closed over
            plan["partial"].add(a["table"])
            world = "open"
        slot["states"] = ["known"]
        if not a["multivalued"]:
            if not a["required"]:
                slot["states"].append("not_applicable")
            # Only a closed, optional slot read in full can establish absence from a missing row (§3.3).
            if a["required"] or world == "open":
                slot["states"].append("unknown")
        for name in plan["family"][cls[a["kind"]]]:  # the kind that declares it, and each kind below restates it
            if a["name"] in kinds[name]["slots"]:
                raise FormError(f"{a['id']}: {name} has two slots `{a['name']}`")
            kinds[name]["slots"][a["name"]] = slot | ({"world": world} if world != kinds[name]["world"] else {})
        plan["slots"][a["table"]] = (cls[a["kind"]], a["name"], a)
    # A kind of decided values (DV1, §3.7) carries its marker and owner; its decision is always known, because
    # admission takes no row of it without one. A role that reads the decision in part cannot be told it is
    # always there, so for that role the kind is written without the marker, as an open data-plane kind. The
    # kinds below a control kind are control kinds too (contracts/bundle.yaml), with the slot they restate.
    for k, kind in sorted(control.items()):
        decision = kinds[kind["class"]]["slots"].get("decision")
        table = next((a["table"] for a in bundle.get("attributes", []) + bundle.get("arrows", [])
                      if a["kind"] == k and a["name"] == "decision"), None)
        if decision is not None and table is not None and not partial(kind["id"]) and not partial(table):
            for name in plan["family"][kind["class"]]:
                kinds[name]["slots"]["decision"]["states"] = ["known"]
                kinds[name] |= {"plane": "control", "owner": kind["owner"]}
    for r in bundle.get("relations", []):
        name = pascal(r["id"])
        if name in kinds:
            raise FormError(f"derived relation {r['id']} collides with kind {name}")
        slots = {}
        for column in r["columns"]:
            if column["name"] in slots:
                raise FormError(f"{r['id']}: two columns `{column['name']}`")
            slots[column["name"]] = _column_slot(r["id"], column, by_id, chains) | {"card": "1", "states": ["known"],
                                                                          "derived": True}
        kinds[name] = {"world": "open" if partial(r["id"]) else r["world"], "id": {"type": "Text"},
                       "slots": slots, "tuple_key": list(slots)}
        plan["derived"][r["id"]] = (name, list(slots))
    doc = {"rezono": "1.0", "pack": pack, "base": base, "kinds": kinds}
    if types:
        doc["types"] = types
    if enums:
        doc["enums"] = enums
    return doc, plan


def _column_slot(relation: str, column: dict, by_id: dict, chains: dict) -> dict:
    """The value of a derived column's slot: its checked semantic type where the bundle gives one, else the scalar
    of its physical rule type. Its semantic type stores what its physical type stores; a reference stores the
    identifier of its target's root kind."""
    where = f"{relation}.{column['name']}"
    physical = column.get("type")
    if not isinstance(physical, str) or physical not in RULE_COLUMN_TYPES:
        raise FormError(f"{where}: unsupported rule column type {physical!r}")
    scalar = {"type": RULE_COLUMN_TYPES[physical]}
    if physical == "integer":
        scalar |= {"min": BIGINT[0], "max": BIGINT[1]}
    semantic = column.get("semantic")
    if semantic is None:
        return scalar
    if not isinstance(semantic, dict) or semantic.get("base") != physical:
        raise FormError(f"{where}: its semantic type does not store a {physical}")
    if semantic.get("case") == "scalar":
        return scalar
    if semantic.get("case") == "ref":
        target = semantic.get("target")
        if target not in by_id:
            raise FormError(f"{where}: refers to {target!r}, which is not a kind of the bundle")
        if ID_STORAGE.get(by_id[chains[target][-1]].get("id_type")) != physical:
            raise FormError(f"{where}: the identifier of {target} is not stored as a {physical}")
        return {"ref": by_id[target]["class"]}
    raise FormError(f"{where}: a {semantic.get('case')!r} column is not written as a publication yet")


# --- rows ------------------------------------------------------------------------------------------------------

def _chain(by_id: dict, kind: str) -> list[str]:
    """The kind and the kinds above it, nearest first, by the bundle's `parent`."""
    out = []
    while kind is not None:
        if kind not in by_id or kind in out:
            raise FormError(f"kind {out[0] if out else kind}: its parents do not end at a root kind")
        out.append(kind)
        kind = by_id[kind].get("parent")
    return out


def _elements(doc: dict, plan: dict, rows: dict) -> dict[tuple, str]:
    """(root kind, id) → the most specific kind the role reads the element as: in Rezono an element
    of a subkind is a row of every kind above it too, and those rows are one element. Two kinds of one tree with
    neither above the other cannot both hold it (one identity per kind tree, S1)."""
    at: dict[tuple, str] = {}
    for kind_id, name in plan["kinds"].items():
        for (i,) in rows.get(kind_id, []):
            key = (l0.root(doc, name), i)
            seen = at.setdefault(key, name)
            if seen in plan["family"][name]:
                continue  # already at this kind or at one below it
            if name not in plan["family"][seen]:
                raise FormError(f"{i} is an element of {seen} and of {name}, and neither is above the other")
            at[key] = name
    return at


def witness_uri(w: dict, schema: dict | None = None) -> str:
    if schema is not None:
        from . import rdf

        return rdf.canonical_witness_iri(schema, w)
    return "rezono:w/" + canonical_sha256(w)


def _parse_bool(where: str, v) -> bool:
    if isinstance(v, bool):
        return v
    if v == "true":
        return True
    if v == "false":
        return False
    raise FormError(f"{where}: {v!r} is not a boolean value")


def _value(doc: dict, name: str, slot: str, a: dict, v):
    """The row JSON payload of one Rezono value of a slot (§3.2)."""
    if "target" in a:
        return {"$ref": v}
    if a["type"] == "boolean":
        return _parse_bool(a["table"], v)
    t = doc.get("types", {}).get(doc["kinds"][name]["slots"][slot].get("type"), {})
    return int(v) if t and _number_spelling(t) else v  # LD2: a bounded integer is a JSON number (hash-neutral)


def row_json(doc: dict, plan: dict, epoch: dict) -> list[dict]:
    """Every element as a row (§3): every slot written, absence as its state, `$why` and `$src` attached.
    `epoch` holds the role's `rows` per relation, its `witnesses` and its fact `sources`."""
    at = _elements(doc, plan, epoch["rows"])
    elems: dict[tuple, dict] = {(name, i): {"$kind": name, "$id": i} for (_, i), name in at.items()}

    def element(name: str, i: str):
        """The row of the element `i` of kind `name`: written at `name` or at a kind below it."""
        kind = at.get((l0.root(doc, name), i))
        return elems[kind, i] if kind in plan["family"][name] else None

    for table, (name, slot, a) in plan["slots"].items():
        for i, v in epoch["rows"].get(table, []):
            row = element(name, i)
            if row is None:
                raise FormError(f"{table}: {i} is not an element of {name}")
            value = _value(doc, name, slot, a, v)
            if a["multivalued"]:
                row.setdefault(slot, []).append(value)
            elif slot in row:
                raise FormError(f"{table}: two values for {i}")
            else:
                row[slot] = value
    hidden = {(kind, slot) for table, (name, slot, _) in plan["slots"].items() if table in plan["partial"]
              for kind in plan["family"][name]}
    for name, kind in doc["kinds"].items():
        for slot_name, slot in kind["slots"].items():
            if slot.get("derived"):
                continue
            for (n, _), row in elems.items():
                if n != name or slot_name in row:
                    continue
                if slot["card"] in ("*", "+"):
                    row[slot_name] = []  # over an open relation: no member known, not "none" (§3.3)
                elif (name, slot_name) in hidden:
                    row[slot_name] = {"$unknown": NOT_READ_IN_FULL}
                else:
                    row[slot_name] = {"$" + ("unknown" if "unknown" in slot["states"] else "na"): ""}
    for rel, (name, cols) in plan["derived"].items():
        slots = doc["kinds"][name]["slots"]
        for parts in epoch["rows"].get(rel, []):
            key_parts = [("true" if v else "false") if isinstance(v, bool) else v for v in parts]
            i = canonical_json(key_parts)
            elems[name, i] = {
                "$kind": name, "$id": i,
                **{
                    c: {"$ref": v} if "ref" in slots[c]
                    else _parse_bool(f"{rel}.{c}", v) if slots[c].get("type") == "Bool"
                    else v
                    for c, v in zip(cols, parts)
                },
            }
    for w in epoch["witnesses"]:
        rel = w["conclusion"]["relation"]
        if rel in plan["derived"]:
            row = elems[plan["derived"][rel][0], w["conclusion"]["key"]]
            row.setdefault("$why", {})["$id"] = witness_uri(w, doc)
    slot_of = {t: (n, s) for t, (n, s, _) in plan["slots"].items()}
    for entry in epoch["sources"]:
        rel, parts = entry["row"]["relation"], json.loads(entry["row"]["key"])
        if rel in plan["kinds"]:
            row, slot = element(plan["kinds"][rel], parts[0]), "$id"
        elif rel in slot_of:
            name, slot = slot_of[rel]
            row = element(name, parts[0])
        else:
            continue  # an enum row: schema, not data
        if row is None:
            raise KeyError((rel, parts[0]))  # a source of a row the role does not read: as before, an error
        # One array per slot (§3.5): a many-valued slot has one Rezono row per member, each with its own sources,
        # and they all land in the slot's array. Sorted by canonical JSON, each Source once, whatever the order.
        row.setdefault("$src", {}).setdefault(slot, []).extend(entry["sources"])
    for row in elems.values():
        for slot, objs in row.get("$src", {}).items():
            row["$src"][slot] = [json.loads(t) for t in sorted({canonical_json(o) for o in objs})]
    return [elems[k] for k in sorted(elems)]


def form(manifest: dict, bundle: dict, rows: dict, full, witnesses: list, sources: list, role: str) -> dict:
    """One role's form: its schema document, rows and hashes, and the manifest's names it carries. `full` is
    None for the complete role."""
    doc, plan = schema_document(bundle, full)
    out = row_json(doc, plan, {"rows": rows, "witnesses": witnesses, "sources": sources})
    return {"schema": doc, "rows": out, "hashes": hashes(doc, out), "manifest": role_manifest(manifest, role),
            "role": role}


# --- back onto Rezono relations ----------------------------------------------------------------------------------

def _key(value) -> str:
    return canonical_json(value)


def relations(doc: dict, plan: dict, rows: list[dict]) -> dict[str, set]:
    """What a form says, as Rezono relations: per relation of the plan the set of its rows, each value spelled as
    `row_json` spells it. A state object is no value; a derived row is its columns."""
    out: dict[str, set] = {t: set() for t in [*plan["kinds"], *plan["slots"], *plan["derived"]]}
    kind_table = {name: t for t, name in plan["kinds"].items()}
    derived_table = {name: (t, cols) for t, (name, cols) in plan["derived"].items()}
    slot_table = {(kind, slot): t for t, (name, slot, _) in plan["slots"].items() for kind in plan["family"][name]}
    for r in rows:
        name, i = r["$kind"], r["$id"]
        if name in derived_table:
            t, cols = derived_table[name]
            out[t].add(_key([
                r[c]["$ref"] if isinstance(r[c], dict)
                else ("true" if r[c] else "false") if isinstance(r[c], bool)
                else r[c]
                for c in cols
            ]))
            continue
        for kind in l0.chain(doc, name):  # an element of a subkind is an element of every kind above it
            out[kind_table[kind]].add(_key([i]))
        for slot in doc["kinds"][name]["slots"]:
            v = r.get(slot)
            members = v if isinstance(v, list) else [v]
            for m in members:
                if isinstance(m, dict) and "$ref" not in m:
                    continue  # a state: no value
                out[slot_table[name, slot]].add(_key([i, m]))
    return out


def expected_relations(doc: dict, plan: dict, rows: dict) -> dict[str, set]:
    """The role's own rows per relation of the plan, each value spelled as `row_json` spells it."""
    out: dict[str, set] = {}
    kind_table = {name: t for t, name in plan["kinds"].items()}
    for t, name in plan["kinds"].items():  # with the elements the role reads as a kind below (see `relations`)
        out[t] = {_key(list(k)) for below in plan["family"][name] for k in rows.get(kind_table[below], [])}
    for t, (name, slot, a) in plan["slots"].items():
        out[t] = {_key([i, _value(doc, name, slot, a, v)]) for i, v in rows.get(t, [])}
    for t in plan["derived"]:
        out[t] = {_key([("true" if v else "false") if isinstance(v, bool) else v for v in k]) for k in rows.get(t, [])}
    return out


def differences(doc: dict, plan: dict, form_rows: list[dict], rows: dict, limit: int = 3) -> list[str]:
    """Where a form says other than the role's rows: per relation, a row only in the form or only in the files."""
    got, want = relations(doc, plan, form_rows), expected_relations(doc, plan, rows)
    out = []
    for t in sorted(want):
        more, less = sorted(got[t] - want[t]), sorted(want[t] - got[t])
        out += [f"{t}: {k} is in the form, not in the role's files" for k in more[:limit]]
        out += [f"{t}: {k} is in the role's files, not in the form" for k in less[:limit]]
    return out
