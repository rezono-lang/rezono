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

from . import rezono_module, seal, spans, types
from .diagnostics import Diagnosed, Diagnostic
from .pack import Pack, snake

ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
PLACE = re.compile(r"([^.\[\]]+)|\[([0-9]+)\]")  # admission's place: names, and positions from 1 in brackets
PYTHON_TYPES = {"VARCHAR": str, "BIGINT": int, "BOOLEAN": bool, "DATE": datetime.date}
SQL_TYPES = {"text": "VARCHAR", "enum": "VARCHAR", "integer": "BIGINT", "boolean": "BOOLEAN", "date": "DATE"}
FORMAT = "rezono.schema-bundle/1"
DATASET_FORMAT = rezono_module.DATASET_FORMAT
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
        meta = yaml.safe_load(manifest.read_text(encoding="utf-8"))
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
    if any(rezono_module.module_body(submitted, version) is not None
           for version in (rezono_module.FORMAT, rezono_module.NATIVE_FORMAT)):
        return None
    module = rezono_module.module_body(submitted, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"{declared.form}: expected a Rezono module form")
    if not any(isinstance(decl, dict) and "dataset" in decl for decl in module["decls"]):
        return None

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


def document(path: Path, pack: Pack | None = None) -> dict[str, list]:
    """Read records per kind from a fact file or a named dataset.

    A null document or section is refused. Use {} for an empty document or [] for an empty relation.
    """
    dataset = dataset_at(path)
    data = dataset.form if dataset is not None else yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("format") == DATASET_FORMAT:
        data = scalar_dataset(schema(pack), data) if pack is not None else untyped_dataset(data)
    return sections(data)


def sections(data) -> dict[str, list]:
    """`data` checked as records per kind: a mapping whose every section is a list."""
    refused = [r for r in admit(SHAPE, data)[1] if r.code in DOCUMENT]
    if refused:
        raise refusal(SHAPE, data, refused)
    return data


def schema(pack: Pack) -> Schema:
    """What admission judges a pack's facts against: the kinds, attributes and arrows of its schema bundle
    (emit.bundle), only the fields admission reads. A test holds them equal to the archived bundle's; the hash
    is of these fields, not of the archived bundle."""
    def present(d):
        return {k: v for k, v in d.items() if v is not None}
    kinds, attributes, arrows = [], [], []
    for k, kind in pack.kinds.items():
        kinds.append(present({"id": k, "parent": kind.parent, "abstract": kind.abstract,
                              "identifier": kind.identifier,
                              "id_type": types.of_sql(pack.kinds[pack.root(k)].id_type).bundle,
                              "plane": kind.plane, "owner": kind.owner}))
        for s in kind.slots.values():
            common = {"kind": k, "name": s.name, "table": s.table, "multivalued": s.multivalued}
            if s.arrow:
                arrows.append(common | {"target": s.range, "inlined": s.inlined})
            else:
                attributes.append(common | {"type": s.type.bundle})
    return Schema({"format": FORMAT, "pack": {"id": pack.meta["name"]}, "kinds": kinds, "attributes": attributes,
                   "arrows": arrows})


def load(pack: Pack, path: str | Path) -> dict[str, list[tuple]]:
    path = Path(path)
    try:
        data = document(path, pack)
        rows = rows_of(pack, data)
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


def scalar_dataset(judged: Schema, form: dict) -> dict[str, list]:
    """Decode a named module dataset into the records used by ordinary admission."""
    records, _ = located_scalar_dataset(judged, form)
    return records


def located_scalar_dataset(judged: Schema, form: dict) -> tuple[dict[str, list], dict[str, list[str]]]:
    """Decode each record with its JSON pointer for publication provenance."""
    module = rezono_module.module_body(form, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"expected {DATASET_FORMAT} with a module header and spans")
    problems = [message for _, message, _ in rezono_module.header_errors(module, judged.pack)]
    if problems:
        raise LoadError("\n".join(problems))
    tables = _named_dataset(module)["decls"]

    records: dict[str, list] = {}
    pointers: dict[str, list[str]] = {}
    for table_index, table in enumerate(tables):
        kind, columns, rows = dataset_table(table)
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
            if not isinstance(row, list) or len(row) != len(columns):
                raise LoadError(f"{where}: row width does not match the fact table header")
            output.append(dataset_record(zip(columns, row, strict=True), where, judged, kind))
            places.append(f"/module/decls/0/decls/{table_index}/rows/{row_index}")
    return records, pointers


def untyped_dataset(form: dict) -> dict[str, list]:
    """Read the authored shapes when no pack is available to supply column types."""
    module = rezono_module.module_body(form, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"expected {DATASET_FORMAT} with a module header and spans")
    problems = [message for _, message, _ in rezono_module.header_errors(module, module["pack"])]
    if problems:
        raise LoadError("\n".join(problems))

    records: dict[str, list] = {}
    for table in _named_dataset(module)["decls"]:
        kind, columns, rows = dataset_table(table)
        output = records.setdefault(kind, [])
        for row in rows:
            where = f"{kind}[{len(output) + 1}]"
            if not isinstance(row, list) or len(row) != len(columns):
                raise LoadError(f"{where}: row width does not match the fact table header")
            output.append(dataset_record(zip(columns, row, strict=True), where))
    return records


def dataset_table(table) -> tuple[str, list[str], list]:
    if not isinstance(table, dict) or table.keys() != {"fact", "columns", "rows"}:
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
    return kind, columns, rows


def dataset_record(entries, where: str, judged: Schema | None = None, kind: str | None = None) -> dict:
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
        if slot is not None:
            record[name] = dataset_cell(cell, field, SQL_TYPES[slot.type], slot.multivalued,
                                        judged, slot.target if slot.inlined else None)
        else:
            sql_type = SQL_TYPES[identity.id_type] if identity is not None else None
            record[name] = dataset_cell(cell, field, sql_type)
    return record


def dataset_cell(cell, where: str, sql_type: str | None = None, repeated: bool = False,
                 judged: Schema | None = None, target: str | None = None):
    if isinstance(cell, dict) and cell.keys() == {"list"}:
        if (sql_type is not None and not repeated) or not isinstance(cell["list"], list):
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
