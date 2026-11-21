"""Validate edge pilot results against the publication manifest."""

import json
from hashlib import sha256

from rezono_publisher import pointers, publish

_ORDER = {"green": 0, "warning": 1, "red": 2}


def reads_all_in_full(manifest: dict, role: str) -> bool:
    """Check a role's full coverage against all relations in the unscoped manifest."""
    snapshots = manifest.get("snapshots", [])
    relations = {snapshot["relation"] for snapshot in snapshots}
    full = {
        snapshot["relation"]
        for snapshot in snapshots
        if snapshot["role"] == role
        and (snapshot.get("full") is True or snapshot.get("complete") is True)
    }
    return bool(relations) and full == relations


def check_statuses(role: str, manifest: dict, truth: dict | None = None) -> None:
    """Check that check statuses match the store's unscoped manifest or all-or-nothing without one."""
    checks = manifest.get("checks")
    if truth is not None:
        if manifest.get("id") is None or manifest.get("id") != truth.get("id"):
            raise SystemExit(f"{role} checks: manifest {manifest.get('id')!r} checked against {truth.get('id')!r}")
        full = reads_all_in_full(truth, role)
        expected = [
            {"name": check["name"], "status": check["status"] if full else "unavailable"}
            for check in truth.get("checks", [])
        ]
        if checks != expected:
            raise SystemExit(f"{role} checks: expected {expected!r}, got {checks!r}")
        return

    if not isinstance(checks, list):
        raise SystemExit(f"{role} checks: expected a list, got {checks!r}")
    for check in checks:
        if (not isinstance(check, dict) or set(check) != {"name", "status"}
                or not isinstance(check["name"], str) or not check["name"]
                or not isinstance(check["status"], str)):
            raise SystemExit(f"{role} checks: invalid check entry {check!r}")
    statuses = {check["status"] for check in checks}
    if not statuses <= {"green", "warning", "unavailable"}:
        raise SystemExit(f"{role} checks: unexpected status in {checks!r}")
    if "unavailable" in statuses and statuses != {"unavailable"}:
        raise SystemExit(f"{role} checks: mixed unavailable and shown statuses in {checks!r}")
    if statuses and statuses != {"unavailable"} and not reads_all_in_full(manifest, role):
        raise SystemExit(f"{role} checks: status shown to a role that reads in part")


def asked(gate, role: str, pack: str, manifest: str, question: str) -> list[dict]:
    """Read all pages of one typed question from a role-scoped gate."""
    path = f"/{pack}/{manifest}/ask"
    headers = {"Content-Type": "application/json"}
    pages = []
    identity = None
    seen = set()
    body = {"ask": question}
    while True:
        status, answer = gate.call(path, method="POST", body=body, headers=headers)
        if status != 200 or not isinstance(answer, dict):
            raise SystemExit(f"{role} ask: expected a successful answer page")
        if (answer.get("format") != "rezono.answer/1" or answer.get("question") != "ask"
                or answer.get("manifest_id") != manifest):
            raise SystemExit(f"{role} ask: answer format, question or manifest mismatch")

        expression, dataset = answer.get("expression"), answer.get("dataset")
        if not isinstance(expression, dict) or expression.get("text") != question:
            raise SystemExit(f"{role} ask: answer expression mismatch")
        schema, expression_hash = answer.get("output_schema"), expression.get("hash")
        if (not isinstance(schema, str) or not schema
                or not isinstance(expression_hash, str) or not expression_hash
                or not isinstance(dataset, dict) or dataset.get("$schema") != schema):
            raise SystemExit(f"{role} ask: missing or mismatched schema or expression hash")
        current = (schema, expression_hash, dataset.get("schema"))
        if identity is not None and current != identity:
            raise SystemExit(f"{role} ask: answer schema or expression changed between pages")
        identity = current

        rows = dataset.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise SystemExit(f"{role} ask: expected a list of answer rows")
        pages.extend(rows)
        after = answer.get("next")
        if after is None:
            return pages
        if not isinstance(after, str) or not after or after in seen:
            raise SystemExit(f"{role} ask: invalid or repeated cursor")
        seen.add(after)
        body = {"ask": question, "after": after}


