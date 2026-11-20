"""Compare two compiled schema bundles and classify the change to a pack's public surface.

Implements the public-surface comparison of docs/rezono/v0.md section 4c and
decisions/language-surface-compatibility.md sections 1-3, 6 and 7:

- Reads only compiled schema bundles (`rezono.schema-bundle/1`), never source text.
- Fails closed on malformed bundles with `ValueError`.
- Returns `{"class": <"patch" | "minor" | "major">, "changes": [...]}` where each
  change is `{"element", "change", "class"}` sorted by `(element, change)`.
- Non-surface bundle content (spans, sentences, labels, messages, channels, pages,
  kind order, questions, rules, pack version and display helpers) produces no changes.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from rezono_canon import sha256_hex
from rezono_checker.canon import strict_json_loads

__all__ = [
    "BUNDLE_FILE",
    "BUNDLE_FORMAT",
    "compare",
    "compatibility",
    "manifest_bundle_entry",
    "parse_semver",
    "read_manifest_bundle",
    "refusal",
]

BUNDLE_FILE = "bundle/schema-bundle.json"
BUNDLE_FORMAT = "rezono.schema-bundle/1"
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"\A(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_CLASS_RANK = {"patch": 0, "minor": 1, "major": 2}
_WORLDS = frozenset({"open", "closed"})
_DECIMAL_INT = re.compile(r"^-?(0|[1-9][0-9]*)$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SLOT_DERIVED_CHECKS = frozenset(
    {"totality", "functionality", "reference", "value_range", "pattern", "cardinality"}
)
_FUTURE_SURFACE_FIELDS = ("may_read", "effect", "totality")


def _require_dict(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected an object")
    return value


def _require_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where}: expected a list")
    return value


def _require_str(value: Any, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"{where}: expected a {'string' if allow_empty else 'non-empty string'}")
    return value


def _require_bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{where}: expected a boolean")
    return value


def _optional_str(obj: dict[str, Any], key: str, where: str, *, allow_empty: bool = False) -> str | None:
    if key not in obj:
        return None
    return _require_str(obj[key], f"{where}.{key}", allow_empty=allow_empty)


def _optional_bool(obj: dict[str, Any], key: str, where: str, default: bool = False) -> bool:
    if key not in obj:
        return default
    return _require_bool(obj[key], f"{where}.{key}")


def _optional_world(obj: dict[str, Any], where: str) -> str:
    if "world" not in obj:
        return "closed"
    world = obj["world"]
    if not isinstance(world, str) or world not in _WORLDS:
        raise ValueError(f"{where}.world: expected 'open' or 'closed'")
    return world


def _optional_decimal_int(obj: dict[str, Any], key: str, where: str) -> int | None:
    if key not in obj:
        return None
    raw = obj[key]
    if not isinstance(raw, str) or not _DECIMAL_INT.fullmatch(raw):
        raise ValueError(f"{where}.{key}: expected a canonical decimal integer string")
    return int(raw)


def _optional_str_list(obj: dict[str, Any], key: str, where: str, *, allow_empty_item: bool = False) -> list[str]:
    if key not in obj:
        return []
    items = _require_list(obj[key], f"{where}.{key}")
    return [_require_str(item, f"{where}.{key}[{i}]", allow_empty=allow_empty_item) for i, item in enumerate(items)]


def _optional_date(obj: dict[str, Any], key: str, where: str) -> datetime.date | None:
    if key not in obj:
        return None
    raw = obj[key]
    if not isinstance(raw, str) or not _ISO_DATE.fullmatch(raw):
        raise ValueError(f"{where}.{key}: expected an ISO date YYYY-MM-DD")
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as err:
        raise ValueError(f"{where}.{key}: invalid calendar date {raw!r}") from err


def _validate_semantic(value: Any, where: str) -> dict[str, Any]:
    sem = _require_dict(value, where)
    _require_str(sem.get("case"), f"{where}.case")
    _require_str(sem.get("base"), f"{where}.base")
    if "open" in sem:
        _require_bool(sem["open"], f"{where}.open")
    return sem


def _qualify(element_id: str, module: str | None) -> str:
    """Prefix elements from an imported module (`<pack>:<path>`) with their module."""
    if module and ":" in module:
        return f"{module}/{element_id}"
    return element_id


def _parse_bundle(raw: Any, label: str) -> dict[str, Any]:
    """Validate and index the public surface of one compiled schema bundle (fail closed)."""
    bundle = _require_dict(raw, label)
    if bundle.get("format") != BUNDLE_FORMAT:
        raise ValueError(f"{label}.format: expected {BUNDLE_FORMAT!r}")

    pack_info = _require_dict(bundle.get("pack"), f"{label}.pack")
    pack_id = _require_str(pack_info.get("id"), f"{label}.pack.id")
    _require_str(pack_info.get("version"), f"{label}.pack.version")
    pack_base = _optional_str(pack_info, "base", f"{label}.pack")

    for list_key in ("schemas", "imports"):
        if list_key in bundle:
            _require_list(bundle[list_key], f"{label}.{list_key}")

    # Kinds
    raw_kinds = _require_list(bundle.get("kinds"), f"{label}.kinds")
    kinds: dict[str, dict[str, Any]] = {}
    kind_modules: dict[str, str | None] = {}
    kind_identifiers: dict[str, str | None] = {}
    seen_kind_stables: set[str] = set()
    for i, entry in enumerate(raw_kinds):
        where = f"{label}.kinds[{i}]"
        kind = _require_dict(entry, where)
        kid = _require_str(kind.get("id"), f"{where}.id")
        stable_id = _require_str(kind.get("stable_id"), f"{where}.stable_id")
        if kid in kinds:
            raise ValueError(f"{where}.id: duplicate kind id {kid!r}")
        if stable_id in seen_kind_stables:
            raise ValueError(f"{where}.stable_id: duplicate kind stable_id {stable_id!r}")
        seen_kind_stables.add(stable_id)
        module = _optional_str(kind, "module", where)
        identifier = _optional_str(kind, "identifier", where)
        kind_modules[kid] = module
        kind_identifiers[kid] = identifier
        private = _optional_bool(kind, "private", where, default=False)
        parsed_kind = {
            "id": kid,
            "stable_id": stable_id,
            "element": _qualify(kid, module),
            "parent": _optional_str(kind, "parent", where),
            "abstract": _require_bool(kind.get("abstract"), f"{where}.abstract"),
            "identifier": identifier,
            "id_type": _require_str(kind.get("id_type"), f"{where}.id_type"),
            "identifier_patterns": _optional_str_list(kind, "identifier_patterns", where, allow_empty_item=True),
            "world": _optional_world(kind, where),
            "plane": _optional_str(kind, "plane", where),
            "relationship": _optional_bool(kind, "relationship", where, default=False),
            "ends": _optional_str_list(kind, "ends", where),
            "iri": _optional_str(kind, "iri", where),
            "deprecated_until": _optional_date(kind, "deprecated_until", where),
            "future": {f: kind[f] for f in _FUTURE_SURFACE_FIELDS if f in kind},
        }
        if not private:
            kinds[kid] = parsed_kind

    # Slots (arrows and attributes unified so arrow <-> attribute changes are retypes)
    slots: dict[str, dict[str, Any]] = {}
    all_slot_ids: set[str] = set()
    seen_slot_stables: set[str] = set()
    enum_slot_openness: dict[str, list[bool]] = {}
    for section, is_arrow in (("arrows", True), ("attributes", False)):
        raw_slots = _require_list(bundle[section], f"{label}.{section}") if section in bundle else []
        for i, entry in enumerate(raw_slots):
            where = f"{label}.{section}[{i}]"
            slot = _require_dict(entry, where)
            sid = _require_str(slot.get("id"), f"{where}.id")
            stable_id = _require_str(slot.get("stable_id"), f"{where}.stable_id")
            if sid in all_slot_ids:
                raise ValueError(f"{where}.id: duplicate slot id {sid!r}")
            if stable_id in seen_slot_stables:
                raise ValueError(f"{where}.stable_id: duplicate slot stable_id {stable_id!r}")
            all_slot_ids.add(sid)
            seen_slot_stables.add(stable_id)
            kind_id = _require_str(slot.get("kind"), f"{where}.kind")
            required = _require_bool(slot.get("required"), f"{where}.required")
            multivalued = _require_bool(slot.get("multivalued"), f"{where}.multivalued")
            min_card = _optional_decimal_int(slot, "minimum_cardinality", where)
            max_card = _optional_decimal_int(slot, "maximum_cardinality", where)
            if min_card is not None and min_card < 0:
                raise ValueError(f"{where}.minimum_cardinality: must be >= 0")
            if max_card is not None and max_card < 0:
                raise ValueError(f"{where}.maximum_cardinality: must be >= 0")
            if min_card is not None and max_card is not None and min_card > max_card:
                raise ValueError(f"{where}: minimum_cardinality exceeds maximum_cardinality")
            world = _optional_world(slot, where)
            semantic = _validate_semantic(slot.get("semantic"), f"{where}.semantic")
            private = _optional_bool(slot, "private", where, default=False)
            if is_arrow:
                target = _require_str(slot.get("target"), f"{where}.target")
                inlined = _require_bool(slot.get("inlined"), f"{where}.inlined")
                value_type = schema_type = derivation = enum_name = currency = input_format = constant = None
                minimum = maximum = None
                patterns: list[str] = []
            else:
                target = None
                inlined = None
                value_type = _require_str(slot.get("type"), f"{where}.type")
                schema_type = _require_str(slot.get("schema_type"), f"{where}.schema_type")
                derivation = _require_str(slot.get("derivation"), f"{where}.derivation")
                enum_name = _optional_str(slot, "enum", where)
                currency = _optional_str(slot, "currency", where)
                input_format = _optional_str(slot, "input_format", where)
                minimum = _optional_decimal_int(slot, "minimum", where)
                maximum = _optional_decimal_int(slot, "maximum", where)
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise ValueError(f"{where}: minimum exceeds maximum")
                patterns = _optional_str_list(slot, "patterns", where, allow_empty_item=True)
                constant = _optional_str(slot, "constant", where, allow_empty=True)
            ref_enum = enum_name or (semantic.get("enum") if isinstance(semantic.get("enum"), str) else None)
            is_enum_slot = semantic["case"] == "enum" or ref_enum is not None
            enum_open = bool(semantic.get("open", False)) if is_enum_slot else False
            if not private and ref_enum is not None:
                enum_slot_openness.setdefault(ref_enum, []).append(enum_open)
            parsed_slot = {
                "id": sid,
                "stable_id": stable_id,
                "element": _qualify(sid, kind_modules.get(kind_id)),
                "is_arrow": is_arrow,
                "required": required,
                "multivalued": multivalued,
                "minimum_cardinality": min_card,
                "maximum_cardinality": max_card,
                "world": world,
                "semantic_type": {k: v for k, v in semantic.items() if k != "open"},
                "is_enum": is_enum_slot,
                "enum_open": enum_open,
                "target": target,
                "inlined": inlined,
                "type": value_type,
                "schema_type": schema_type,
                "derivation": derivation,
                "enum": enum_name,
                "currency": currency,
                "input_format": input_format,
                "minimum": minimum,
                "maximum": maximum,
                "patterns": patterns,
                "constant": constant,
                "deprecated_until": _optional_date(slot, "deprecated_until", where),
                "future": {f: slot[f] for f in _FUTURE_SURFACE_FIELDS if f in slot},
            }
            if not private:
                slots[sid] = parsed_slot

    # Enums
    raw_enums = _require_list(bundle["enums"], f"{label}.enums") if "enums" in bundle else []
    enums: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(raw_enums):
        where = f"{label}.enums[{i}]"
        enum = _require_dict(entry, where)
        eid = _require_str(enum.get("id"), f"{where}.id")
        if eid in enums:
            raise ValueError(f"{where}.id: duplicate enum id {eid!r}")
        raw_values = _require_list(enum.get("values"), f"{where}.values")
        values = [_require_str(v, f"{where}.values[{j}]") for j, v in enumerate(raw_values)]
        if len(set(values)) != len(values):
            raise ValueError(f"{where}.values: duplicate values in enum {eid!r}")
        module = _optional_str(enum, "module", where)
        private = _optional_bool(enum, "private", where, default=False)
        explicit_open: bool | None = None
        if "world" in enum and "open" in enum:
            world_open = _optional_world(enum, where) == "open"
            flag_open = _require_bool(enum["open"], f"{where}.open")
            if world_open != flag_open:
                raise ValueError(f"{where}: conflicting 'world' and 'open'")
            explicit_open = world_open
        elif "world" in enum:
            explicit_open = _optional_world(enum, where) == "open"
        elif "open" in enum:
            explicit_open = _require_bool(enum["open"], f"{where}.open")
        slot_flags = enum_slot_openness.get(eid, [])
        is_open = explicit_open if explicit_open is not None else (bool(slot_flags) and all(slot_flags))
        if not private:
            enums[eid] = {
                "id": eid,
                "element": _qualify(eid, module),
                "module": module,
                "values": values,
                "explicit_open": explicit_open,
                "is_open": is_open,
                "deprecated_until": _optional_date(enum, "deprecated_until", where),
            }

    # Derived relations
    raw_relations = _require_list(bundle["relations"], f"{label}.relations") if "relations" in bundle else []
    relations: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(raw_relations):
        where = f"{label}.relations[{i}]"
        rel = _require_dict(entry, where)
        rid = _require_str(rel.get("id"), f"{where}.id")
        if rid in relations:
            raise ValueError(f"{where}.id: duplicate relation id {rid!r}")
        module = _optional_str(rel, "module", where)
        raw_cols = _require_list(rel.get("columns"), f"{where}.columns")
        columns = []
        seen_cols: set[str] = set()
        for j, col_entry in enumerate(raw_cols):
            cwhere = f"{where}.columns[{j}]"
            col = _require_dict(col_entry, cwhere)
            cname = _require_str(col.get("name"), f"{cwhere}.name")
            if cname in seen_cols:
                raise ValueError(f"{cwhere}.name: duplicate column {cname!r}")
            seen_cols.add(cname)
            ctype = _require_str(col.get("type"), f"{cwhere}.type")
            csem = _validate_semantic(col["semantic"], f"{cwhere}.semantic") if "semantic" in col else None
            ccur = _optional_str(col, "currency", cwhere)
            columns.append({"name": cname, "type": ctype, "semantic": csem, "currency": ccur})
        rel_sem = _validate_semantic(rel["semantic"], f"{where}.semantic") if "semantic" in rel else None
        private = _optional_bool(rel, "private", where, default=False)
        if not private:
            relations[rid] = {
                "id": rid,
                "element": _qualify(rid, module),
                "module": module,
                "columns": columns,
                "world": _optional_world(rel, where),
                "semantic": rel_sem,
                "absence": _optional_bool(rel, "absence", where, default=False),
                "outcome": _optional_str(rel, "outcome", where),
                "closes": _optional_str(rel, "closes", where),
                "extend": _optional_bool(rel, "extend", where, default=False),
                "calc": _optional_str(rel, "calc", where),
                "checks": _optional_str_list(rel, "checks", where),
                "deprecated_until": _optional_date(rel, "deprecated_until", where),
                "future": {f: rel[f] for f in _FUTURE_SURFACE_FIELDS if f in rel},
            }

    # Checks
    raw_checks = _require_list(bundle["checks"], f"{label}.checks") if "checks" in bundle else []
    checks: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(raw_checks):
        where = f"{label}.checks[{i}]"
        chk = _require_dict(entry, where)
        view = _require_str(chk.get("view"), f"{where}.view")
        if view in checks:
            raise ValueError(f"{where}.view: duplicate check view {view!r}")
        check_type = _require_str(chk.get("check"), f"{where}.check")
        kind_id = _require_str(chk.get("kind"), f"{where}.kind")
        subject = _optional_str(chk, "subject", where, allow_empty=True) or None
        path = _optional_str(chk, "path", where, allow_empty=True)
        owner = _check_derived_owner(check_type, kind_id, subject, kind_identifiers, all_slot_ids)
        checks[view] = {
            "view": view,
            "element": _qualify(view, kind_modules.get(kind_id)),
            "check": check_type,
            "kind": kind_id,
            "path": path,
            "owner": owner,
        }

    # Reasons
    raw_reasons = _require_list(bundle["reasons"], f"{label}.reasons") if "reasons" in bundle else []
    reasons: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(raw_reasons):
        where = f"{label}.reasons[{i}]"
        reason = _require_dict(entry, where)
        code = _require_str(reason.get("code"), f"{where}.code")
        if code in reasons:
            raise ValueError(f"{where}.code: duplicate reason code {code!r}")
        iri = _require_str(reason.get("iri"), f"{where}.iri")
        states = _optional_str_list(reason, "states", where) if "states" in reason else None
        reasons[code] = {"code": code, "element": f"reason.{code}", "iri": iri, "states": states}

    return {
        "pack_id": pack_id,
        "pack_base": pack_base,
        "kinds": kinds,
        "slots": slots,
        "enums": enums,
        "relations": relations,
        "checks": checks,
        "reasons": reasons,
    }


def _check_derived_owner(
    check_type: str,
    kind_id: str,
    subject: str | None,
    kind_identifiers: dict[str, str | None],
    all_slot_ids: set[str],
) -> tuple[str, str] | None:
    """Return `('kind', kind_id)` or `('slot', slot_id)` for compiler-generated checks already covered
    by kind/slot comparison, or `None` for standalone checks (`unique`, `path_equation`, `rule`)."""
    if check_type == "identification":
        return ("kind", kind_id)
    if check_type == "reference" and subject == "is_a":
        return ("kind", kind_id)
    if check_type == "pattern" and subject is not None:
        slot_id = f"{kind_id}.{subject}"
        if slot_id in all_slot_ids:
            return ("slot", slot_id)
        if kind_identifiers.get(kind_id) == subject:
            return ("kind", kind_id)
    if check_type in _SLOT_DERIVED_CHECKS and subject is not None:
        return ("slot", f"{kind_id}.{subject}")
    return None


def _match_elements(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> tuple[list[tuple[str, str, bool]], list[str], list[str]]:
    """Match elements by id, and across different ids by stable_id (renames)."""
    before_by_stable = {item["stable_id"]: eid for eid, item in before.items()}
    after_by_stable = {item["stable_id"]: eid for eid, item in after.items()}
    matched: list[tuple[str, str, bool]] = []
    used_before: set[str] = set()
    used_after: set[str] = set()

    for eid in sorted(before.keys() & after.keys()):
        if before[eid]["stable_id"] == after[eid]["stable_id"]:
            matched.append((eid, eid, False))
            used_before.add(eid)
            used_after.add(eid)

    for stable_id in sorted(before_by_stable.keys() & after_by_stable.keys()):
        b_id = before_by_stable[stable_id]
        a_id = after_by_stable[stable_id]
        if b_id not in used_before and a_id not in used_after:
            matched.append((b_id, a_id, b_id != a_id))
            used_before.add(b_id)
            used_after.add(a_id)

    for eid in sorted((before.keys() - used_before) & (after.keys() - used_after)):
        matched.append((eid, eid, False))
        used_before.add(eid)
        used_after.add(eid)

    return matched, sorted(before.keys() - used_before), sorted(after.keys() - used_after)


def _compare_world(before_world: str, after_world: str, element: str, record) -> bool:
    if before_world == after_world:
        return False
    record(element, "closed" if after_world == "closed" else "opened", "major")
    return True


def _compare_patterns(before_pats: list[str], after_pats: list[str]) -> str | None:
    """Return 'widened', 'narrowed', or None for a change in required regex patterns."""
    b_set, a_set = set(before_pats), set(after_pats)
    if b_set == a_set:
        return None
    return "widened" if a_set < b_set else "narrowed"


def _compare_deprecation(
    before_date: datetime.date | None,
    after_date: datetime.date | None,
    element: str,
    record,
) -> bool:
    """Section 6: adding, extending or removing a deprecation is a patch; moving its date earlier is major."""
    if before_date is not None and after_date is not None and after_date < before_date:
        record(element, "changed", "major")
        return True
    return False


def _compare_future_fields(before_future: dict[str, Any], after_future: dict[str, Any], element: str, record) -> bool:
    """Section 1: a property absent from the earlier bundle is not compared; dropping or changing one is major."""
    changed = False
    for field, b_val in before_future.items():
        if field not in after_future or after_future[field] != b_val:
            record(element, "changed", "major")
            changed = True
    return changed


def _slot_type_signature(slot: dict[str, Any]) -> tuple[Any, ...]:
    return (
        slot["is_arrow"],
        slot["semantic_type"],
        slot["target"],
        slot["type"],
        slot["schema_type"],
        slot["derivation"],
        slot["enum"],
        slot["currency"],
        slot["input_format"],
    )


def _slot_is_plus(slot: dict[str, Any]) -> bool:
    """A multivalued slot requiring at least one value (`T+` or minimum_cardinality >= 1)."""
    if not slot["multivalued"]:
        return False
    return slot["required"] or (slot["minimum_cardinality"] is not None and slot["minimum_cardinality"] >= 1)


def _compare_slot_refinements(b_slot: dict[str, Any], a_slot: dict[str, Any], element: str, record) -> bool:
    widened = False
    narrowed = False

    b_min, a_min = b_slot["minimum"], a_slot["minimum"]
    if b_min != a_min:
        if b_min is not None and (a_min is None or a_min < b_min):
            widened = True
        else:
            narrowed = True

    b_max, a_max = b_slot["maximum"], a_slot["maximum"]
    if b_max != a_max:
        if b_max is not None and (a_max is None or a_max > b_max):
            widened = True
        else:
            narrowed = True

    pat_change = _compare_patterns(b_slot["patterns"], a_slot["patterns"])
    if pat_change == "widened":
        widened = True
    elif pat_change == "narrowed":
        narrowed = True

    b_const, a_const = b_slot["constant"], a_slot["constant"]
    if b_const != a_const:
        if b_const is not None and a_const is None:
            widened = True
        else:
            narrowed = True

    if narrowed:
        record(element, "narrowed", "major")
        return True
    if widened:
        record(element, "widened", "minor")
        return True
    return False


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two compiled schema bundles and classify their public-surface changes."""
    old = _parse_bundle(before, "before")
    new = _parse_bundle(after, "after")

    recorded: dict[tuple[str, str], str] = {}

    def record(element: str, change: str, cls: str) -> None:
        key = (element, change)
        prev = recorded.get(key)
        if prev is None or _CLASS_RANK[cls] > _CLASS_RANK[prev]:
            recorded[key] = cls

    # Track kinds/slots that changed so compiler-generated derived checks do not duplicate or invert their class.
    changed_before_owners: set[tuple[str, str]] = set()
    changed_after_owners: set[tuple[str, str]] = set()

    # 1. Pack-level identity and base IRI
    if old["pack_id"] != new["pack_id"]:
        record("pack.id", "changed", "major")
    if old["pack_base"] != new["pack_base"]:
        record("pack.base", "changed", "major")

    # 2. Kinds
    kind_matches, kind_removed, kind_added = _match_elements(old["kinds"], new["kinds"])
    for kid in kind_removed:
        record(old["kinds"][kid]["element"], "removed", "major")
        changed_before_owners.add(("kind", kid))
    for kid in kind_added:
        record(new["kinds"][kid]["element"], "added", "minor")
        changed_after_owners.add(("kind", kid))
    for b_id, a_id, renamed in kind_matches:
        b_kind, a_kind = old["kinds"][b_id], new["kinds"][a_id]
        elem = b_kind["element"]
        touched = False
        if renamed:
            record(elem, "renamed", "major")
            touched = True
        if _compare_world(b_kind["world"], a_kind["world"], elem, record):
            touched = True
        pat_change = _compare_patterns(b_kind["identifier_patterns"], a_kind["identifier_patterns"])
        if pat_change is not None:
            record(elem, pat_change, "minor" if pat_change == "widened" else "major")
            touched = True
        for prop in ("parent", "abstract", "identifier", "id_type", "plane", "relationship", "ends", "iri"):
            if b_kind[prop] != a_kind[prop]:
                record(elem, "changed", "major")
                touched = True
        if _compare_deprecation(b_kind["deprecated_until"], a_kind["deprecated_until"], elem, record):
            touched = True
        if _compare_future_fields(b_kind["future"], a_kind["future"], elem, record):
            touched = True
        if touched:
            changed_before_owners.add(("kind", b_id))
            changed_after_owners.add(("kind", a_id))

    # 3. Slots (arrows and attributes)
    slot_matches, slot_removed, slot_added = _match_elements(old["slots"], new["slots"])
    for sid in slot_removed:
        record(old["slots"][sid]["element"], "removed", "major")
        changed_before_owners.add(("slot", sid))
    for sid in slot_added:
        a_slot = new["slots"][sid]
        record(a_slot["element"], "added", "major" if _slot_is_plus(a_slot) else "minor")
        changed_after_owners.add(("slot", sid))
    for b_id, a_id, renamed in slot_matches:
        b_slot, a_slot = old["slots"][b_id], new["slots"][a_id]
        elem = b_slot["element"]
        touched = False
        if renamed:
            record(elem, "renamed", "major")
            touched = True
        retyped = _slot_type_signature(b_slot) != _slot_type_signature(a_slot)
        if retyped:
            record(elem, "retyped", "major")
            touched = True
        else:
            if b_slot["is_enum"] and a_slot["is_enum"] and b_slot["enum_open"] != a_slot["enum_open"]:
                record(elem, "closed" if b_slot["enum_open"] else "opened", "major")
                touched = True
            if _compare_slot_refinements(b_slot, a_slot, elem, record):
                touched = True
        if (b_slot["required"], b_slot["multivalued"], b_slot["minimum_cardinality"], b_slot["maximum_cardinality"]) != (
            a_slot["required"], a_slot["multivalued"], a_slot["minimum_cardinality"], a_slot["maximum_cardinality"]
        ):
            record(elem, "cardinality", "major")
            touched = True
        if _compare_world(b_slot["world"], a_slot["world"], elem, record):
            touched = True
        if b_slot["is_arrow"] and a_slot["is_arrow"] and b_slot["inlined"] != a_slot["inlined"]:
            record(elem, "changed", "major")
            touched = True
        if _compare_deprecation(b_slot["deprecated_until"], a_slot["deprecated_until"], elem, record):
            touched = True
        if _compare_future_fields(b_slot["future"], a_slot["future"], elem, record):
            touched = True
        if touched:
            changed_before_owners.add(("slot", b_id))
            changed_after_owners.add(("slot", a_id))

    # 4. Enums and their values
    for eid in sorted(old["enums"].keys() | new["enums"].keys()):
        b_enum = old["enums"].get(eid)
        a_enum = new["enums"].get(eid)
        if b_enum is None:
            record(a_enum["element"], "added", "minor")
            continue
        if a_enum is None:
            record(b_enum["element"], "removed", "major")
            continue
        elem = b_enum["element"]
        module = b_enum["module"]
        if b_enum["explicit_open"] is not None:
            b_open = b_enum["explicit_open"]
            a_open = bool(a_enum["explicit_open"])
            if b_open != a_open:
                record(elem, "closed" if b_open else "opened", "major")
        b_vals, a_vals = b_enum["values"], a_enum["values"]
        b_set, a_set = set(b_vals), set(a_vals)
        both_open = b_enum["is_open"] and a_enum["is_open"]
        for val in sorted(b_set - a_set):
            record(_qualify(val, module), "removed", "major")
        added_vals = [val for val in a_vals if val not in b_set]
        for val in sorted(added_vals):
            record(_qualify(val, module), "added", "minor" if both_open else "major")
        kept_in_new = [val for val in a_vals if val in b_set]
        kept_in_old = [val for val in b_vals if val in a_set]
        if kept_in_new != kept_in_old or (both_open and added_vals and a_vals[: len(kept_in_new)] != kept_in_new):
            record(elem, "changed", "major")
        _compare_deprecation(b_enum["deprecated_until"], a_enum["deprecated_until"], elem, record)

    # 5. Derived relations
    for rid in sorted(old["relations"].keys() | new["relations"].keys()):
        b_rel = old["relations"].get(rid)
        a_rel = new["relations"].get(rid)
        if b_rel is None:
            record(a_rel["element"], "added", "minor")
            continue
        if a_rel is None:
            record(b_rel["element"], "removed", "major")
            continue
        elem = b_rel["element"]
        _compare_world(b_rel["world"], a_rel["world"], elem, record)
        b_cols, a_cols = b_rel["columns"], a_rel["columns"]
        if [c["name"] for c in b_cols] != [c["name"] for c in a_cols]:
            record(elem, "changed", "major")
        elif any(
            (cb["type"], cb["semantic"], cb["currency"]) != (ca["type"], ca["semantic"], ca["currency"])
            for cb, ca in zip(b_cols, a_cols, strict=True)
        ):
            record(elem, "retyped", "major")
        if b_rel["semantic"] != a_rel["semantic"]:
            record(elem, "retyped", "major")
        for prop in ("absence", "outcome", "closes", "extend", "calc"):
            if b_rel[prop] != a_rel[prop]:
                record(elem, "changed", "major")
        b_rel_checks, a_rel_checks = set(b_rel["checks"]), set(a_rel["checks"])
        for chk_name in sorted(b_rel_checks - a_rel_checks):
            record(_qualify(chk_name, b_rel["module"]), "removed", "major")
        for chk_name in sorted(a_rel_checks - b_rel_checks):
            record(_qualify(chk_name, a_rel["module"]), "added", "minor")
        _compare_deprecation(b_rel["deprecated_until"], a_rel["deprecated_until"], elem, record)
        _compare_future_fields(b_rel["future"], a_rel["future"], elem, record)

    # 6. Checks
    for view in sorted(old["checks"].keys() | new["checks"].keys()):
        b_chk = old["checks"].get(view)
        a_chk = new["checks"].get(view)
        if b_chk is None:
            if a_chk["owner"] not in changed_after_owners:
                record(a_chk["element"], "added", "minor")
            continue
        if a_chk is None:
            if b_chk["owner"] not in changed_before_owners:
                record(b_chk["element"], "removed", "major")
            continue
        if b_chk["owner"] is None and (
            b_chk["check"] != a_chk["check"]
            or b_chk["kind"] != a_chk["kind"]
            or b_chk["path"] != a_chk["path"]
        ):
            record(b_chk["element"], "changed", "major")

    # 7. Reasons
    for code in sorted(old["reasons"].keys() | new["reasons"].keys()):
        b_reason = old["reasons"].get(code)
        a_reason = new["reasons"].get(code)
        if b_reason is None:
            record(a_reason["element"], "added", "minor")
            continue
        if a_reason is None:
            record(b_reason["element"], "removed", "major")
            continue
        if b_reason["iri"] != a_reason["iri"]:
            record(b_reason["element"], "changed", "major")
        if b_reason["states"] is not None and a_reason["states"] != b_reason["states"]:
            record(b_reason["element"], "changed", "major")

    changes = [
        {"element": elem, "change": change, "class": cls}
        for (elem, change), cls in sorted(recorded.items())
    ]
    overall = max((c["class"] for c in changes), key=_CLASS_RANK.__getitem__, default="patch")
    return {"class": overall, "changes": changes}


