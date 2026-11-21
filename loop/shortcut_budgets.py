"""Thin readers and packs/std-budget adapter for the three monotonically shrinking shortcut budgets.

See decisions/no-green-by-cheapest-route.md and decisions/tooling-does-not-decide.md section 2.1:
- `day_number_fields`: integer day-number fields (`*_day` or integer `day` slots) in pack schemas.
- `duplicate_source_blocks`: repeated identical source metadata blocks within a `.sources.yaml` file.
- `rezono_pack_dl_regression`: `.dl` files under `rules/` in packs that already have `rezono/**/*.rezono`,
  paired with visible off-board tracking of `.dl` files in packs without a `rezono/` module.

All pass/fail budget verdicts (`budget_raised`, `budget_exceeded`, `budget_ratchet_violation`,
`budget_missing_head`), `budget_within`, and advisory `budget_slack` are derived strictly by
evaluating `packs/std-budget` (fail-closed, no Python decision fallback).
"""

from __future__ import annotations

import argparse
from collections import Counter
import datetime
import functools
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
STD_BUDGET_DIR = ROOT / "packs" / "std-budget"
BUDGET_PATH = "loop/shortcut-budget.json"

BUDGET_NAMES = (
    "day_number_fields",
    "duplicate_source_blocks",
    "rezono_pack_dl_regression",
)
BLOCKING_RELATIONS = (
    "budget_raised",
    "budget_exceeded",
    "budget_ratchet_violation",
    "budget_missing_head",
)
RESULT_RELATIONS = (*BLOCKING_RELATIONS, "budget_slack", "budget_within")

PACK_TOP_DIRS = ("build", "examples", "packs", "run")
EXCLUDED_DIR_NAMES = frozenset({
    "test",
    "tests",
    "fixture",
    "fixtures",
    "candidate",
    "node_modules",
    "__pycache__",
})
INTEGER_RANGES = frozenset({"integer", "int", "number"})


def _is_excluded_path(rel_parts: tuple[str, ...]) -> bool:
    return any(part in EXCLUDED_DIR_NAMES or part.startswith(".") for part in rel_parts)


def _iter_pack_dirs(root: Path, *, include_rezono_only: bool = False) -> list[Path]:
    """Return sorted pack directories under PACK_TOP_DIRS excluding test fixtures and candidate/."""
    found: dict[str, Path] = {}
    for top in PACK_TOP_DIRS:
        base = root / top
        if not base.is_dir():
            continue
        for pack_yaml in sorted(base.rglob("pack.yaml")):
            pack_dir = pack_yaml.parent
            rel = pack_dir.relative_to(root)
            if _is_excluded_path(rel.parts):
                continue
            found[rel.as_posix()] = pack_dir
        if include_rezono_only:
            for rezono_file in sorted(base.rglob("*.rezono")):
                rel_file = rezono_file.relative_to(root)
                if _is_excluded_path(rel_file.parts):
                    continue
                if "rezono" not in rel_file.parts:
                    continue
                idx = rel_file.parts.index("rezono")
                if idx == 0:
                    continue
                pack_dir = root.joinpath(*rel_file.parts[:idx])
                rel_pack = pack_dir.relative_to(root)
                if _is_excluded_path(rel_pack.parts):
                    continue
                found.setdefault(rel_pack.as_posix(), pack_dir)
    return [found[key] for key in sorted(found)]


def _is_day_number_field(name: str, range_name: Any, integer_types: frozenset[str] | set[str] = frozenset()) -> bool:
    """Whether a schema slot is an integer day-number slot (`day` or `*_day`)."""
    lower_name = name.strip().lower()
    if lower_name != "day" and not lower_name.endswith("_day"):
        return False
    if not isinstance(range_name, str):
        return False
    raw = range_name.strip()
    local = raw.partition(".")[2] if "." in raw else raw
    if local in integer_types:
        return True
    return local.lower() in INTEGER_RANGES


