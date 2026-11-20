"""Turn a fact file (records per kind) into rows per engine table.

What a valid fact is lives in one place, admission (rezono_admission, ruling 2 of 11-11-2026): the rows of a fact
document, every refusal, and the observer that tells the sources where each row comes from. Here are what the
compiler adds around it: the schema it judges against, built from the pack as the schema bundle states it; the
refusals as one LoadError; the row hashes of sealed kinds, which the bundle does not state yet; and
the files and their source sidecars.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml
from rezono_admission import Schema
from rezono_admission import rows as admit

from . import rezono_module, seal, spans, strict_yaml, types
from .diagnostics import Diagnosed, Diagnostic
from .pack import Pack, snake

ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
PLACE = re.compile(r"([^.\[\]]+)|\[([0-9]+)\]")  # admission's place: names, and positions from 1 in brackets
PYTHON_TYPES = {"VARCHAR": str, "BIGINT": int, "BOOLEAN": bool, "DATE": datetime.date}
SQL_TYPES = {"text": "VARCHAR", "enum": "VARCHAR", "integer": "BIGINT", "boolean": "BOOLEAN", "date": "DATE"}
FORMAT = "rezono.schema-bundle/1"
DATASET_FORMAT = rezono_module.DATASET_FORMAT
FACT_ROW_KEYS = frozenset({"fact", "id", "valid", "during", "in", "known", "set"})
_OMITTED = object()
# A schema without kinds: what admission refuses of a document against it, beside its unknown kinds, is the
# document's own shape (sections).
SHAPE = Schema({"format": FORMAT, "pack": {"id": ""}, "kinds": []})
DOCUMENT = {"document_null", "document_not_mapping", "section_null", "section_not_list"}
# A refusal's code as the loader has always said it; `where` is admission's (kind[record].slot).
TEXT = {
    "document_null": "a null document is not a fact file; write {{}} for a file without records",
    "document_not_mapping": "a fact file is a mapping of kind to records, not a {data}",
    "section_null": "section '{where}' is null; write [] for an empty relation",
    "section_not_list": "section '{where}' is not a list of records",
    "unknown_kind": "unknown kind '{where}'",
    "kind_without_identifier": "{where}: has no identifier; give its elements inlined",
    "kind_abstract": "{where}: the kind is abstract",
    "record_without_identifier": "{where}: record without its identifier",
    "unknown_slot": "{where}: unknown slot '{name}'",
    "dictionary_value_not_record": "{where}: in the dictionary form, the value must be a record",
    "wrong_type": "{where}: is not a {type}",
    "invalid_sha256": "{where}: invalid SHA-256 digest",
    "decision_missing": "{where}: a decided value names its decision (plane: control)",
}


class LoadError(Diagnosed):
    """Facts that do not load, with their diagnostics (D15): admission's refusals keep their codes and places."""


def files(pack_dir: str | Path) -> list[Path]:
    """Legacy fact files followed by declared datasets, in path order within each group."""
    pack_dir = Path(pack_dir)
    paths = sorted((pack_dir / "facts").glob("*.yaml"))
    for path in paths:
        if path.name.endswith(".sources.yaml") and not path.with_name(path.name.removesuffix(".sources.yaml") + ".yaml").is_file():
            raise LoadError(f"{path.name}: a source sidecar has no companion fact file")
    return [p for p in paths if not p.name.endswith(".sources.yaml")] + _named_datasets(pack_dir)


def _named_datasets(pack_dir: Path) -> list[Path]:
    meta, modules = _module_entries(pack_dir)
    return sorted(pack_dir / declared.form for declared in modules
                  if _declared_dataset(pack_dir, meta, declared) is not None)


def _module_entries(pack_dir: Path) -> tuple[dict, list[rezono_module.Declared]]:
    manifest = pack_dir / "pack.yaml"
    if not manifest.exists():
        return {}, []
    try:
        meta = strict_yaml.read(manifest)
    except (OSError, yaml.YAMLError) as error:
        raise LoadError(f"pack.yaml: cannot read dataset declarations ({error})") from error
    if not isinstance(meta, dict):
        raise LoadError("pack.yaml: expected a mapping of pack metadata")

    errors: list[str] = []
    modules = rezono_module.declared(meta, pack_dir, errors, reject_undeclared=False, include_datasets=True)
    if errors:
        raise LoadError("\n".join(errors))
    return meta, modules


@dataclass(frozen=True)
class DatasetForm:
    form: dict
    source: str | None