def _parse_json_bundle(raw: Any, where: str) -> dict[str, Any]:
    """Parse a strict JSON schema bundle document from UTF-8 bytes or text (fail closed)."""
    if not isinstance(raw, (bytes, bytearray, str)) or not raw:
        raise ValueError(f"{where}: missing compiled schema bundle")
    try:
        doc = strict_json_loads(raw)
    except (UnicodeDecodeError, ValueError) as err:
        raise ValueError(f"{where}: invalid schema bundle JSON: {err}") from err
    return _require_dict(doc, where)


def manifest_bundle_entry(manifest: Any) -> tuple[str, str]:
    """Extract `(uri, sha256)` for `bundle/schema-bundle.json` from a published manifest (fail closed)."""
    doc = _require_dict(manifest, "manifest")
    mid = _require_str(doc.get("id"), "manifest.id")
    compiled = _require_list(doc.get("compiled"), f"manifest {mid}.compiled")
    matches: list[tuple[str, str]] = []
    for i, item in enumerate(compiled):
        where = f"manifest {mid}.compiled[{i}]"
        entry = _require_dict(item, where)
        if entry.get("file") != BUNDLE_FILE:
            continue
        uri = _require_str(entry.get("uri"), f"{where}.uri")
        digest = _require_str(entry.get("sha256"), f"{where}.sha256")
        if not _SHA256_HEX.fullmatch(digest):
            raise ValueError(f"{where}.sha256: expected a 64-character lowercase hex digest")
        matches.append((uri, digest))
    if not matches:
        raise ValueError(f"manifest {mid}: missing compiled entry for {BUNDLE_FILE}")
    if len(matches) > 1:
        raise ValueError(f"manifest {mid}: duplicate compiled entry for {BUNDLE_FILE}")
    return matches[0]