def _read_pack_schema_models(pack_dir: Path) -> tuple[list[Any], list[dict[str, Any]], dict[str, str], set[str]]:
    """Read a pack's LinkML schemas and Rezono module forms via `rezono_compiler` (fail-closed)."""
    from rezono_compiler import rezono_module
    from rezono_compiler.schemaview import SchemaView

    schemas: list[Any] = []
    schema_dir = pack_dir / "schema"
    if schema_dir.is_dir():
        for yaml_path in sorted(schema_dir.rglob("*.yaml")):
            if _is_excluded_path(yaml_path.relative_to(pack_dir).parts):
                continue
            try:
                sv = SchemaView(yaml_path)
                schema = sv.schema
            except Exception as exc:
                raise RuntimeError(f"failed to read LinkML schema {yaml_path}: {exc}") from exc
            schemas.append(schema)

    forms: list[dict[str, Any]] = []
    rezono_dir = pack_dir / "rezono"
    if rezono_dir.is_dir():
        for rezono_path in sorted(rezono_dir.rglob("*.rezono")):
            if _is_excluded_path(rezono_path.relative_to(pack_dir).parts):
                continue
            rel_mod = rezono_path.relative_to(pack_dir).as_posix()
            rel_form = rezono_path.relative_to(pack_dir).with_suffix(".json").as_posix()
            decl = rezono_module.Declared(rel_mod, rel_form, "facts")
            errors: list[str] = []
            form = rezono_module.authored_form(pack_dir, decl, rezono_path.read_bytes(), errors)
            if form is None:
                detail = "; ".join(str(err) for err in errors) or "module reader failed"
                raise RuntimeError(f"failed to parse Rezono module {rezono_path}: {detail}")
            forms.append(form)

    type_bases: dict[str, str] = {}
    declared_names: set[str] = set()
    for schema in schemas:
        for tname, tdef in (schema.types or {}).items():
            name_str = str(tname)
            declared_names.add(name_str)
            if tdef.typeof:
                type_bases[name_str] = str(tdef.typeof)
        declared_names.update(str(cname) for cname in (schema.classes or {}))
        declared_names.update(str(ename) for ename in (schema.enums or {}))
    for form in forms:
        declared_names.update(rezono_module.names(form))
        type_bases.update(rezono_module.type_bases(form))

    return schemas, forms, type_bases, declared_names