def _declared_dataset(pack_dir: Path, meta: dict, declared: rezono_module.Declared) -> DatasetForm | None:
    path = pack_dir / declared.form
    source_dir = pack_dir.resolve() / rezono_module.DIR
    try:
        if not all((pack_dir / name).resolve().is_relative_to(source_dir)
                   for name in (declared.module, declared.form)):
            raise LoadError(f"{declared.form}: a module or form resolves outside {rezono_module.DIR}/")
        submitted = json.loads(path.read_bytes())
    except (OSError, ValueError) as error:
        raise LoadError(f"{declared.form}: cannot read module form ({error})") from error
    plain = rezono_module.module_body(submitted, rezono_module.FORMAT)
    if (plain is not None and rezono_module.fact_tables_only(plain)
            and not rezono_module.form_only_source(pack_dir / declared.module, submitted)):
        return _fact_tables(pack_dir, meta, declared, submitted)
    if any(rezono_module.module_body(submitted, version) is not None
           for version in (rezono_module.FORMAT, rezono_module.NATIVE_FORMAT)):
        return None
    module = rezono_module.module_body(submitted, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"{declared.form}: expected a Rezono module form")
    if not any(isinstance(decl, dict) and "dataset" in decl for decl in module["decls"]):
        return None
    # Declarations before the dataset are lowered as a schema module; only the dataset's tables load here.
    submitted = rezono_module.dataset_only(submitted)
    module = submitted["module"]

    basename = Path(declared.module).stem
    name = _named_dataset(module)["dataset"]
    if name != basename:
        raise LoadError(f"{declared.form}: module '{basename}' declares dataset '{name}'")
    if submitted["spans"] and not rezono_module.valid_places(module, submitted["spans"]):
        raise LoadError(f"{declared.form}: spans must place each module node")

    errors: list[str] = []
    pack_name = str(meta.get("name", ""))
    effective = rezono_module.effective_dataset_form(pack_dir, declared, pack_name, submitted, errors)
    if effective is None:
        raise LoadError("\n".join(errors))
    if effective is submitted:
        return DatasetForm(submitted, None)
    effective = rezono_module.dataset_only(effective)
    authored = rezono_module.module_body(effective, DATASET_FORMAT)
    dataset = rezono_module.named_dataset(authored) if authored is not None else None
    if authored is None or dataset is None:
        raise LoadError(f"{declared.module}: expected one named dataset")
    if dataset["dataset"] != basename:
        raise LoadError(f"{declared.module}: module '{basename}' declares dataset '{dataset['dataset']}'")
    errors = [message for _, message, _ in rezono_module.header_errors(authored, pack_name)]
    if errors:
        raise LoadError(f"{declared.module}: " + "; ".join(errors))
    return DatasetForm(effective, declared.module)


def _fact_tables(pack_dir: Path, meta: dict, declared: rezono_module.Declared, submitted: dict) -> DatasetForm:
    """A module of fact tables, read from its authored source, as the named dataset of its file name."""
    errors: list[str] = []
    effective = rezono_module.source_form(pack_dir, declared, submitted, errors, lambda source: False)
    if effective is None:
        raise LoadError("\n".join(errors))
    authored = rezono_module.module_body(effective, rezono_module.FORMAT)
    if authored is None or not rezono_module.fact_tables_only(authored):
        raise LoadError(f"{declared.module}: a module of fact tables declares nothing else")
    problems = [message for _, message, _ in rezono_module.header_errors(authored, str(meta.get("name", "")))]
    if problems:
        raise LoadError(f"{declared.module}: " + "; ".join(problems))
    spans = [span | {"at": re.sub(r"^/decls/", "/decls/0/decls/", span["at"])} for span in effective["spans"]]
    module = authored | {"decls": [{"dataset": Path(declared.module).stem, "decls": authored["decls"]}]}
    return DatasetForm({"format": DATASET_FORMAT, "module": module, "spans": spans}, declared.module)


def dataset_at(path: Path) -> DatasetForm | None:
    """Resolve a declared dataset's authored source while retaining standalone JSON forms."""
    if path.suffix != ".json":
        return None
    for spelling in dict.fromkeys((Path(os.path.abspath(path)), path.resolve())):
        for parent in spelling.parents:
            if parent.name != rezono_module.DIR or not (parent.parent / "pack.yaml").is_file():
                continue
            pack_dir = parent.parent
            meta, modules = _module_entries(pack_dir)
            for declared in modules:
                if pack_dir / declared.form == spelling:
                    return _declared_dataset(pack_dir, meta, declared)
    return None


def _load_error(code: str, message: str, where: str = "") -> LoadError:
    return LoadError(message, [Diagnostic(code, message, where)])


def _parse_iso_date(value: object, where: str) -> datetime.date:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        raise _load_error("invalid_date", f"{where}: expected an ISO date YYYY-MM-DD", where)
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as error:
        raise _load_error("invalid_date", f"{where}: invalid calendar date {value!r}", where) from error


def document(path: Path, pack: Pack | None = None, *, as_of: str | None = None, known: str | None = None) -> dict[str, list]:
    """Read records per kind from a fact file or a named dataset.

    A null document or section is refused. Use {} for an empty document or [] for an empty relation.
    """
    data, _ = _document_with_dated_tables(path, pack, as_of=as_of, known=known)
    return data