_UNSAFE_KEY_CHARS = frozenset({"\\", "%", "?", "#", ":"})


def _has_unsafe_key_chars(text: str) -> bool:
    return any(ch in _UNSAFE_KEY_CHARS or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text)


def _store_key_for_uri(store, uri: str, where: str, pack: str | None = None) -> str:
    """Resolve a manifest entry URI to a validated key within `store` (and `pack`, if given)."""
    try:
        prefix = store.uri("")
    except AttributeError as err:
        raise ValueError(f"{where}: store does not expose uri()") from err
    if not isinstance(prefix, str) or not prefix.endswith("/") or not uri.startswith(prefix):
        raise ValueError(f"{where}: uri {uri!r} does not belong to this store")
    key = uri[len(prefix):]
    if not key or _has_unsafe_key_chars(key):
        raise ValueError(f"{where}: invalid store key from uri {uri!r}")
    parts = key.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError(f"{where}: invalid store key from uri {uri!r}")
    if pack is not None:
        pack_name = _require_str(pack, f"{where}.pack")
        if "/" in pack_name or pack_name in {".", ".."} or _has_unsafe_key_chars(pack_name):
            raise ValueError(f"{where}: invalid pack name {pack_name!r}")
        if parts[0] != pack_name or len(parts) < 2:
            raise ValueError(f"{where}: key {key!r} lies outside pack {pack_name!r}")
    return key