def _fetch(local, uri: str, digest: str, what: str) -> bytes:
    """The bytes of an object by its uri, which must hash to the digest that names them."""
    data = local.get(uri.split("/", 3)[3]) if uri.startswith("s3://") else None
    if data is None or sha256(data).hexdigest() != digest:
        raise SystemExit(f"{what}: missing object or wrong hash")
    return data


def _object(local, key: str, what: str) -> bytes:
    data = local.get(key)
    if data is None:
        raise SystemExit(f"{what}: {key} is missing")
    return data


def _holds_swept_value(rows, key: str, value: str) -> bool:
    """Return whether snapshot rows contain the swept cell key and value."""
    return isinstance(rows, list) and any(
        isinstance(row, dict) and row.get("key") == [key, value] for row in rows
    )


def _check_sweep_cell(reader, role: str, pack: str, sweep_name: object,
                      kind: object, slot: object, key: object, cell: object) -> None:
    """Verify one generic sweep cell has a computed status backed by its variant snapshot."""
    if not isinstance(cell, dict):
        raise SystemExit(f"{role} sweeps: sweep {sweep_name!r} has invalid cell {cell!r}")
    status = cell.get("status")
    if status == "unavailable":
        raise SystemExit(f"{role} sweeps: sweep {sweep_name!r} cell is unavailable")
    if status not in ("green", "warning", "red"):
        raise SystemExit(f"{role} sweeps: sweep {sweep_name!r} cell has non-computed status {status!r}")
    value = cell.get("value")
    if not isinstance(value, str):
        raise SystemExit(f"{role} sweeps: sweep {sweep_name!r} cell is missing value")
    if not all(isinstance(part, str) and part for part in (kind, slot, key)):
        raise SystemExit(f"{role} sweeps: sweep {sweep_name!r} is missing kind, slot or key")
    if status == "red":
        diagnosis = cell.get("diagnosis")
        if not isinstance(diagnosis, str) or not diagnosis:
            raise SystemExit(f"{role} sweeps: sweep {sweep_name!r} red cell is missing diagnosis")
        return
    manifest = cell.get("manifest")
    if not isinstance(manifest, str) or not manifest:
        raise SystemExit(f"{role} sweeps: sweep {sweep_name!r} computed cell is missing manifest")
    if reader is None:
        raise SystemExit(f"{role} sweeps: missing reader for sweep {sweep_name!r}")
    rows = reader.get(f"/{pack}/{manifest}/snapshots/{kind}__{slot}")
    if not _holds_swept_value(rows, key, value):
        raise SystemExit(f"{role} sweeps: {manifest} snapshot does not hold {key} = {value}")


def check_sweeps(reader, role: str, pack: str, sweeps: list[dict]) -> None:
    """Check that every generic sweep cell has a computed status backed by its variant snapshot."""
    if not isinstance(sweeps, list):
        raise SystemExit(f"{role} sweeps: expected a list, got {sweeps!r}")
    for sweep in sweeps:
        if not isinstance(sweep, dict):
            raise SystemExit(f"{role} sweeps: invalid sweep entry {sweep!r}")
        name = sweep.get("name")
        cells = sweep.get("cells")
        if not isinstance(cells, list) or not cells:
            raise SystemExit(f"{role} sweeps: sweep {name!r} has no cells")
        cell_ref = sweep.get("cell") if isinstance(sweep.get("cell"), dict) else {}
        kind = sweep.get("kind") or cell_ref.get("kind")
        slot = sweep.get("slot") or cell_ref.get("slot")
        key = sweep.get("key") or cell_ref.get("id")
        for cell in cells:
            _check_sweep_cell(reader, role, pack, name, kind, slot, key, cell)