def _document_with_dated_tables(
    path: Path, pack: Pack | None = None, *, as_of: str | None = None, known: str | None = None
) -> tuple[dict[str, list], set[str]]:
    as_of_date = _parse_iso_date(as_of, "as_of") if as_of is not None else None
    known_date = _parse_iso_date(known, "known") if known is not None else None
    dataset = dataset_at(path)
    data = dataset.form if dataset is not None else strict_yaml.read(path)
    dated_tables: set[str] = set()
    if isinstance(data, dict) and data.get("format") == DATASET_FORMAT:
        if pack is not None:
            data, _, dated_tables = _located_scalar_dataset(schema(pack), data, as_of=as_of_date, known=known_date)
        else:
            data = untyped_dataset(data, as_of=as_of_date, known=known_date)
    return sections(data), dated_tables


def sections(data) -> dict[str, list]:
    """`data` checked as records per kind: a mapping whose every section is a list."""
    refused = [r for r in admit(SHAPE, data)[1] if r.code in DOCUMENT]
    if refused:
        raise refusal(SHAPE, data, refused)
    return data


class FactSchema(Schema):
    """Keep module slot cardinality alongside the unchanged admission bundle."""

    def __init__(self, bundle: dict, optional_slots: set[str]):
        super().__init__(bundle)
        self.optional_slots = frozenset(optional_slots)


def schema(pack: Pack) -> FactSchema:
    """What admission judges a pack's facts against: the kinds, attributes and arrows of its schema bundle
    (emit.bundle), only the fields admission reads. A test holds them equal to the archived bundle's; the hash
    is of these fields, not of the archived bundle."""
    def present(d):
        return {k: v for k, v in d.items() if v is not None}
    kinds, attributes, arrows = [], [], []
    optional_slots = set()
    for k, kind in pack.kinds.items():
        kinds.append(present({"id": k, "parent": kind.parent, "abstract": kind.abstract,
                              "identifier": kind.identifier,
                              "id_type": types.of_sql(pack.kinds[pack.root(k)].id_type).bundle,
                              "plane": kind.plane, "owner": kind.owner}))
        for s in kind.slots.values():
            if not s.required and not s.minimum_cardinality:
                optional_slots.add(s.table)
            common = {"kind": k, "name": s.name, "table": s.table, "multivalued": s.multivalued}
            if s.arrow:
                arrows.append(common | {"target": s.range, "inlined": s.inlined})
            else:
                attributes.append(common | present({"type": s.type.bundle, "input_format": s.input_format}))
    return FactSchema({"format": FORMAT, "pack": {"id": pack.meta["name"]}, "kinds": kinds,
                       "attributes": attributes, "arrows": arrows}, optional_slots)


def load(pack: Pack, path: str | Path, *, as_of: str | None = None, known: str | None = None) -> dict[str, list[tuple]]:
    path = Path(path)
    try:
        data, dated_tables = _document_with_dated_tables(path, pack, as_of=as_of, known=known)
        rows = rows_of(pack, data)
        if dated_tables:
            for table in dated_tables:
                rows.setdefault(table, [])
            rows = {t: rows[t] for t in sorted(rows)}
    except LoadError as error:
        raise placed(error, path) from None
    if path.parent.name == "facts" and path.with_suffix(".sources.yaml").exists():
        from .sources import file_entries
        file_entries(pack, path, data)  # malformed metadata blocks batch loading too; the row API stays unchanged
    return rows


def _named_dataset(module: dict) -> dict:
    dataset = rezono_module.named_dataset(module)
    if dataset is None:
        raise LoadError("expected one named dataset in the module form")
    return dataset


def named_dataset_decls(form: dict) -> list:
    """The fact tables and source declarations of the named dataset of a module form, in source order."""
    module = rezono_module.module_body(form, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"expected {DATASET_FORMAT} with a module header and spans")
    return _named_dataset(module)["decls"]


def scalar_dataset(judged: FactSchema, form: dict, *,
                   as_of: datetime.date | None = None, known: datetime.date | None = None) -> dict[str, list]:
    """Decode a named module dataset into the records used by ordinary admission."""
    records, _, _ = _located_scalar_dataset(judged, form, as_of=as_of, known=known)
    return records


def located_scalar_dataset(judged: FactSchema, form: dict, *,
                           as_of: datetime.date | None = None,
                           known: datetime.date | None = None) -> tuple[dict[str, list], dict[str, list[str]]]:
    """Decode each record with its JSON pointer for publication provenance."""
    records, pointers, _ = _located_scalar_dataset(judged, form, as_of=as_of, known=known)
    return records, pointers