def _imported_pack_dirs(pack_dir: Path, root_resolved: Path) -> list[Path]:
    """Return resolvable imported pack directories declared in `pack.yaml` (fail-closed)."""
    pack_yaml = pack_dir / "pack.yaml"
    if not pack_yaml.is_file():
        return []
    try:
        meta = yaml.safe_load(pack_yaml.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RuntimeError(f"failed to read pack manifest {pack_yaml}: {exc}") from exc
    if not isinstance(meta, dict):
        raise RuntimeError(f"invalid pack manifest {pack_yaml}: expected a YAML mapping")
    imports = meta.get("imports")
    if imports is None:
        return []
    if not isinstance(imports, list):
        raise RuntimeError(f"invalid pack manifest {pack_yaml}: imports must be a list")
    out: list[Path] = []
    for entry in imports:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise RuntimeError(f"invalid pack manifest {pack_yaml}: each import entry must declare a string path")
        candidate = (pack_dir / entry["path"]).resolve()
        if candidate.is_dir() and candidate.is_relative_to(root_resolved):
            out.append(candidate)
    return out


def _count_schema_day_number_fields(schema: Any, integer_types: set[str]) -> int:
    default_range = schema.default_range or "string"
    top_slots = schema.slots or {}
    classes = schema.classes or {}

    count = 0
    used_top_slots: set[str] = set()
    for class_def in classes.values():
        attributes = class_def.attributes or {}
        slot_usage = class_def.slot_usage or {}

        for attr_name, attr_def in attributes.items():
            rng = attr_def.range
            if rng is None and attr_name in top_slots:
                rng = top_slots[attr_name].range
            if rng is None:
                rng = default_range
            if _is_day_number_field(str(attr_name), rng, integer_types):
                count += 1

        for slot_name in (class_def.slots or []):
            if slot_name in attributes:
                continue
            used_top_slots.add(slot_name)
            rng = slot_usage[slot_name].range if slot_name in slot_usage else None
            if rng is None and slot_name in top_slots:
                rng = top_slots[slot_name].range
            if rng is None:
                rng = default_range
            if _is_day_number_field(str(slot_name), rng, integer_types):
                count += 1

    for slot_name, slot_def in top_slots.items():
        if slot_name in used_top_slots:
            continue
        rng = slot_def.range if slot_def.range is not None else default_range
        if _is_day_number_field(str(slot_name), rng, integer_types):
            count += 1

    return count


def _count_rezono_form_day_number_fields(
    form: dict[str, Any],
    declared_names: set[str],
    integer_types: set[str],
) -> int:
    from rezono_compiler import rezono_slot

    def _resolve_range(type_name: str) -> str:
        if "." in type_name:
            return type_name.partition(".")[2]
        return rezono_slot.builtin_range(type_name, type_name in declared_names) or type_name

    count = 0
    for decl in form["module"]["decls"]:
        if not isinstance(decl, dict):
            continue
        if "kind" in decl:
            for slot in decl.get("slots") or []:
                if not isinstance(slot, dict):
                    continue
                sname, stype = slot.get("slot"), slot.get("type")
                if isinstance(sname, str) and isinstance(stype, str):
                    if _is_day_number_field(sname, _resolve_range(stype), integer_types):
                        count += 1
            for derived in decl.get("derived") or []:
                if not isinstance(derived, dict):
                    continue
                dname, dtype = derived.get("derived"), derived.get("type")
                if isinstance(dname, str) and isinstance(dtype, str):
                    if _is_day_number_field(dname, _resolve_range(dtype), integer_types):
                        count += 1
        elif "extend" in decl:
            for derived in decl.get("derived") or []:
                if not isinstance(derived, dict):
                    continue
                dname, dtype = derived.get("derived"), derived.get("type")
                if isinstance(dname, str) and isinstance(dtype, str):
                    if _is_day_number_field(dname, _resolve_range(dtype), integer_types):
                        count += 1
    return count


def count_day_number_fields(root: Path) -> dict[str, int]:
    """Count integer day-number schema fields per pack under `root` via `rezono_compiler`."""
    from rezono_compiler import rezono_module

    root = Path(root)
    root_resolved = root.resolve()
    pack_dirs = _iter_pack_dirs(root, include_rezono_only=True)
    loaded: dict[Path, tuple[list[Any], list[dict[str, Any]], dict[str, str], set[str]]] = {}

    def _get_loaded(pdir: Path) -> tuple[list[Any], list[dict[str, Any]], dict[str, str], set[str]]:
        key = pdir.resolve()
        if key not in loaded:
            loaded[key] = _read_pack_schema_models(pdir)
        return loaded[key]

    def _collect_type_bases(pdir: Path, visited: set[Path]) -> dict[str, str]:
        key = pdir.resolve()
        if key in visited:
            return {}
        visited.add(key)
        combined: dict[str, str] = {}
        for imp_dir in _imported_pack_dirs(pdir, root_resolved):
            combined.update(_collect_type_bases(imp_dir, visited))
        _, _, own_bases, _ = _get_loaded(pdir)
        combined.update(own_bases)
        return combined

    counts: dict[str, int] = {}
    for pack_dir in pack_dirs:
        schemas, forms, _, declared_names = _get_loaded(pack_dir)
        type_bases = _collect_type_bases(pack_dir, set())
        integer_types = rezono_module.integer_type_names(type_bases, type_bases, INTEGER_RANGES)

        total = sum(_count_schema_day_number_fields(schema, integer_types) for schema in schemas)
        total += sum(
            _count_rezono_form_day_number_fields(form, declared_names, integer_types)
            for form in forms
        )
        if total > 0:
            counts[pack_dir.relative_to(root).as_posix()] = total
    return dict(sorted(counts.items()))


def _canonicalize_yaml_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _canonicalize_yaml_value(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, list):
        return [_canonicalize_yaml_value(item) for item in value]
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return value


def _count_file_duplicate_source_blocks(path: Path) -> int:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return 0
    blocks: list[str] = []
    default_block = data.get("default")
    if isinstance(default_block, dict) and default_block:
        blocks.append(json.dumps(_canonicalize_yaml_value(default_block), sort_keys=True, ensure_ascii=False))
    records = data.get("records")
    if isinstance(records, list):
        for entry in records:
            if not isinstance(entry, dict):
                continue
            stripped = {k: v for k, v in entry.items() if k != "of"}
            if stripped:
                blocks.append(json.dumps(_canonicalize_yaml_value(stripped), sort_keys=True, ensure_ascii=False))
    freq = Counter(blocks)
    return sum(n - 1 for n in freq.values() if n > 1)


def count_duplicate_source_blocks(root: Path) -> dict[str, int]:
    """Count repeated identical source metadata blocks per `.sources.yaml` file under `root`."""
    root = Path(root)
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("*.sources.yaml")):
        rel = path.relative_to(root)
        if _is_excluded_path(rel.parts):
            continue
        dups = _count_file_duplicate_source_blocks(path)
        if dups > 0:
            counts[rel.as_posix()] = dups
    return dict(sorted(counts.items()))


