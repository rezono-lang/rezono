"""Import a named inventory export without changing authoritative placement facts."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile

import yaml

from rezono_compiler import facts, pack, sources, writer


def _name(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must contain non-empty text")
    return value


def _array(document: dict, field: str) -> list:
    values = document.get(field)
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    return values


def _render(document: object, mapping: object, filename: str, revision: str) -> tuple[str, dict, dict]:
    if not isinstance(mapping, dict) or set(mapping) != {"placement_fields"}:
        raise ValueError("the mapping must contain placement_fields")
    fields = mapping["placement_fields"]
    if not isinstance(fields, dict) or set(fields) != {"service", "cluster"}:
        raise ValueError("placement_fields must map service and cluster")
    service_key = _name(fields["service"], "service mapping")
    cluster_key = _name(fields["cluster"], "cluster mapping")
    if not isinstance(document, dict):
        raise ValueError("the export must be a JSON object")
    export = _name(document.get("export"), "export")
    observations, scope = [], []
    source_rows = []

    def cite(kind, ident, pointer):
        source_rows.append({
            "of": {"kind": kind, "id": ident}, "kind": "tool",
            "name": filename, "revision": revision, "position": pointer,
        })

    cite("cmdb_export", export, "/export")
    for index, record in enumerate(_array(document, "observations")):
        pointer = f"/observations/{index}"
        if not isinstance(record, dict):
            raise ValueError(f"{pointer} must be an object")
        ident = f"{export}/{index}"
        observations.append({
            "id": ident, "export": export,
            "service": _name(record.get(service_key), f"{pointer} service"),
            "cluster": _name(record.get(cluster_key), f"{pointer} cluster"),
        })
        cite("cmdb_observation", ident, pointer)
    for index, service in enumerate(_array(document, "complete_services")):
        ident = f"{export}/{index}"
        pointer = f"/complete_services/{index}"
        scope.append({"id": ident, "export": export, "service": _name(service, pointer)})
        cite("cmdb_scope", ident, pointer)
    return export, {"cmdb_export": [{"id": export}], "cmdb_observation": observations, "cmdb_scope": scope}, {
        "records": source_rows,
    }


def _write_pair(path: Path, companion: Path, fact_text: str, source_text: str) -> None:
    # The staging directory reserves this export while its two files are replaced.
    stage = path.with_suffix(".import")
    stage.mkdir()
    try:
        staged_fact = stage / path.name
        staged_source = stage / companion.name
        old_fact = stage / "previous"
        staged_fact.write_text(fact_text, encoding="utf-8", newline="\n")
        staged_source.write_text(source_text, encoding="utf-8", newline="\n")
        if path.exists():
            copyfile(path, old_fact)
        staged_fact.replace(path)
        try:
            staged_source.replace(companion)
        except OSError:
            if old_fact.exists():
                old_fact.replace(path)
            else:
                path.unlink()
            raise
    finally:
        for staged in stage.iterdir():
            staged.unlink()
        stage.rmdir()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    mapping = yaml.safe_load(args.mapping.read_text(encoding="utf-8"))
    export, data, metadata = _render(json.loads(raw), mapping, args.source.name, sha256(raw).hexdigest())
    model = pack.read(args.pack)
    facts.rows_of(model, data)
    stem = f"facts/cmdb-{sha256(export.encode('utf-8')).hexdigest()}"
    path = writer.fact_path(args.pack, stem + ".yaml")
    companion = writer.fact_path(args.pack, stem + ".sources.yaml")
    fact_text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    sources.text_entries(model, path.name, fact_text, data, metadata=metadata)
    _write_pair(path, companion, fact_text, yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False))


if __name__ == "__main__":
    main()