def _located_scalar_dataset(
    judged: FactSchema,
    form: dict,
    *,
    as_of: datetime.date | None = None,
    known: datetime.date | None = None,
) -> tuple[dict[str, list], dict[str, list[str]], set[str]]:
    module = rezono_module.module_body(form, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"expected {DATASET_FORMAT} with a module header and spans")
    problems = [message for _, message, _ in rezono_module.header_errors(module, judged.pack)]
    if problems:
        raise LoadError("\n".join(problems))
    tables = _named_dataset(module)["decls"]

    records: dict[str, list] = {}
    pointers: dict[str, list[str]] = {}
    fact_rows: list[_ParsedFactRow] = []
    for table_index, table in enumerate(tables):
        if source_decl(table):
            continue
        if fact_row_decl(table):
            fact_rows.append(_decode_fact_row(table, table_index, judged))
            continue
        kind, columns, rows, cited = dataset_table(table)
        if kind not in judged.kinds:
            raise LoadError(f"unknown kind '{kind}'")
        identifier = judged.kinds[judged.root(kind)].identifier
        if columns[0] != identifier:
            raise LoadError(f"{kind}: expected unique columns beginning with the identifier")

        for column in columns[1:]:
            if judged.slot(kind, column) is None:
                raise LoadError(f"{kind}: unknown slot '{column}'")

        output = records.setdefault(kind, [])
        places = pointers.setdefault(kind, [])
        for row_index, row in enumerate(rows):
            where = f"{kind}[{len(output) + 1}]"
            if not isinstance(row, list) or len(row) != len(columns) + len(cited):
                raise LoadError(f"{where}: row width does not match the fact table header")
            output.append(dataset_record(zip(columns, row[:len(columns)], strict=True), where, judged, kind))
            places.append(f"/module/decls/0/decls/{table_index}/rows/{row_index}")
    dated_tables = _resolve_fact_rows(fact_rows, records, pointers, judged, as_of, known)
    return records, pointers, dated_tables


def untyped_dataset(form: dict, *,
                    as_of: datetime.date | None = None,
                    known: datetime.date | None = None) -> dict[str, list]:
    """Read the authored shapes when no pack is available to supply column types."""
    module = rezono_module.module_body(form, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"expected {DATASET_FORMAT} with a module header and spans")
    problems = [message for _, message, _ in rezono_module.header_errors(module, module["pack"])]
    if problems:
        raise LoadError("\n".join(problems))

    records: dict[str, list] = {}
    pointers: dict[str, list[str]] = {}
    fact_rows: list[_ParsedFactRow] = []
    for index, table in enumerate(_named_dataset(module)["decls"]):
        if source_decl(table):
            continue
        if fact_row_decl(table):
            fact_rows.append(_decode_fact_row(table, index, None))
            continue
        kind, columns, rows, cited = dataset_table(table)
        output = records.setdefault(kind, [])
        places = pointers.setdefault(kind, [])
        for row_index, row in enumerate(rows):
            where = f"{kind}[{len(output) + 1}]"
            if not isinstance(row, list) or len(row) != len(columns) + len(cited):
                raise LoadError(f"{where}: row width does not match the fact table header")
            output.append(dataset_record(zip(columns, row[:len(columns)], strict=True), where))
            places.append(f"/module/decls/0/decls/{index}/rows/{row_index}")
    _resolve_fact_rows(fact_rows, records, pointers, None, as_of, known)
    return records


def fact_row_decl(decl) -> bool:
    """A FactRow declaration in a dataset (decisions/language-dated-facts.md)."""
    return isinstance(decl, dict) and "fact" in decl and "columns" not in decl and "rows" not in decl


@dataclass(frozen=True)
class _ParsedFactRow:
    index: int
    kind: str
    root: str
    id_key: str
    eid: object
    valid: tuple[datetime.date, datetime.date | None] | None
    known: datetime.date | None
    assignments: list[tuple[str, str, object]]

    @property
    def dated(self) -> bool:
        return self.valid is not None or self.known is not None


def _normalize_fact_expr(cell):
    """Normalize expression nodes written by the module reader into scalar/collection fact cells."""
    if not isinstance(cell, dict):
        return cell
    if cell.keys() == {"list"} and isinstance(cell["list"], list):
        return {"list": [_normalize_fact_expr(item) for item in cell["list"]]}
    if cell.keys() == {"record"} and isinstance(cell["record"], dict):
        return {"record": {k: _normalize_fact_expr(v) for k, v in cell["record"].items()}}
    if cell.keys() == {"path"} and isinstance(cell["path"], list) and len(cell["path"]) == 1 and isinstance(cell["path"][0], str):
        return {"lit": cell["path"][0]}
    if cell.keys() == {"kind"} and isinstance(cell["kind"], str):
        return {"lit": cell["kind"]}
    if (cell.keys() == {"neg"} and isinstance(cell["neg"], dict)
            and cell["neg"].keys() == {"lit"} and isinstance(cell["neg"]["lit"], str)
            and re.fullmatch(r"[0-9]+", cell["neg"]["lit"])):
        return {"lit": "-" + cell["neg"]["lit"]}
    return cell