def count_rezono_pack_dl_files(root: Path) -> tuple[dict[str, int], dict[str, int]]:
    """Count `.dl` files under `rules/` per pack, split into `(regression_counts, offboard_counts)`.

    Packs that already contain at least one `rezono/**/*.rezono` module are reported in
    `regression_counts` (governed by the shrinking `rezono_pack_dl_regression` budget). Packs
    without any `rezono/` module are reported visibly in `offboard_counts`.
    """
    root = Path(root)
    regression: dict[str, int] = {}
    offboard: dict[str, int] = {}

    for pack_dir in _iter_pack_dirs(root, include_rezono_only=False):
        rules_dir = pack_dir / "rules"
        if not rules_dir.is_dir():
            continue
        dl_files = [
            p for p in sorted(rules_dir.rglob("*.dl"))
            if not _is_excluded_path(p.relative_to(pack_dir).parts)
        ]
        if not dl_files:
            continue
        rezono_dir = pack_dir / "rezono"
        has_rezono = rezono_dir.is_dir() and any(
            not _is_excluded_path(p.relative_to(pack_dir).parts)
            for p in rezono_dir.rglob("*.rezono")
        )
        key = pack_dir.relative_to(root).as_posix()
        if has_rezono:
            regression[key] = len(dl_files)
        else:
            offboard[key] = len(dl_files)

    return dict(sorted(regression.items())), dict(sorted(offboard.items()))


@functools.lru_cache(maxsize=1)
def _load_std_budget():
    """Compile and cache `packs/std-budget` (fail-closed; cleared via cache_clear in tests)."""
    from rezono_compiler import pack, rules

    model = pack.read(STD_BUDGET_DIR)
    program = rules.load(model.rules)
    missing = set(RESULT_RELATIONS) - set(program.derived())
    if missing:
        raise RuntimeError(f"packs/std-budget does not derive required relations: {sorted(missing)}")
    return model, program


def _validate_count_map(label: str, values: dict[str, int]) -> None:
    if not isinstance(values, dict):
        raise ValueError(f"{label} must be a dict mapping cell names to non-negative integers")
    for cell, count in values.items():
        if not isinstance(cell, str) or not cell:
            raise ValueError(f"{label} cell key must be a non-empty string, got {cell!r}")
        if type(count) is not int or count < 0:
            raise ValueError(f"{label}[{cell!r}] must be a non-negative int, got {count!r}")


def evaluate_shortcut_budget(
    budget_name: str,
    base_ceilings: dict[str, int],
    head_ceilings: dict[str, int],
    base_observed: dict[str, int],
    head_observed: dict[str, int],
) -> dict[str, set[tuple[str, str]]]:
    """Evaluate a shrink-only shortcut budget strictly through `packs/std-budget` (fail-closed)."""
    if not isinstance(budget_name, str) or not budget_name:
        raise ValueError(f"budget_name must be a non-empty string, got {budget_name!r}")
    _validate_count_map("base_ceilings", base_ceilings)
    _validate_count_map("head_ceilings", head_ceilings)
    _validate_count_map("base_observed", base_observed)
    _validate_count_map("head_observed", head_observed)

    from rezono_compiler import batch, facts, scenarios

    model, program = _load_std_budget()

    entries = [
        {"id": f"ce-base-{idx}", "budget": budget_name, "cell": cell, "ceiling": ceiling, "revision": "base"}
        for idx, (cell, ceiling) in enumerate(sorted(base_ceilings.items()))
    ] + [
        {"id": f"ce-head-{idx}", "budget": budget_name, "cell": cell, "ceiling": ceiling, "revision": "head"}
        for idx, (cell, ceiling) in enumerate(sorted(head_ceilings.items()))
    ]
    readings = [
        {"id": f"rd-base-{idx}", "budget": budget_name, "cell": cell, "observed": observed, "revision": "base"}
        for idx, (cell, observed) in enumerate(sorted(base_observed.items()))
    ] + [
        {"id": f"rd-head-{idx}", "budget": budget_name, "cell": cell, "observed": observed, "revision": "head"}
        for idx, (cell, observed) in enumerate(sorted(head_observed.items()))
    ]

    admitted = facts.rows_of(model, {"budget_entry": entries, "budget_reading": readings})
    inputs = scenarios.rule_rows(model, program, admitted)
    with batch.connect(program, inputs) as con:
        batch.compute(con, program)
        rows = batch.read(con, program, list(RESULT_RELATIONS))
    return {rel: set(rows.get(rel, ())) for rel in RESULT_RELATIONS}


