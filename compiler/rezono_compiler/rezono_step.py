"""Validate port declarations, safe_steps pack bindings, and lower step declarations (rezono.module/4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

from . import modules, pack, rezono_module, rules
from .diagnostics import Diagnostic

if TYPE_CHECKING:
    from .native_rule_signatures import Refusal, Schema, Signature, Source


@dataclass(frozen=True)
class ReaderBinding:
    """One safe_steps.readers entry in pack.yaml, bound to a checked relation and input port."""
    relation: str
    port: str
    scope: tuple[str, ...]
    targets: frozenset[tuple[str, str | None]]


@dataclass(frozen=True)
class AtomicEffectBinding:
    """One safe_steps.atomic_effects entry in pack.yaml, bound to an effect apply operation."""
    port: str
    operation: str
    boundary: str
    evidence: dict[str, str]


@dataclass(frozen=True)
class SafeStepsBindings:
    """Resolved safe_steps bindings for one pack."""
    readers: dict[str, ReaderBinding]
    atomic_effects: dict[str, AtomicEffectBinding]


def _compile_error(message: str, where: str, code: str = "R049") -> pack.CompileError:
    diagnostic = Diagnostic(code, message, where)
    return pack.CompileError(str(diagnostic), [diagnostic])


def load_ports(pack_dir: Path, meta: dict, imported: Mapping[str, modules.Imported]) -> dict[str, dict[str, dict]]:
    """Load and validate every ports/*.yaml file in the root pack and its pinned imports."""
    root = str(meta["name"])
    dirs: list[tuple[str, Path]] = [(root, pack_dir)] + [(name, imp.dir) for name, imp in sorted(imported.items())]
    loaded: dict[str, dict[str, dict]] = {}
    loader = None
    port_error_cls = None
    for pack_name, directory in dirs:
        ports_dir = directory / "ports"
        files = sorted(ports_dir.glob("*.yaml")) if ports_dir.is_dir() else []
        by_name: dict[str, dict] = {}
        if not files:
            loaded[pack_name] = by_name
            continue
        if loader is None:
            from rezono_ports import PortError, load as load_port
            loader, port_error_cls = load_port, PortError
        for path in files:
            where = f"{pack_name}/ports/{path.name}"
            try:
                doc = loader(path)
            except port_error_cls as error:
                raise _compile_error(str(error), where) from error
            if doc["name"] != path.stem:
                raise _compile_error(
                    f"{where}: port declaration name {doc['name']!r} must match file stem {path.stem!r}",
                    where,
                )
            by_name[doc["name"]] = doc
        loaded[pack_name] = by_name
    return loaded


def visible_packs(owner: str, root: str, meta: dict, imported: Mapping[str, modules.Imported]) -> tuple[str, ...]:
    """Pack names whose ports and bindings are visible to `owner`: itself and its verified import closure."""
    if owner == root:
        deps = modules.dependency_order(dict(imported), modules.direct(meta))
    else:
        deps = modules.dependency_order(dict(imported), imported[owner].imports)
    return (owner, *deps)


def _resolve_port(
    ports_by_pack: Mapping[str, Mapping[str, dict]],
    visible: Iterable[str],
    port_name: str,
    *,
    expected_kind: str | None = None,
    where: str,
) -> dict:
    matches = [ports_by_pack[p][port_name] for p in visible if port_name in ports_by_pack.get(p, ())]
    if not matches:
        raise _compile_error(f"{where}: unknown port {port_name!r}", where, "R046")
    if len(matches) > 1:
        raise _compile_error(f"{where}: ambiguous port {port_name!r}", where, "R046")
    port = matches[0]
    if expected_kind is not None and port["kind"] != expected_kind:
        raise _compile_error(
            f"{where}: port {port_name!r} has kind {port['kind']!r}, expected {expected_kind!r}",
            where,
            "R003",
        )
    return port


def resolve_effect_operation(
    ports_by_pack: Mapping[str, Mapping[str, dict]],
    visible: Iterable[str],
    operation: str,
    where: str,
) -> tuple[str, str]:
    """Resolve an authored effect operation name to a unique visible effect port's `apply` operation."""
    matches = [
        port for p in visible for port in ports_by_pack.get(p, {}).values()
        if port["kind"] == "effect" and port["effect"]["apply"] == operation
    ]
    if not matches:
        raise _compile_error(
            f"{where}: unresolved effect operation {operation!r} (no visible effect port declares apply: {operation!r})",
            where,
            "R046",
        )
    if len(matches) > 1:
        names = ", ".join(sorted(m["name"] for m in matches))
        raise _compile_error(
            f"{where}: ambiguous effect operation {operation!r} across ports: {names}",
            where,
            "R046",
        )
    return matches[0]["name"], operation


def _all_model_slots(pack_kinds: Mapping[str, pack.Kind], kind_name: str) -> list[pack.Slot]:
    out: list[pack.Slot] = []
    cur: str | None = kind_name
    while cur:
        k = pack_kinds.get(cur)
        if k is None:
            break
        out.extend(k.slots.values())
        cur = k.parent
    return sorted(out, key=lambda s: s.name)


def _kind_has_slot(pack_kinds: Mapping[str, pack.Kind], kind_name: str, slot_name: str) -> bool:
    return any(s.name == slot_name for s in _all_model_slots(pack_kinds, kind_name))


def _nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def parse_safe_steps(
    pack_name: str,
    meta: dict,
    visible: tuple[str, ...],
    ports_by_pack: Mapping[str, Mapping[str, dict]],
    signatures: Mapping[str, Signature],
    pack_kinds: Mapping[str, pack.Kind],
) -> SafeStepsBindings:
    """Validate and resolve the optional `safe_steps` block in `pack.yaml`."""
    where = f"{pack_name}/pack.yaml: safe_steps"
    raw = meta.get("safe_steps")
    if raw is None:
        return SafeStepsBindings({}, {})
    if not isinstance(raw, dict):
        raise _compile_error(f"{where}: must be a mapping", where)
    unknown = sorted(set(raw) - {"readers", "atomic_effects"})
    if unknown:
        raise _compile_error(f"{where}: unknown members {', '.join(unknown)}", where)

    readers: dict[str, ReaderBinding] = {}
    if "readers" in raw:
        raw_readers = raw["readers"]
        if not isinstance(raw_readers, list):
            raise _compile_error(f"{where}.readers: must be a list", f"{where}.readers")
        for index, entry in enumerate(raw_readers):
            at = f"{where}.readers[{index}]"
            if not isinstance(entry, dict):
                raise _compile_error(f"{at}: must be a mapping", at)
            missing = sorted({"relation", "port", "scope", "targets"} - set(entry))
            extra = sorted(set(entry) - {"relation", "port", "scope", "targets"})
            if missing or extra:
                raise _compile_error(
                    f"{at}: needs exact keys relation, port, scope, targets",
                    at,
                )
            relation = entry["relation"]
            port_name = entry["port"]
            scope = entry["scope"]
            targets = entry["targets"]
            if not _nonempty_str(relation):
                raise _compile_error(f"{at}.relation: must be a nonempty relation name", at)
            if relation in readers:
                raise _compile_error(f"{at}: duplicate reader binding for relation {relation!r}", at)
            sig = signatures.get(relation)
            if sig is None or sig.owner not in visible:
                raise _compile_error(f"{at}.relation: {relation!r} is not a visible checked signature", at, "R040")
            if not _nonempty_str(port_name):
                raise _compile_error(f"{at}.port: must be a nonempty port name", at)
            _resolve_port(ports_by_pack, visible, port_name, expected_kind="in", where=at)

            if not isinstance(scope, list) or not scope or not all(_nonempty_str(c) for c in scope):
                raise _compile_error(f"{at}.scope: must be a nonempty list of column names", at)
            if len(set(scope)) != len(scope):
                raise _compile_error(f"{at}.scope: duplicate column in scope", at)
            sig_cols = {col for col, _, _ in sig.key}
            bad_cols = [c for c in scope if c not in sig_cols]
            if bad_cols:
                raise _compile_error(
                    f"{at}.scope: column(s) {', '.join(bad_cols)} not in signature of {relation!r}",
                    at,
                    "R003",
                )

            if not isinstance(targets, list) or not targets:
                raise _compile_error(f"{at}.targets: must be a nonempty list of targets", at)
            target_set: set[tuple[str, str | None]] = set()
            for t_idx, target in enumerate(targets):
                t_at = f"{at}.targets[{t_idx}]"
                if not isinstance(target, dict) or "kind" not in target or set(target) - {"kind", "slot"}:
                    raise _compile_error(f"{t_at}: needs 'kind' and optional 'slot'", t_at)
                kind_name = target["kind"]
                slot_name = target.get("slot")
                if not _nonempty_str(kind_name) or kind_name not in pack_kinds:
                    raise _compile_error(f"{t_at}: unknown kind {kind_name!r}", t_at, "R001")
                if "slot" in target:
                    if not _nonempty_str(slot_name) or not _kind_has_slot(pack_kinds, kind_name, slot_name):
                        raise _compile_error(f"{t_at}: {kind_name!r} has no slot {slot_name!r}", t_at, "R001")
                else:
                    slot_name = None
                pair = (kind_name, slot_name)
                if pair in target_set:
                    raise _compile_error(f"{t_at}: duplicate target {pair!r}", t_at)
                target_set.add(pair)

            readers[relation] = ReaderBinding(relation, port_name, tuple(scope), frozenset(target_set))

    atomic_effects: dict[str, AtomicEffectBinding] = {}
    if "atomic_effects" in raw:
        raw_effects = raw["atomic_effects"]
        if not isinstance(raw_effects, list):
            raise _compile_error(f"{where}.atomic_effects: must be a list", f"{where}.atomic_effects")
        for index, entry in enumerate(raw_effects):
            at = f"{where}.atomic_effects[{index}]"
            if not isinstance(entry, dict) or set(entry) != {"operation", "boundary", "evidence"}:
                raise _compile_error(f"{at}: needs exact keys operation, boundary, evidence", at)
            operation = entry["operation"]
            boundary = entry["boundary"]
            evidence = entry["evidence"]
            if not _nonempty_str(operation):
                raise _compile_error(f"{at}.operation: must be a nonempty operation name", at)
            if operation in atomic_effects:
                raise _compile_error(f"{at}: duplicate atomic_effects binding for {operation!r}", at)
            port_name, _ = resolve_effect_operation(ports_by_pack, visible, operation, at)
            if not _nonempty_str(boundary):
                raise _compile_error(f"{at}.boundary: must be a nonempty boundary name", at)
            if (not isinstance(evidence, dict) or set(evidence) != {"relation", "key"}
                    or not _nonempty_str(evidence["relation"]) or not _nonempty_str(evidence["key"])):
                raise _compile_error(f"{at}.evidence: must be a RowRef with relation and key", at)
            atomic_effects[operation] = AtomicEffectBinding(
                port_name, operation, boundary, {"relation": evidence["relation"], "key": evidence["key"]},
            )

    return SafeStepsBindings(readers, atomic_effects)


def validate_pack_bindings(
    pack_dir: Path,
    meta: dict,
    imported: Mapping[str, modules.Imported],
    pack_kinds: Mapping[str, pack.Kind],
) -> None:
    """Validate ports/*.yaml and safe_steps bindings when a pack has no native Rezono modules."""
    ports_by_pack = load_ports(pack_dir, meta, imported)
    root = str(meta["name"])
    visible = visible_packs(root, root, meta, imported)
    parse_safe_steps(root, meta, visible, ports_by_pack, {}, pack_kinds)
    for name, imp in sorted(imported.items()):
        imp_visible = visible_packs(name, root, meta, imported)
        parse_safe_steps(name, imp.meta, imp_visible, ports_by_pack, {}, pack_kinds)


def match_relation_name(owner: str, root: str, path: str, step_name: str, existing: Mapping[str, Any]) -> str:
    """Derive a deterministic, valid rule IR relation name for a step's positive match."""
    module_id = path.removeprefix(f"{rezono_module.DIR}/").removesuffix(".rezono")
    slug = re.sub(r"_+", "_", module_id.replace("/", "_").replace("-", "_")).strip("_")
    if owner == root:
        candidate = f"step_{slug}_{step_name}"
    else:
        owner_slug = re.sub(r"_+", "_", owner.replace("-", "_")).strip("_")
        candidate = f"step_{owner_slug}_{slug}_{step_name}"
    if not rules.NAME.match(candidate) or "__" in candidate:
        raise ValueError(f"Derived step match relation {candidate!r} is not a valid IR relation name")
    if candidate in existing:
        raise ValueError(f"Derived step match relation {candidate!r} collides with an existing relation")
    return candidate


def _compatible(schema: Schema, actual: str, expected: str, *, is_literal: bool = False) -> bool:
    if schema.assignable(actual, expected):
        return True
    if is_literal:
        if actual == "Int" and schema.scalar_storages.get(expected) == "integer":
            return True
        if actual == "Text" and schema.scalar_storages.get(expected) == "string":
            return True
    return False


def _type_operand(
    schema: Schema,
    source: Source,
    node: object,
    at: str,
    col_types: Mapping[str, str],
    *,
    allow_wildcard: bool = False,
    wildcard_type: str | None = None,
    allow_collection: bool = False,
) -> tuple[dict, str, set[str], bool]:
    from .native_rule_signatures import Refusal, literal_type

    if not isinstance(node, dict):
        raise Refusal("R049", "Step operand must be an expression node", at)
    if set(node) == {"wildcard"}:
        if not allow_wildcard or node["wildcard"] is not True or wildcard_type is None:
            raise Refusal("R049", "A wildcard is only allowed as a forbidden pattern column", at)
        return {"wildcard": True}, wildcard_type, set(), False
    if set(node) == {"path"}:
        path = node["path"]
        if not isinstance(path, list) or not path or not all(isinstance(p, str) for p in path):
            raise Refusal("R049", "Invalid path expression in step", at)
        root, *hops = path
        if root not in col_types:
            raise Refusal("R042", f"Unbound identifier {root!r} in step", at)
        current = col_types[root]
        many = False
        for i, hop in enumerate(hops):
            (_, current), many = schema.slot(current, hop, at)
            if many and i + 1 < len(hops):
                raise Refusal("R005", f"{hop!r} gives a set where a single subject is required", at)
        if many and not allow_collection:
            raise Refusal("R005", f"Multivalued path {'.'.join(path)!r} requires a collection target", at)
        return {"path": list(path)}, current, {root}, False
    if set(node) == {"neg"}:
        inner_expr, inner_type, refs, is_lit = _type_operand(schema, source, node["neg"], f"{at}/neg", col_types)
        if inner_type != "Int" and schema.scalar_storages.get(inner_type) != "integer":
            raise Refusal("R003", f"Expected whole number under negation, found {inner_type}", at)
        return {"neg": inner_expr}, inner_type, refs, is_lit
    if set(node) == {"lit"}:
        token = node["lit"]
        if not isinstance(token, str):
            raise Refusal("R049", "Invalid literal in step", at)
        resolved = literal_type(schema, source, token, at)
        if resolved is None:
            raise Refusal("R049", f"Literal {token!r} has no resolved schema type", at)
        expr_token = token
        if m := re.fullmatch(r"([A-Za-z0-9_.]+):`([^`]+)`", token):
            expr_token = f"{resolved}:`{m[2]}`"
        elif m := re.fullmatch(r'([A-Za-z0-9_.]+)(".*")', token):
            expr_token = f"{resolved}{m[2]}"
        return {"lit": expr_token}, resolved, set(), True
    if set(node) == {"arith"} and isinstance(node["arith"], list) and len(node["arith"]) == 3:
        op, left, right = node["arith"]
        left_e, left_t, left_r, _ = _type_operand(schema, source, left, f"{at}/arith/1", col_types)
        right_e, right_t, right_r, _ = _type_operand(schema, source, right, f"{at}/arith/2", col_types)
        for side_t, side_at in ((left_t, f"{at}/arith/1"), (right_t, f"{at}/arith/2")):
            if side_t != "Int" and schema.scalar_storages.get(side_t) != "integer":
                raise Refusal("R003", f"Expected whole number in arithmetic, found {side_t}", side_at)
        return {"arith": [op, left_e, right_e]}, "Int", left_r | right_r, False
    if set(node) == {"call"} and isinstance(node["call"], list) and len(node["call"]) == 2:
        name, args = node["call"]
        if name == "quotient" and isinstance(args, list) and len(args) == 2:
            left_e, left_t, left_r, _ = _type_operand(schema, source, args[0], f"{at}/call/1/0", col_types)
            right_e, right_t, right_r, _ = _type_operand(schema, source, args[1], f"{at}/call/1/1", col_types)
            for side_t, side_at in ((left_t, f"{at}/call/1/0"), (right_t, f"{at}/call/1/1")):
                if side_t != "Int" and schema.scalar_storages.get(side_t) != "integer":
                    raise Refusal("R003", f"Expected whole number in quotient, found {side_t}", side_at)
            return {"call": ["quotient", [left_e, right_e]]}, "Int", left_r | right_r, False
    raise Refusal("R049", "Unsupported expression in step operand", at)


def _lower_call(
    schema: Schema,
    source: Source,
    call_node: object,
    at: str,
    col_types: Mapping[str, str],
    signatures: dict[str, Signature],
    *,
    allow_wildcard: bool = False,
    require_signature: bool = False,
) -> tuple[pack.StepCall, set[str]]:
    from .native_rule_signatures import Refusal, call_of, signature_of

    if not isinstance(call_node, dict) or set(call_node) != {"call"}:
        raise Refusal("R049", "Expected a direct relation call", at)
    name, raw_args = call_node["call"]
    if require_signature:
        relation, sig = signature_of(source, name, signatures, at)
        expected_types = tuple(t for _, t, _ in sig.key)
    else:
        relation, expected_types = call_of(schema, source, name, signatures, at)
    if len(raw_args) != len(expected_types):
        raise Refusal("R041", f"{name!r} takes {len(expected_types)} columns, got {len(raw_args)}", at)

    operands: list[pack.StepOperand] = []
    referenced: set[str] = set()
    for index, (arg, expected) in enumerate(zip(raw_args, expected_types, strict=True)):
        arg_at = f"{at}/call/1/{index}"
        expr, actual, refs, is_lit = _type_operand(
            schema, source, arg, arg_at, col_types,
            allow_wildcard=allow_wildcard, wildcard_type=expected,
        )
        if expr != {"wildcard": True} and not _compatible(schema, actual, expected, is_literal=is_lit):
            raise Refusal("R003", f"Expected {expected}, found {actual}", arg_at)
        operands.append(pack.StepOperand(expr=expr, type=actual))
        referenced.update(refs)
    return pack.StepCall(relation=relation, operands=tuple(operands)), referenced


def _check_key_operand(
    schema: Schema,
    source: Source,
    key_node: object,
    at: str,
    col_types: Mapping[str, str],
    resolved_kind: str,
) -> pack.StepOperand:
    from .native_rule_signatures import Refusal

    key_expr, key_type, _, _ = _type_operand(schema, source, key_node, at, col_types)
    id_scalar = "Int" if schema.storage(resolved_kind, at) == "integer" else "Text"
    if not (schema.assignable(key_type, resolved_kind) or key_type == id_scalar):
        raise Refusal("R003", f"Expected key of {resolved_kind} ({id_scalar}), found {key_type}", at)
    return pack.StepOperand(expr=key_expr, type=key_type)


def _lower_change(
    schema: Schema,
    source: Source,
    change_node: object,
    at: str,
    col_types: Mapping[str, str],
    pack_kinds: Mapping[str, pack.Kind],
) -> tuple[pack.StepChange, list[pack.StepPostcondition]]:
    from .native_rule_signatures import Refusal

    if not isinstance(change_node, dict) or len(change_node) != 1:
        raise Refusal("R049", "Invalid step effect change", at)
    variant, body = next(iter(change_node.items()))
    body_at = f"{at}/{variant}"
    if variant not in {"insert_row", "retract_row", "set_slot", "retract_slot"} or not isinstance(body, dict):
        raise Refusal("R049", f"Unsupported step effect change {variant!r}", at)

    resolved_kind, _ = schema.type(source, body["kind"], body_at)
    if resolved_kind not in schema.classes or resolved_kind not in pack_kinds:
        raise Refusal("R003", f"{body['kind']!r} is not a modeled kind", body_at)
    model_kind = pack_kinds[resolved_kind]
    if model_kind.abstract:
        raise Refusal("R003", f"Abstract kind {resolved_kind!r} cannot be mutated by a step effect", body_at)

    key_op = _check_key_operand(schema, source, body["key"], f"{body_at}/key", col_types, resolved_kind)

    if variant == "insert_row":
        slots_by_name: dict[str, pack.StepOperand] = {}
        for s_idx, slot_entry in enumerate(body["slots"]):
            s_at = f"{body_at}/slots/{s_idx}"
            slot_name = slot_entry["name"]
            if model_kind.identifier and slot_name == model_kind.identifier:
                raise Refusal("R049", f"Cannot assign identifier slot {slot_name!r} inside insert_row", s_at)
            if slot_name in slots_by_name:
                raise Refusal("R040", f"Duplicate slot {slot_name!r} in insert_row", s_at)
            (_, expected_slot_type), many = schema.slot(resolved_kind, slot_name, s_at)
            val_expr, val_type, _, val_is_lit = _type_operand(
                schema, source, slot_entry["value"], f"{s_at}/value", col_types, allow_collection=many,
            )
            if not _compatible(schema, val_type, expected_slot_type, is_literal=val_is_lit):
                raise Refusal(
                    "R003",
                    f"Expected {expected_slot_type} for {resolved_kind}.{slot_name}, found {val_type}",
                    f"{s_at}/value",
                )
            slots_by_name[slot_name] = pack.StepOperand(expr=val_expr, type=val_type)

        # Require every required field, including inherited fields.
        missing_required = [
            s.name for s in _all_model_slots(pack_kinds, resolved_kind)
            if s.required and s.name not in slots_by_name
        ]
        if missing_required:
            raise Refusal(
                "R049",
                f"insert_row for {resolved_kind!r} is missing required slot(s): {', '.join(missing_required)}",
                body_at,
            )
        change = pack.StepChange(op="insert", kind=resolved_kind, key=key_op, values=slots_by_name)
        postconditions = [
            pack.StepPostcondition(
                subject=key_op,
                attribute=pack.StepAttribute(kind=resolved_kind, slot=None),
                state="present",
                value=key_op,
            ),
            *[
                pack.StepPostcondition(
                    subject=key_op,
                    attribute=pack.StepAttribute(kind=resolved_kind, slot=slot_name),
                    state="present",
                    value=val_op,
                )
                for slot_name, val_op in slots_by_name.items()
            ],
        ]
        return change, postconditions

    if variant == "retract_row":
        change = pack.StepChange(op="delete", kind=resolved_kind, key=key_op)
        postconditions = [
            pack.StepPostcondition(
                subject=key_op,
                attribute=pack.StepAttribute(kind=resolved_kind, slot=None),
                state="absent",
                value=None,
            ),
        ]
        return change, postconditions

    slot_name = body["slot"]
    if model_kind.identifier and slot_name == model_kind.identifier:
        raise Refusal("R049", f"Cannot mutate identifier slot {slot_name!r}", body_at)
    (_, expected_slot_type), many = schema.slot(resolved_kind, slot_name, body_at)

    if variant == "set_slot":
        val_expr, val_type, _, val_is_lit = _type_operand(
            schema, source, body["value"], f"{body_at}/value", col_types, allow_collection=many,
        )
        if not _compatible(schema, val_type, expected_slot_type, is_literal=val_is_lit):
            raise Refusal(
                "R003",
                f"Expected {expected_slot_type} for {resolved_kind}.{slot_name}, found {val_type}",
                f"{body_at}/value",
            )
        change = pack.StepChange(
            op="set", kind=resolved_kind, key=key_op, slot=slot_name,
            value=pack.StepOperand(expr=val_expr, type=val_type),
        )
        postconditions = [
            pack.StepPostcondition(
                subject=key_op,
                attribute=pack.StepAttribute(kind=resolved_kind, slot=slot_name),
                state="present",
                value=change.value,
            ),
        ]
        return change, postconditions

    # retract_slot
    change = pack.StepChange(op="unset", kind=resolved_kind, key=key_op, slot=slot_name)
    postconditions = [
        pack.StepPostcondition(
            subject=key_op,
            attribute=pack.StepAttribute(kind=resolved_kind, slot=slot_name),
            state="absent",
            value=None,
        ),
    ]
    return change, postconditions


def lower_steps(
    meta: dict,
    pack_dir: Path | None,
    imported: Mapping[str, modules.Imported],
    schema: Schema,
    signatures: dict[str, Signature],
    step_decls: list[tuple[Source, str, dict, str, tuple[tuple[str, str, str], ...]]],
    pack_kinds: Mapping[str, pack.Kind] | None,
    errors: list[Diagnostic],
) -> tuple[pack.CompiledStep, ...]:
    """Validate port/safe_steps bindings and lower all step declarations into CompiledStep entries."""
    from .native_rule_signatures import Refusal

    root = str(meta["name"])
    ports_by_pack: dict[str, dict[str, dict]] = {}
    bindings_by_pack: dict[str, SafeStepsBindings] = {}
    if pack_dir is not None:
        try:
            ports_by_pack = load_ports(pack_dir, meta, imported)
            kinds = pack_kinds or {}
            root_vis = visible_packs(root, root, meta, imported)
            bindings_by_pack[root] = parse_safe_steps(root, meta, root_vis, ports_by_pack, signatures, kinds)
            for imp_name, imp in sorted(imported.items()):
                imp_vis = visible_packs(imp_name, root, meta, imported)
                bindings_by_pack[imp_name] = parse_safe_steps(
                    imp_name, imp.meta, imp_vis, ports_by_pack, signatures, kinds,
                )
        except pack.CompileError as error:
            errors.extend(error.diagnostics)
            return ()

    if not step_decls:
        return ()
    if pack_dir is None or pack_kinds is None:
        errors.append(Diagnostic("R049", "Step lowering requires pack directory and schema kinds"))
        return ()

    compiled: list[pack.CompiledStep] = []
    for source, at, decl, match_relation, step_cols in step_decls:
        try:
            col_types = {name: logical for name, logical, _ in step_cols}

            # 1. Lower forbid blockers.
            blockers: list[pack.StepBlocker] = []
            raw_forbid = decl.get("forbid")
            if raw_forbid is not None and (not isinstance(raw_forbid, list) or not raw_forbid):
                raise Refusal("R048", "forbid must be a nonempty list", f"{at}/forbid")
            for f_idx, forbid in enumerate(raw_forbid or ()):
                f_at = f"{at}/forbid/{f_idx}"
                if not isinstance(forbid, dict) or set(forbid) != {"pattern", "within"}:
                    raise Refusal("R048", "Each forbid clause requires pattern and within", f_at)
                pattern_call, pattern_cols = _lower_call(
                    schema, source, forbid["pattern"], f"{f_at}/pattern", col_types, signatures, allow_wildcard=True,
                )
                coverage_call, coverage_cols = _lower_call(
                    schema, source, forbid["within"], f"{f_at}/within", col_types, signatures, allow_wildcard=False,
                )
                if pattern_cols and pattern_cols.isdisjoint(coverage_cols):
                    raise Refusal(
                        "R049",
                        "Forbid coverage call is unrelated to the forbidden pattern keys",
                        f"{f_at}/within",
                    )
                blockers.append(pack.StepBlocker(pattern=pattern_call, coverage=coverage_call))

            # 2. Resolve effect operation and atomic boundary.
            visible = visible_packs(source.owner, root, meta, imported)
            owner_bindings = bindings_by_pack[source.owner]
            effect_at = f"{at}/effect"
            effect_node = decl["effect"]
            if (not isinstance(effect_node, dict) or set(effect_node) != {"operation", "changes"}
                    or not _nonempty_str(effect_node["operation"])
                    or not isinstance(effect_node["changes"], list) or not effect_node["changes"]):
                raise Refusal("R048", "Step effect requires an operation name and one or more changes", effect_at)
            op_name = effect_node["operation"]
            try:
                port_name, apply_name = resolve_effect_operation(
                    ports_by_pack, visible, op_name, f"{source.file}#{effect_at}",
                )
            except pack.CompileError as error:
                raise Refusal("R046", str(error.diagnostics[0].message), effect_at) from None

            raw_changes = decl["effect"]["changes"]
            atomic_binding = owner_bindings.atomic_effects.get(apply_name)
            if len(raw_changes) > 1 and atomic_binding is None:
                raise Refusal(
                    "R049",
                    f"Multi-write step effect {apply_name!r} requires a safe_steps.atomic_effects binding in pack.yaml",
                    effect_at,
                )
            operation = pack.StepOperation(
                port=port_name,
                apply=apply_name,
                boundary=atomic_binding.boundary if atomic_binding else None,
                evidence=dict(atomic_binding.evidence) if atomic_binding else None,
            )

            # 3. Lower effect changes, detect conflicting/repeated writes, and derive postconditions.
            changes: list[pack.StepChange] = []
            postconditions: list[pack.StepPostcondition] = []
            row_writes: set[tuple[str, str]] = set()
            slot_writes: set[tuple[str, str, str]] = set()
            for c_idx, raw_change in enumerate(raw_changes):
                c_at = f"{effect_at}/changes/{c_idx}"
                change, posts = _lower_change(schema, source, raw_change, c_at, col_types, pack_kinds)
                key_canon = json.dumps(change.key.expr, sort_keys=True, separators=(",", ":"))
                row_key = (change.kind, key_canon)
                if change.op in ("insert", "delete"):
                    if row_key in row_writes or any(rk[:2] == row_key for rk in slot_writes):
                        raise Refusal("R049", f"Conflicting or repeated write on {change.kind}", c_at)
                    row_writes.add(row_key)
                else:
                    assert change.slot is not None
                    slot_key = (change.kind, key_canon, change.slot)
                    if row_key in row_writes or slot_key in slot_writes:
                        raise Refusal("R049", f"Conflicting or repeated write on {change.kind}.{change.slot}", c_at)
                    slot_writes.add(slot_key)
                changes.append(change)
                postconditions.extend(posts)

            # 4. Lower confirmation reader, token, and verify reader target coverage.
            confirm_at = f"{at}/confirm"
            confirm_node = decl["confirm"]
            if not isinstance(confirm_node, dict) or set(confirm_node) != {"reader", "token"}:
                raise Refusal("R048", "Step confirm requires reader and token", confirm_at)
            reader_call, _ = _lower_call(
                schema, source, confirm_node["reader"], f"{confirm_at}/reader", col_types, signatures,
                allow_wildcard=False, require_signature=True,
            )
            reader_sig = signatures[reader_call.relation]
            reader_binding = owner_bindings.readers.get(reader_call.relation)
            if reader_binding is None and reader_sig.owner in bindings_by_pack:
                reader_binding = bindings_by_pack[reader_sig.owner].readers.get(reader_call.relation)
            if reader_binding is None:
                raise Refusal(
                    "R049",
                    f"Confirmation reader {reader_call.relation!r} has no safe_steps.readers binding in pack.yaml",
                    f"{confirm_at}/reader",
                )
            for post in postconditions:
                target = (post.attribute.kind, post.attribute.slot)
                if target not in reader_binding.targets:
                    attr_label = f"{target[0]}.{target[1]}" if target[1] else target[0]
                    raise Refusal(
                        "R049",
                        f"Confirmation reader {reader_call.relation!r} does not cover postcondition target {attr_label!r}",
                        f"{confirm_at}/reader",
                    )

            tok_expr, tok_type, _, _ = _type_operand(
                schema, source, decl["confirm"]["token"], f"{confirm_at}/token", col_types,
            )
            confirmation = pack.StepConfirmation(
                reader=pack.StepReader(port=reader_binding.port, call=reader_call, scope=reader_binding.scope),
                token=pack.StepOperand(expr=tok_expr, type=tok_type),
                postconditions=tuple(postconditions),
            )

            module_id = source.path.removeprefix(f"{rezono_module.DIR}/").removesuffix(".rezono")
            compiled.append(pack.CompiledStep(
                id=(source.owner, module_id, decl["step"]),
                match_relation=match_relation,
                columns=step_cols,
                blockers=tuple(blockers),
                operation=operation,
                changes=tuple(changes),
                confirmation=confirmation,
            ))
        except Refusal as error:
            errors.append(source.diagnose(error))
    return tuple(compiled)