def _check_slot_value(slot, value, where: str) -> None:
    if isinstance(value, list):
        for i, item in enumerate(value, 1):
            _check_slot_value(slot, item, f"{where}[{i}]")
        return
    if slot.input_format == "sha256" and (not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)):
        raise _load_error("invalid_sha256", f"{where}: invalid SHA-256 digest", where)


def _decode_fact_row(decl: dict, index: int, judged: FactSchema | None) -> _ParsedFactRow:
    extra = decl.keys() - FACT_ROW_KEYS
    if extra:
        raise _load_error("invalid_fact_row", f"decls[{index}]: unexpected fields in fact row: {sorted(extra)}")
    if not {"fact", "id", "set"} <= decl.keys():
        raise _load_error("invalid_fact_row", f"decls[{index}]: a fact row needs fact, id and set")
    if not isinstance(decl["fact"], str):
        raise _load_error("invalid_fact_row", f"decls[{index}]: invalid dataset fact kind")
    kind = snake(decl["fact"])

    id_key = "id"
    root = kind
    if judged is not None:
        if kind not in judged.kinds:
            raise _load_error("unknown_kind", f"unknown kind '{kind}'", kind)
        if judged.kinds[kind].abstract:
            raise _load_error("kind_abstract", f"{kind}: the kind is abstract", kind)
        root = judged.root(kind)
        identity = judged.kinds[root]
        if identity.identifier is None:
            raise _load_error("kind_without_identifier", f"{kind}: has no identifier", kind)
        id_key = identity.identifier
        raw_id = decl["id"]
        sql_type = SQL_TYPES[identity.id_type]
        id_where = f"{kind}.{id_key}"
        if isinstance(raw_id, str):
            if sql_type == "VARCHAR":
                if not raw_id:
                    raise _load_error("wrong_type", f"{id_where}: identifier cannot be empty", id_where)
                eid: object = raw_id
            else:
                eid = scalar_cell({"lit": raw_id}, sql_type, id_where)
        else:
            eid = typed(sql_type, raw_id, id_where)
    else:
        eid = decl["id"]

    where = f"{kind}[{eid}]"
    if "during" in decl or "in" in decl:
        raise _load_error("unsupported_context", f"{where}: stage and setup contexts (during/in) are not lowered yet", kind)

    valid_range: tuple[datetime.date, datetime.date | None] | None = None
    if "valid" in decl:
        raw_valid = decl["valid"]
        if not isinstance(raw_valid, list) or not (1 <= len(raw_valid) <= 2):
            raise _load_error("invalid_date_range", f"{where}: valid must be one or two ISO dates", kind)
        start = _parse_iso_date(raw_valid[0], f"{where}.valid[0]")
        end = _parse_iso_date(raw_valid[1], f"{where}.valid[1]") if len(raw_valid) == 2 else None
        if end is not None and end <= start:
            raise _load_error(
                "invalid_date_range",
                f"{where}: valid end date {raw_valid[1]!r} must be after start date {raw_valid[0]!r}",
                f"{where}.valid",
            )
        valid_range = (start, end)

    row_known: datetime.date | None = None
    if "known" in decl:
        row_known = _parse_iso_date(decl["known"], f"{where}.known")

    raw_set = decl["set"]
    if not isinstance(raw_set, list):
        raise _load_error("invalid_fact_row", f"{where}: set must be a list of assignments", kind)

    assignments: list[tuple[str, str, object]] = []
    seen: set[str] = set()
    for pos, item in enumerate(raw_set):
        if not isinstance(item, dict) or not {"slot", "value"} <= item.keys() or item.keys() - {"slot", "value", "source"}:
            raise _load_error("invalid_fact_row", f"{where}.set[{pos}]: expected slot and value", kind)
        if not isinstance(item["slot"], str):
            raise _load_error("invalid_fact_row", f"{where}.set[{pos}]: expected slot name", kind)
        slot_name = snake(item["slot"])
        if slot_name in seen:
            raise _load_error("duplicate_slot", f"{where}: duplicate field '{slot_name}'", f"{where}.{slot_name}")
        seen.add(slot_name)
        field_where = f"{where}.{slot_name}"
        cell = item["value"]
        if judged is not None:
            if slot_name == id_key:
                raise _load_error("unknown_slot", f"{where}: unknown slot '{slot_name}'", field_where)
            slot = judged.slot(kind, slot_name)
            if slot is None:
                raise _load_error("unknown_slot", f"{where}: unknown slot '{slot_name}'", field_where)
            if cell == {"lit": "n/a"}:
                if slot.table not in judged.optional_slots:
                    raise _load_error("wrong_type", f"{field_where}: n/a requires an optional slot", field_where)
                decoded: object = _OMITTED
            else:
                decoded = dataset_cell(
                    _normalize_fact_expr(cell),
                    field_where,
                    SQL_TYPES[slot.type],
                    judged,
                    slot.target if slot.inlined else None,
                )
                _check_slot_value(slot, decoded, field_where)
            table_name = slot.table
        else:
            decoded = _OMITTED if cell == {"lit": "n/a"} else dataset_cell(_normalize_fact_expr(cell), field_where)
            table_name = f"{kind}__{slot_name}"
        assignments.append((slot_name, table_name, decoded))

    return _ParsedFactRow(index, kind, root, id_key, eid, valid_range, row_known, assignments)