def _parse_budget_section(
    raw_text: str,
    budget_name: str,
    *,
    strict_format: bool,
) -> dict[str, int]:
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"{BUDGET_PATH} must be a JSON object")
    if strict_format and raw_text != json.dumps(parsed, indent=2, sort_keys=True) + "\n":
        raise ValueError(f"{BUDGET_PATH} must be canonical sorted JSON with 2-space indent and trailing LF")
    if budget_name not in parsed or not isinstance(parsed[budget_name], dict):
        raise ValueError(f"{BUDGET_PATH} is missing object section {budget_name!r}")
    section = parsed[budget_name]
    result: dict[str, int] = {}
    for cell, ceiling in section.items():
        if not isinstance(cell, str) or not cell:
            raise ValueError(f"{BUDGET_PATH}[{budget_name!r}] has invalid cell key {cell!r}")
        if type(ceiling) is not int or ceiling <= 0:
            raise ValueError(f"{BUDGET_PATH}[{budget_name!r}][{cell!r}] must be a positive integer")
        result[cell] = ceiling
    return result


def _is_relevant_git_path(rel_posix: str, budget_name: str) -> bool:
    if rel_posix == BUDGET_PATH:
        return True
    p = PurePosixPath(rel_posix)
    if _is_excluded_path(p.parts):
        return False
    if budget_name == "duplicate_source_blocks":
        return p.name.endswith(".sources.yaml")
    if not p.parts or p.parts[0] not in PACK_TOP_DIRS:
        return False
    if p.name == "pack.yaml":
        return True
    if budget_name == "day_number_fields":
        return (
            (p.suffix == ".yaml" and "schema" in p.parts)
            or (p.suffix == ".rezono" and "rezono" in p.parts)
        )
    if budget_name == "rezono_pack_dl_regression":
        return (
            (p.suffix == ".dl" and "rules" in p.parts)
            or (p.suffix == ".rezono" and "rezono" in p.parts)
        )
    return False


def _materialize_git_tree(repo_root: Path, rev: str, budget_name: str, dest: Path) -> bool:
    """Materialize the files relevant to `budget_name` at git revision `rev` into `dest`.

    Returns whether `BUDGET_PATH` exists at `rev`.
    """
    tree_out = subprocess.check_output(
        ["git", "ls-tree", "-r", "-z", "--full-tree", rev],
        cwd=repo_root,
    )
    wanted: list[tuple[str, str]] = []
    has_budget_file = False
    for entry in filter(None, tree_out.split(b"\0")):
        meta, raw_path = entry.split(b"\t", 1)
        mode, obj_type, oid = meta.decode("ascii").split()
        if obj_type != "blob" or mode not in {"100644", "100755"}:
            continue
        rel_posix = raw_path.decode("utf-8", "surrogateescape")
        if _is_relevant_git_path(rel_posix, budget_name):
            wanted.append((rel_posix, oid))
            if rel_posix == BUDGET_PATH:
                has_budget_file = True

    if not wanted:
        return False

    batch_input = b"\n".join(oid.encode("ascii") for _, oid in wanted) + b"\n"
    batch_out = subprocess.check_output(
        ["git", "cat-file", "--batch"],
        cwd=repo_root,
        input=batch_input,
    )

    pos = 0
    for rel_posix, expected_oid in wanted:
        nl = batch_out.index(b"\n", pos)
        header = batch_out[pos:nl].decode("ascii")
        parts = header.split()
        if len(parts) != 3 or parts[0] != expected_oid or parts[1] != "blob":
            raise RuntimeError(f"unexpected git cat-file header for {rev}:{rel_posix}: {header!r}")
        size = int(parts[2])
        start = nl + 1
        end = start + size
        blob = batch_out[start:end]
        pos = end + 1

        target = dest.joinpath(*rel_posix.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)

    return has_budget_file