def read_manifest_bundle(manifest: Any, store, *, pack: str | None = None) -> dict[str, Any]:
    """Read and verify the compiled schema bundle named by `manifest` from `store` (fail closed)."""
    doc = _require_dict(manifest, "manifest")
    mid = _require_str(doc.get("id"), "manifest.id")
    uri, digest = manifest_bundle_entry(doc)
    where = f"manifest {mid} {BUNDLE_FILE}"
    key = _store_key_for_uri(store, uri, where, pack=pack)
    data = store.get(key)
    if data is None:
        raise ValueError(f"{where}: bundle {key!r} is not in the store")
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError(f"{where}: bundle {key!r} did not return bytes")
    actual = sha256_hex(bytes(data))
    if actual != digest:
        raise ValueError(f"{where}: bundle {key!r} sha256 mismatch (expected {digest}, got {actual})")
    return _parse_json_bundle(data, where)


def parse_semver(version: Any, where: str = "pack.version") -> tuple[int, int, int]:
    """Parse a strict `MAJOR.MINOR.PATCH` semantic version (no leading zeroes), failing closed."""
    if not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ValueError(f"{where}: expected a semantic version MAJOR.MINOR.PATCH, got {version!r}")
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)


def _version_refusal(
    change_class: str,
    before_text: str,
    before_ver: tuple[int, int, int],
    after_text: str,
    after_ver: tuple[int, int, int],
) -> str | None:
    if change_class == "major":
        if after_ver[0] > before_ver[0]:
            return None
        return f"a major change needs a new major version: {before_text} to {after_text}"
    if change_class == "minor":
        if after_ver[:2] > before_ver[:2]:
            return None
        return f"a minor change needs a new minor version: {before_text} to {after_text}"
    if change_class == "patch":
        if after_ver > before_ver:
            return None
        return f"a patch change needs a higher version: {before_text} to {after_text}"
    raise ValueError(f"unknown compatibility class {change_class!r}")