def _resolve_fact_rows(
    fact_rows: list[_ParsedFactRow],
    records: dict[str, list],
    pointers: dict[str, list[str]],
    judged: FactSchema | None,
    as_of: datetime.date | None,
    known: datetime.date | None,
) -> set[str]:
    if not fact_rows:
        return set()

    def ancestors(rec_kind: str) -> list[str]:
        return judged.ancestors(rec_kind) if judged is not None else [rec_kind]

    by_root: dict[tuple[str, object], list[tuple[str, dict]]] = {}
    for rec_kind, rec_list in records.items():
        root = judged.root(rec_kind) if judged is not None else rec_kind
        id_key = judged.kinds[root].identifier if judged is not None else "id"
        if id_key is None:
            continue
        for rec in rec_list:
            if id_key in rec:
                by_root.setdefault((root, rec[id_key]), []).append((rec_kind, rec))

    def matching_records(row: _ParsedFactRow) -> list[tuple[str, dict]]:
        return [(rk, rec) for rk, rec in by_root.get((row.root, row.eid), []) if row.kind in ancestors(rk)]

    for row in fact_rows:
        if row.dated:
            continue
        matches = matching_records(row)
        if matches:
            for _, rec in matches:
                for slot_name, _, val in row.assignments:
                    if slot_name in rec:
                        raise _load_error(
                            "duplicate_slot",
                            f"{row.kind}[{row.eid}]: duplicate field '{slot_name}'",
                            f"{row.kind}.{slot_name}",
                        )
                    if val is not _OMITTED:
                        rec[slot_name] = val
        else:
            new_rec: dict[str, object] = {row.id_key: row.eid}
            for slot_name, _, val in row.assignments:
                if val is not _OMITTED:
                    new_rec[slot_name] = val
            records.setdefault(row.kind, []).append(new_rec)
            pointers.setdefault(row.kind, []).append(f"/module/decls/0/decls/{row.index}")
            by_root.setdefault((row.root, row.eid), []).append((row.kind, new_rec))

    dated_tables: set[str] = set()
    applying: dict[tuple[str, object, str], list[tuple[tuple[int, datetime.date], str, object, list[tuple[str, dict]]]]] = {}
    for row in fact_rows:
        if not row.dated:
            continue
        matches = matching_records(row)
        if not matches:
            raise _load_error(
                "unknown_record",
                f"{row.kind}: dated fact row references unknown record {row.eid!r}",
                row.kind,
            )
        if row.valid is not None and as_of is None:
            raise _load_error(
                "missing_as_of",
                f"{row.kind}[{row.eid}]: dated fact row with valid range requires as_of",
                row.kind,
            )
        if row.known is not None and known is None:
            raise _load_error(
                "missing_known",
                f"{row.kind}[{row.eid}]: dated fact row with known date requires known",
                row.kind,
            )
        for slot_name, table_name, _ in row.assignments:
            dated_tables.add(table_name)
            if any(slot_name in rec for _, rec in matches):
                raise _load_error(
                    "versions_overlap",
                    f"{table_name}: versions_overlap between undated and dated assignments for record {row.eid!r}",
                    table_name,
                )
        valid_ok = row.valid is None or (
            row.valid[0] <= as_of and (row.valid[1] is None or as_of < row.valid[1])  # type: ignore[operator]
        )
        known_ok = row.known is None or row.known <= known  # type: ignore[operator]
        if not (valid_ok and known_ok):
            continue
        rank = (1, row.known) if row.known is not None else (0, datetime.date.min)
        for slot_name, table_name, val in row.assignments:
            key = (row.root, row.eid, table_name)
            applying.setdefault(key, []).append((rank, slot_name, val, matches))

    for (root, eid, table_name), candidates in applying.items():
        best_rank = max(item[0] for item in candidates)
        winners = [item for item in candidates if item[0] == best_rank]
        if len(winners) > 1:
            raise _load_error(
                "versions_overlap",
                f"{table_name}: versions_overlap for record {eid!r}",
                table_name,
            )
        _, slot_name, val, matches = winners[0]
        for _, rec in matches:
            if val is _OMITTED:
                rec.pop(slot_name, None)
            else:
                rec[slot_name] = val

    return dated_tables


