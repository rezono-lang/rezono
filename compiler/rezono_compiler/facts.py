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
import re
from dataclasses import replace
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
DATASET_FORMAT = "rezono.module/2"
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
    """Fact data files only: a .sources.yaml companion is metadata, never a kind section."""
    paths = sorted((Path(pack_dir) / "facts").glob("*.yaml"))
    for path in paths:
        if path.name.endswith(".sources.yaml") and not path.with_name(path.name.removesuffix(".sources.yaml") + ".yaml").is_file():
            raise LoadError(f"{path.name}: a source sidecar has no companion fact file")
    return [p for p in paths if not p.name.endswith(".sources.yaml")]


def document(path: Path, pack: Pack | None = None) -> dict[str, list]:
    """Read records per kind, decoding a scalar dataset when its pack is available.

    A null document or section is refused. Use {} for an empty document or [] for an empty relation.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if pack is not None and isinstance(data, dict) and data.get("format") == DATASET_FORMAT:
        data = scalar_dataset(schema(pack), data)
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


def scalar_dataset(judged: Schema, form: dict) -> dict[str, list]:
    """Decode a named module dataset into the records used by ordinary admission."""
    module = rezono_module.module_body(form, DATASET_FORMAT)
    if module is None:
        raise LoadError(f"expected {DATASET_FORMAT} with a module header and spans")
    problems = [message for _, message, _ in rezono_module.header_errors(module, judged.pack)]
    if problems:
        raise LoadError("\n".join(problems))
    declarations = module["decls"]
    if len(declarations) != 1 or not isinstance(declarations[0], dict):
        raise LoadError("expected one named dataset in the module form")
    dataset = declarations[0]
    tables = dataset.get("decls")
    if (dataset.keys() != {"dataset", "decls"} or not isinstance(dataset["dataset"], str)
            or not dataset["dataset"] or not isinstance(tables, list)):
        raise LoadError("expected one named dataset in the module form")

    records: dict[str, list] = {}
    for table in tables:
        if not isinstance(table, dict) or table.keys() != {"fact", "columns", "rows"}:
            raise LoadError("scalar datasets require fact tables")
        if not isinstance(table["fact"], str):
            raise LoadError("invalid dataset fact kind")
        kind = snake(table["fact"])
        if kind not in judged.kinds:
            raise LoadError(f"unknown kind '{kind}'")
        identifier = judged.kinds[judged.root(kind)].identifier
        columns, rows = table["columns"], table["rows"]
        if not isinstance(columns, list) or not columns or not all(isinstance(c, str) for c in columns):
            raise LoadError(f"{kind}: expected a nonempty fact table header")
        columns = [snake(column) for column in columns]
        if columns[0] != identifier or len(set(columns)) != len(columns):
            raise LoadError(f"{kind}: expected unique columns beginning with the identifier")
        if not isinstance(rows, list):
            raise LoadError(f"{kind}: expected fact table rows")

        column_types = [judged.kinds[judged.root(kind)].id_type]
        for column in columns[1:]:
            slot = judged.slot(kind, column)
            if slot is None:
                raise LoadError(f"{kind}: unknown slot '{column}'")
            if slot.multivalued or slot.inlined:
                raise LoadError(f"{kind}.{column}: expected a scalar slot")
            column_types.append(slot.type)

        output = records.setdefault(kind, [])
        for row in rows:
            where = f"{kind}[{len(output) + 1}]"
            if not isinstance(row, list) or len(row) != len(columns):
                raise LoadError(f"{where}: row width does not match the fact table header")
            output.append({column: scalar_cell(cell, SQL_TYPES[type_], f"{where}.{column}")
                           for column, cell, type_ in zip(columns, row, column_types, strict=True)})
    return records


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