def _compare_epoch(epoch, store, previous: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    """Load and compare `epoch`'s compiled schema bundle against an earlier main `previous` manifest.

    Returns None when `previous` is None or when `definition_sha256` and `compiler_sha256`
    are valid 64-character lowercase SHA-256 hex digests matching `previous` (same bundle,
    nothing to compare). Otherwise returns `(before, after, report)` where `report` is
    `{"against": <manifest id>, "class": ..., "changes": [...]}`.
    Fails closed with `ValueError` on missing, mismatched, or malformed manifests or bundles.
    """
    if previous is None:
        return None
    prev_doc = _require_dict(previous, "previous manifest")
    against = _require_str(prev_doc.get("id"), "previous manifest.id")
    pack = _require_str(getattr(epoch, "pack", None), "epoch.pack")
    cur_def = getattr(epoch, "definition_sha256", "")
    cur_comp = getattr(epoch, "compiler_sha256", "")
    if (
        isinstance(cur_def, str)
        and bool(_SHA256_HEX.fullmatch(cur_def))
        and isinstance(cur_comp, str)
        and bool(_SHA256_HEX.fullmatch(cur_comp))
        and prev_doc.get("definition_sha256") == cur_def
        and prev_doc.get("compiler_sha256") == cur_comp
    ):
        return None
    before = read_manifest_bundle(prev_doc, store, pack=pack)
    after = _parse_json_bundle(getattr(epoch, "bundle", ""), "epoch.bundle")
    result = compare(before, after)
    return before, after, {"against": against, "class": result["class"], "changes": result["changes"]}


def compatibility(epoch, store, previous: Any) -> dict[str, Any] | None:
    """Compare `epoch`'s compiled schema bundle against an earlier main `previous` manifest.

    Returns None when `previous` is None or when `definition_sha256` and `compiler_sha256`
    are valid 64-character lowercase SHA-256 hex digests matching `previous` (same bundle,
    nothing to compare). Otherwise returns `{"against": <manifest id>, "class": ..., "changes": [...]}`.
    Fails closed with `ValueError` on missing, mismatched, or malformed manifests or bundles.
    """
    compared = _compare_epoch(epoch, store, previous)
    return None if compared is None else compared[2]


def refusal(epoch, store, previous: Any) -> str | None:
    """Return the refusal reason for a main publication against `previous`, or None when allowed.

    Enforces decisions/language-surface-compatibility.md section 4 once the earlier publication's
    bundle has `pack.version` >= 1.0.0:
    - R033 refuses any major change (naming R033 and the first major change first).
    - The new bundle's `pack.version` must move at least as far as the compatibility class.
    Packs at 0.y.z (initial development) are not refused. Fails closed with `ValueError` on
    malformed manifests, bundles, or semantic versions.
    """
    compared = _compare_epoch(epoch, store, previous)
    if compared is None:
        return None
    before, after, report = compared
    before_text = before["pack"]["version"]
    after_text = after["pack"]["version"]
    before_ver = parse_semver(before_text, "before.pack.version")
    after_ver = parse_semver(after_text, "after.pack.version")
    if before_ver[0] < 1:
        return None
    reasons: list[str] = []
    if report["class"] == "major":
        major_changes = [c for c in report["changes"] if c["class"] == "major"]
        if major_changes:
            first = major_changes[0]
            reasons.append(
                f"R033 {first['element']} {first['change']}: "
                "a breaking change needs a reviewed proposal (docs/rezono/v0.md §4c)"
            )
        else:
            reasons.append("R033: a breaking change needs a reviewed proposal (docs/rezono/v0.md §4c)")
    version_reason = _version_refusal(report["class"], before_text, before_ver, after_text, after_ver)
    if version_reason is not None:
        reasons.append(version_reason)
    return "; ".join(reasons) if reasons else None