def source_decl(decl) -> bool:
    """A source declaration of a dataset (decisions/language-fact-provenance.md); sources.py reads its fields."""
    return isinstance(decl, dict) and decl.keys() == {"source", "fields"}


def dataset_table(table) -> tuple[str, list[str], list, list[str]]:
    """The kind, slot columns and rows of a fact table, and the source fields of its `@` columns, which follow
    the slot columns in each row."""
    if (not isinstance(table, dict) or not {"fact", "columns", "rows"} <= table.keys()
            or table.keys() - {"fact", "columns", "rows", "source", "sourceColumns"}):
        raise LoadError("datasets require fact tables")
    if not isinstance(table["fact"], str):
        raise LoadError("invalid dataset fact kind")
    kind = snake(table["fact"])
    columns, rows = table["columns"], table["rows"]
    if not isinstance(columns, list) or not columns or not all(isinstance(c, str) for c in columns):
        raise LoadError(f"{kind}: expected a nonempty fact table header")
    columns = [snake(column) for column in columns]
    if len(set(columns)) != len(columns):
        raise LoadError(f"{kind}: expected unique columns beginning with the identifier")
    if not isinstance(rows, list):
        raise LoadError(f"{kind}: expected fact table rows")
    if "source" in table and not isinstance(table["source"], str):
        raise LoadError(f"{kind}: invalid source citation")
    cited = table.get("sourceColumns", [])
    if "sourceColumns" in table and "source" not in table:
        raise LoadError(f"{kind}: a source column needs a source citation `@ name` after the fact kind")
    if (not isinstance(cited, list) or ("sourceColumns" in table and not cited)
            or not all(isinstance(c, str) and c for c in cited) or len(set(cited)) != len(cited)):
        raise LoadError(f"{kind}: expected each source field once after the slot columns")
    return kind, columns, rows, cited


def dataset_record(entries, where: str, judged: FactSchema | None = None, kind: str | None = None) -> dict:
    identity = judged.kinds[judged.root(kind)] if judged is not None else None
    record = {}
    seen = set()
    for name, cell in entries:
        if not isinstance(name, str):
            raise LoadError(f"{where}: expected a named record field")
        name = snake(name)
        if name in seen:
            raise LoadError(f"{where}: duplicate field '{name}'")
        seen.add(name)
        slot = None
        if identity is not None and name != identity.identifier:
            slot = judged.slot(kind, name)
            if slot is None:
                raise LoadError(f"{where}: unknown slot '{name}'")
        if cell == {"boundary": "omitted"}:
            continue
        field = f"{where}.{name}"
        if judged is not None and cell == {"lit": "n/a"}:
            if slot is None or slot.table not in judged.optional_slots:
                raise LoadError(f"{field}: n/a requires an optional slot")
            continue
        if slot is not None:
            record[name] = dataset_cell(cell, field, SQL_TYPES[slot.type], judged, slot.target if slot.inlined else None)
        else:
            sql_type = SQL_TYPES[identity.id_type] if identity is not None else None
            record[name] = dataset_cell(cell, field, sql_type)
    return record


def dataset_cell(cell, where: str, sql_type: str | None = None,
                 judged: FactSchema | None = None, target: str | None = None):
    # A list in a single-valued slot is admitted as a legacy document admits it: the typed rows then
    # carry each value, and the slot's functionality check reports the second one.
    if isinstance(cell, dict) and cell.keys() == {"list"}:
        if not isinstance(cell["list"], list):
            raise LoadError(f"{where}: expected a value of the declared slot")
        return [dataset_cell(item, f"{where}[{index}]", sql_type, judged=judged, target=target)
                for index, item in enumerate(cell["list"], 1)]
    if isinstance(cell, dict) and cell.keys() == {"record"}:
        if (sql_type is not None and target is None) or not isinstance(cell["record"], dict):
            raise LoadError(f"{where}: expected a value of the declared slot")
        return dataset_record(cell["record"].items(), where, judged, target)
    if sql_type is not None:
        return scalar_cell(cell, sql_type, where)
    if not isinstance(cell, dict) or cell.keys() != {"lit"} or not isinstance(cell["lit"], str):
        raise LoadError(f"{where}: expected a fact literal")
    raw = cell["lit"]
    if re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw):
        return scalar_cell(cell, "BIGINT", where)
    if raw in ("true", "false"):
        return scalar_cell(cell, "BOOLEAN", where)
    if ISO_DATE.fullmatch(raw):
        return scalar_cell(cell, "DATE", where)
    if raw.startswith('"'):
        return scalar_cell(cell, "VARCHAR", where)
    return raw