def _count_for_budget(budget_name: str, root: Path) -> dict[str, int]:
    if budget_name == "day_number_fields":
        return count_day_number_fields(root)
    if budget_name == "duplicate_source_blocks":
        return count_duplicate_source_blocks(root)
    if budget_name == "rezono_pack_dl_regression":
        regression, _ = count_rezono_pack_dl_files(root)
        return regression
    raise ValueError(f"unknown shortcut budget: {budget_name!r}")


def check_shortcut_budget(
    budget_name: str,
    root: Path,
    base: str,
) -> list[str]:
    """Verify `budget_name` on `root` against git revision `base` via `packs/std-budget` (fail-closed)."""
    if budget_name not in BUDGET_NAMES:
        raise ValueError(f"unknown shortcut budget: {budget_name!r}")
    if not isinstance(base, str) or not base.strip():
        raise ValueError("base must be a non-empty git revision")
    base_rev = base.strip()

    root = Path(root)
    budget_file = root / BUDGET_PATH
    if not budget_file.is_file():
        return [f"missing budget file {BUDGET_PATH}"]
    try:
        head_ceilings = _parse_budget_section(
            budget_file.read_text(encoding="utf-8"),
            budget_name,
            strict_format=True,
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        return [f"invalid budget file {BUDGET_PATH}: {exc}"]

    head_observed = _count_for_budget(budget_name, root)

    with tempfile.TemporaryDirectory(prefix="shortcut-budget-base-") as tmp:
        base_dir = Path(tmp)
        has_base_budget = _materialize_git_tree(root, base_rev, budget_name, base_dir)
        base_observed = _count_for_budget(budget_name, base_dir)
        if not has_base_budget:
            return [f"missing base budget file {base_rev}:{BUDGET_PATH}"]
        try:
            base_ceilings = _parse_budget_section(
                (base_dir / BUDGET_PATH).read_text(encoding="utf-8"),
                budget_name,
                strict_format=False,
            )
        except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
            return [f"invalid base budget file {base_rev}:{BUDGET_PATH}: {exc}"]

    tracked_cells = sorted(
        set(base_ceilings) | set(head_ceilings) | set(base_observed) | set(head_observed)
    )
    measured_head_observed = {cell: head_observed.get(cell, 0) for cell in tracked_cells}

    verdict = evaluate_shortcut_budget(
        budget_name,
        base_ceilings=base_ceilings,
        head_ceilings=head_ceilings,
        base_observed=base_observed,
        head_observed=measured_head_observed,
    )

    findings: list[str] = []
    for budget, cell in sorted(verdict["budget_raised"]):
        findings.append(
            f"budget_raised: {budget} {cell}: "
            f"head_ceiling={head_ceilings.get(cell, 0)} > base_ceiling={base_ceilings.get(cell, 0)}"
        )
    for budget, cell in sorted(verdict["budget_exceeded"]):
        findings.append(
            f"budget_exceeded: {budget} {cell}: "
            f"observed={measured_head_observed.get(cell, 0)} > ceiling={head_ceilings.get(cell, 0)}"
        )
    for budget, cell in sorted(verdict["budget_ratchet_violation"]):
        findings.append(
            f"budget_ratchet_violation: {budget} {cell}: "
            f"head_observed={measured_head_observed.get(cell, 0)} > base_observed={base_observed.get(cell, 0)}"
        )
    for budget, cell in sorted(verdict["budget_missing_head"]):
        findings.append(
            f"budget_missing_head: {budget} {cell}: missing head observation"
        )
    for cell in tracked_cells:
        if (budget_name, cell) not in verdict["budget_within"] and not any(
            (budget_name, cell) in verdict[rel] for rel in BLOCKING_RELATIONS
        ):
            findings.append(
                f"budget_not_within: {budget_name} {cell}: cell did not satisfy budget_within"
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--base", required=True)
    parser.add_argument("--budget", choices=BUDGET_NAMES, action="append")
    args = parser.parse_args(argv)
    if not isinstance(args.base, str) or not args.base.strip():
        parser.error("--base must be a non-empty git revision")

    selected = args.budget or list(BUDGET_NAMES)
    failed = False
    for name in selected:
        findings = check_shortcut_budget(name, args.root, base=args.base)
        for line in findings:
            print(line)
        failed = failed or bool(findings)
    if "rezono_pack_dl_regression" in selected:
        _, offboard = count_rezono_pack_dl_files(args.root)
        print(f"offboard_dl_packs={len(offboard)} offboard_dl_files={sum(offboard.values())}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