def checked_local_grid(local, pack: str, position: str, base_epoch: int, count: int) -> dict:
    """Read the sweep grid of the base manifest and check every variant against it.

    Returns {False: sweeps, True: sweeps}: the grid as a role that does not read every relation sees it
    (a variant exposes nothing but its value, and each check is unavailable) and as a full reader sees it
    (status, checks and the link to the variant manifest or diagnosis).
    """
    base = f"m-{base_epoch}"
    raw = _object(local, f"{pack}/manifests/{base}.json", "base manifest")
    manifest = json.loads(raw)
    head = pointers.head(pack, raw)
    if head is None or local.get(head[0]) != head[1]:
        raise SystemExit(f"{base}: wrong head pointer")
    if manifest.get("id") != base or manifest.get("epoch") != base_epoch:
        raise SystemExit(f"{base}: manifest id or epoch mismatch")
    if not any(s.get("position") == position for s in manifest.get("sources", [])):
        raise SystemExit(f"{base}: manifest is not of position {position}")
    files = [f for f in manifest.get("compiled", []) if f.get("file") == "ir/sweeps.json"]
    if len(files) != 1:
        raise SystemExit(f"{base}: expected one compiled sweep grid")
    declared = json.loads(_fetch(local, files[0]["uri"], files[0]["sha256"], f"{base} sweep grid"))["sweeps"]
    names = [c["name"] for c in manifest.get("checks", [])]
    masked_checks = [{"name": name, "status": "unavailable"} for name in names]
    epoch = base_epoch + 1
    masked, full = [], []
    for sweep in declared:
        if sweep["count"] != count:
            raise SystemExit(f"sweep {sweep['name']}: expected {count} cells, the grid has {sweep['count']}")
        relation = f"{sweep['kind']}__{sweep['slot']}"
        cells_masked, cells_full = [], []
        for index in range(count):
            value = str(sweep["min"] + index * sweep["step"])
            vid = publish.variant_id(sweep["name"], index, epoch)
            cell = {"index": index, "value": value}
            cells_masked.append({**cell, "status": "unavailable", "checks": masked_checks})
            body = local.get(f"{pack}/manifests/{vid}.json")
            diagnosis = local.get(f"{pack}/diagnoses/{vid}.json")
            if body is None and diagnosis is None:
                cells_full.append({**cell, "status": "not_computed"})
                continue
            kind, data = ("manifests", body) if body is not None else ("diagnoses", diagnosis)
            if kind == "manifests":
                variant = json.loads(body)
                if (variant.get("id") != vid or variant.get("base_manifest") != base or variant.get("epoch") != epoch
                        or {k: (variant.get("variant") or {}).get(k) for k in ("sweep", "index", "value")}
                        != {"sweep": sweep["name"], "index": index, "value": value}):
                    raise SystemExit(f"{vid}: does not match its base and grid cell")
            expected = dict(pointers.pointers(pack, kind, data))
            pointer_key = f"{pack}/epochs/{epoch}/{kind}/{vid}.json"
            found = local.get(pointer_key)
            if found is None or json.loads(found) != json.loads(expected[pointer_key]):
                raise SystemExit(f"{vid}: wrong manifest pointer")
            if kind == "diagnoses":
                cells_full.append({**cell, "status": "red", "diagnosis": vid})
                continue
            held = False
            for snapshot in variant.get("snapshots", []):
                if snapshot.get("relation") != relation:
                    continue
                rows = json.loads(_fetch(local, snapshot["uri"], snapshot["sha256"], f"{vid} snapshot"))
                held = held or _holds_swept_value(rows, sweep["key"], value)
            if not held:
                raise SystemExit(f"{vid}: snapshot does not hold {sweep['key']} = {value}")
            checks = [{"name": c["name"], "status": c["status"]} for c in variant.get("checks", [])]
            status = max((c["status"] for c in checks), key=_ORDER.get, default="green")
            cells_full.append({**cell, "status": status, "checks": checks, "manifest": vid})
        head_of = {k: sweep[k] for k in ("name", "kind", "key", "slot")}
        masked.append({**head_of, "cells": cells_masked})
        full.append({**head_of, "cells": cells_full})
    return {False: masked, True: full}


def check_local_sweeps(role: str, seen: dict, grids: dict, full: bool) -> None:
    """Check the sweeps a role was shown against the grids read from the store."""
    shown = seen.get("sweeps")
    if not full:
        for sweep in shown or []:
            if any("manifest" in cell or "diagnosis" in cell for cell in sweep.get("cells", [])):
                raise SystemExit(f"{role} sweeps: a role that reads in part exposes a variant")
        if shown != grids[False]:
            raise SystemExit(f"{role} sweeps: masked sweep differs from the store")
    elif shown != grids[True]:
        raise SystemExit(f"{role} sweeps: computed sweep differs from the store")