def scalar_cell(cell, sql_type: str, where: str):
    """Convert a scalar literal only according to its declared column type."""
    if not isinstance(cell, dict) or cell.keys() != {"lit"} or not isinstance(cell["lit"], str):
        raise LoadError(f"{where}: expected a scalar literal")
    raw = cell["lit"]
    value: object = raw
    if sql_type == "BIGINT" and re.fullmatch(r"-?[0-9]+", raw):
        try:
            value = int(raw)
        except ValueError as error:
            raise LoadError(f"{where}: invalid integer literal") from error
    elif sql_type == "BOOLEAN" and raw in ("true", "false"):
        value = raw == "true"
    elif sql_type == "VARCHAR" and raw.startswith('"'):
        try:
            value = json.loads(raw)
        except ValueError as error:
            raise LoadError(f"{where}: invalid quoted text literal") from error
    elif sql_type == "VARCHAR" and (not raw or any(c.isspace() for c in raw)):
        raise LoadError(f"{where}: invalid unquoted text literal")
    return typed(sql_type, value, where)


def rows_of(pack: Pack, data: dict) -> dict[str, list[tuple]]:
    """Records per kind ({kind: [record, ...]}) as rows per engine table. Every refusal is in the LoadError."""
    judged = schema(pack)
    rows, refused = admit(judged, data)
    if refused:
        raise refusal(judged, data, refused)
    rows |= seal.row_sha256(pack, rows)  # the row hash of each sealed element, as a fact
    return {t: sorted(r, key=repr) for t, r in sorted(rows.items())}


def walk(judged: Schema, kind: str, record, *, on_row=None, on_record=None, context=None) -> None:
    """One record of `kind` through admission, for a caller that needs where each row comes from (the sources):
    the observer sees every record and row (rezono_admission.rows); a refusal is a LoadError."""
    data = {kind: [record]}
    refused = admit(judged, data, on_row=on_row, on_record=on_record, context=context)[1]
    if refused:
        raise refusal(judged, data, refused)


def message(judged: Schema, data, refused) -> str:
    """Admission's refusals as the loader's message: one per refusal, in admission's order."""
    return "; ".join(_text(judged, data, r) for r in refused)


def refusal(judged: Schema, data, refused) -> LoadError:
    """Admission's refusals as one LoadError: the loader's message, and per refusal its diagnostic with admission's
    code and place (rezono_admission.Refusal.diagnostic) and the loader's sentence."""
    return LoadError(message(judged, data, refused),
                     [Diagnostic(r.code, _text(judged, data, r), r.where) for r in refused])


def placed(error: LoadError, path: Path) -> LoadError:
    """`error` with a span on each diagnostic (D15, MOD2's spans): the key or list item of the fact file nearest to
    its admission place (`Kind[3].slot`, positions from 1). The file is named relative to its pack."""
    found = spans.marks(path)
    file = f"facts/{path.name}" if path.parent.name == "facts" else path.name
    out = []
    for d in error.diagnostics:
        keys = tuple(int(n) - 1 if n else key for key, n in PLACE.findall(d.where))
        out.append(replace(d, span=spans.first(found, file, *(keys[:n] for n in range(len(keys), 0, -1)))))
    return LoadError(str(error), out)


def _text(judged: Schema, data, r) -> str:
    return TEXT[r.code].format(where=r.where, data=type(data).__name__, name=r.where.rpartition(".")[2],
                               type=_type_at(judged, r.where) if r.code == "wrong_type" else None)


def _type_at(judged: Schema, where: str) -> str:
    """The SQL type a refused value should have had, from where admission found it (kind[n].slot[n].slot)."""
    head, *steps = where.split(".")
    kind, t = head.partition("[")[0], None
    for step in steps:
        s = judged.slot(kind, step.partition("[")[0])
        if s is None:  # the record's identifier
            t = judged.kinds[judged.root(kind)].id_type
        else:
            t, kind = s.type, s.target or kind
    return SQL_TYPES[t]


def typed(sql_type: str, v, where: str):
    """The value in its engine type. A date may also be ISO text (YYYY-MM-DD), because JSON has no dates."""
    t = PYTHON_TYPES[sql_type]
    if t is datetime.date and isinstance(v, str) and ISO_DATE.match(v):
        try:
            return datetime.date.fromisoformat(v)
        except ValueError:
            pass
    if not isinstance(v, t) or (t is int and isinstance(v, bool)) or (t is datetime.date and isinstance(v, datetime.datetime)):
        raise LoadError(f"{where}: {v!r} is not a {sql_type}")
    return v


def ingress(pack: Pack, rows: dict[str, list[tuple]], weight: str = "insert") -> dict[str, list[dict]]:
    """Rows as Feldera JSON updates ({"insert": {...}} or {"delete": {...}}), per table."""
    out = {}
    for table, rs in rows.items():
        cols = ("id",) if table in pack.kinds else ("id", "v")
        out[table] = [{weight: {c: (x.isoformat() if isinstance(x, datetime.date) else x)
                                for c, x in zip(cols, r)}} for r in rs]
    return out
