"""Read proposal files into the platform compiler for an offline preview."""

import argparse
from collections import defaultdict
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import re

from rezono_compiler import batch, calc, facts, pack, rules, scenarios
from rezono_compiler.sqltext import q


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"duplicate field {name!r}")
        result[name] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def fields(value, label, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - {*required, *optional}:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def name(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise ValueError(f"{label} must be a lowercase identifier")
    return value


def offers(catalog):
    rows = []
    for item, value in mapping(catalog["catalog"], "catalog items").items():
        name(item, "item")
        entry = fields(value, "catalog item", ("component", "sizes", "provisions"))
        name(entry["component"], "component")
        if not isinstance(entry["provisions"], list):
            raise ValueError("catalog provisions must be a list")
        for provision in entry["provisions"]:
            name(provision, "provision")
        for size, quantities in mapping(entry["sizes"], "catalog sizes").items():
            name(size, "size")
            if (not isinstance(quantities, list) or len(quantities) != 4
                    or any(type(n) is not int or n < 0 for n in quantities)):
                raise ValueError("a catalog size requires four nonnegative integer quantities")
            rows.append({"id": f"{item}/{size}", "item": item, "size": size, "monthly_cents": quantities[3]})
    return rows


def request_rows(teams_path, catalog):
    teams = mapping(catalog["teams"], "teams")
    profiles = mapping(catalog["profiles"], "profiles")
    for tenant, value in teams.items():
        name(tenant, "catalog tenant")
        entry = fields(value, "catalog team", ("key",))
        if entry["key"] != tenant:
            raise ValueError("catalog team key does not match its tenant identifier")
    for profile, value in profiles.items():
        name(profile, "catalog profile")
        entry = fields(value, "catalog profile", ("zone", "sizes", "unlisted"))
        name(entry["zone"], "profile zone")
        if not isinstance(entry["sizes"], list):
            raise ValueError("profile sizes must be a list")
        for size in entry["sizes"]:
            name(size, "profile size")
        if entry["unlisted"] not in ("review", "denied"):
            raise ValueError("profile decision must be review or denied")
    records = defaultdict(list)
    records["tenant_catalog_offer"] = offers(catalog)
    available = {(row["item"], row["size"]) for row in records["tenant_catalog_offer"]}
    for path in sorted(teams_path.rglob("request.json")):
        parts = path.relative_to(teams_path).parts
        if len(parts) != 3:
            raise ValueError("expected a request at teams/<tenant>/<service>/request.json")
        tenant, service = name(parts[0], "tenant"), name(parts[1], "service")
        if tenant not in teams:
            raise ValueError(f"unknown tenant {tenant!r}")
        request = fields(read_json(path), "request", ("profile", "items", "connections", "submittedAt"))
        profile = name(request["profile"], "profile")
        if profile not in profiles:
            raise ValueError(f"unknown profile {profile!r}")
        timestamp = request["submittedAt"]
        if not isinstance(timestamp, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", timestamp
        ):
            raise ValueError("submission time must be a UTC timestamp")
        datetime.fromisoformat(timestamp)
        request_id = f"{tenant}/{service}"
        scope = {"tenant": tenant, "service": service}
        records["tenant_service_request"].append(
            {"id": request_id, **scope, "profile": profile, "submitted_at": timestamp}
        )
        for item, value in mapping(request["items"], "request items").items():
            size = name(value, "requested size")
            if (item, size) not in available:
                raise ValueError(f"unknown catalog offer {item}/{size}")
            records["tenant_request_item"].append(
                {"id": f"{request_id}/{item}", **scope, "item": item, "size": size}
            )
        if not isinstance(request["connections"], list):
            raise ValueError("request connections must be a list")
        for index, value in enumerate(request["connections"], 1):
            connection = fields(value, "connection", ("targetZone", "target", "port"), ("peer",))
            target_zone = name(connection["targetZone"], "target zone")
            target = connection["target"]
            if not isinstance(target, str) or not target.strip():
                raise ValueError("connection target must be nonempty text")
            row = {"id": f"{request_id}/{index}", **scope, "target_zone": target_zone,
                   "target": target, "port": connection["port"]}
            if "peer" in connection:
                peer = name(connection["peer"], "peer")
                if peer not in teams:
                    raise ValueError(f"unknown peer {peer!r}")
                row["peer"] = peer
            records["tenant_request_connection"].append(row)
    return records


def preview_inputs(model, pack_path, teams_path, catalog_path):
    if not teams_path.is_dir():
        raise ValueError("teams must be a directory")
    catalog = fields(read_json(catalog_path), "catalog", ("teams", "profiles", "catalog"),
                     ("capacity", "zoneMatrix", "decisions", "bindings"))
    inputs = facts.rows_of(model, request_rows(teams_path, catalog))
    states = scenarios.states(model, pack_path)
    base = states[0][1] if states else {}
    return {table: base.get(table, []) + inputs.get(table, []) for table in sorted(base.keys() | inputs.keys())}


def relation_rows(model, rows, name):
    if not model.rules:
        raise ValueError("pack has no rule program")
    program = rules.load(model.rules)
    if name not in program.derived():
        raise ValueError(f"unknown derived relation {name!r}")
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    connection, _, _ = batch.run(model, program, rows, calculation)
    with closing(connection):
        return sorted(connection.execute(f"SELECT * FROM {q(name)}").fetchall())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inputs")
    commands.add_parser("relation").add_argument("name")
    args = parser.parse_args(argv)

    try:
        model = pack.read(args.pack)
        rows = preview_inputs(model, args.pack, args.teams, args.catalog)
        result = rows if args.command == "inputs" else relation_rows(model, rows, args.name)
        print(json.dumps(result, sort_keys=True, default=lambda value: value.isoformat()))
    except (OSError, ValueError, pack.CompileError, facts.LoadError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
