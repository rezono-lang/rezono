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


DIMENSIONS = ("cores", "memoryGiB", "storageGiB")
RESOURCE_FIELDS = ("cores", "memory_gib", "storage_gib")


def sequence(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def quantity(value):
    if type(value) is not int or value < 0:
        raise ValueError("resource amounts must be nonnegative integers")
    return value


def dimension(value):
    if value not in DIMENSIONS:
        raise ValueError(f"unknown resource dimension {value!r}")
    return value


def port_number(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError("connection port must be an integer from 1 to 65535")
    return value


def target_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("connection target must be nonempty text")
    return value


def catalog_rows(catalog):
    rows = defaultdict(list)
    for item, value in mapping(catalog["catalog"], "catalog items").items():
        name(item, "item")
        entry = fields(value, "catalog item", ("component", "sizes", "provisions"))
        rows["tenant_catalog_item"].append({
            "id": item, "component": name(entry["component"], "component"),
            "provision": [name(p, "provision") for p in sequence(entry["provisions"], "catalog provisions")],
        })
        for size, quantities in mapping(entry["sizes"], "catalog sizes").items():
            name(size, "size")
            if (not isinstance(quantities, list) or len(quantities) != 4
                    or any(type(n) is not int or n < 0 for n in quantities)):
                raise ValueError("a catalog size requires four nonnegative integer quantities")
            rows["tenant_catalog_offer"].append({
                "id": f"{item}/{size}", "item": item, "size": size, "monthly_cents": quantities[3],
                **dict(zip(RESOURCE_FIELDS, quantities[:3], strict=True)),
            })
    for pool, limits in mapping(catalog.get("capacity", {}), "capacity").items():
        name(pool, "capacity pool")
        for key, amount in mapping(limits, "pool capacity").items():
            rows["tenant_pool_limit"].append({
                "id": f"{pool}/{key}", "pool": pool, "dimension": dimension(key), "amount": quantity(amount),
            })
    for link in sequence(catalog.get("zoneMatrix", []), "zone matrix"):
        if not isinstance(link, list) or len(link) != 3:
            raise ValueError("a zone matrix entry requires source, target and port")
        source, target, port = name(link[0], "source zone"), name(link[1], "target zone"), port_number(link[2])
        rows["tenant_zone_link"].append({
            "id": f"{source}/{target}/{port}", "source": source, "target": target, "port": port,
        })
    inventory_present = "landedDeliveries" in catalog
    rows["tenant_landed_delivery"] = landed_deliveries(catalog["landedDeliveries"]) if inventory_present else []
    rows["tenant_landed_inventory"] = [{
        "id": "landed-deliveries", "state": "complete" if inventory_present else "unknown",
    }]
    add_review_inputs(rows, catalog)
    rows["tenant_quota"] = readable_quotas(catalog)
    for artifact, scope in mapping(catalog.get("bindings", {}), "catalog bindings").items():
        if scope not in ("tenant", "delivery"):
            raise ValueError("catalog binding scope must be tenant or delivery")
        rows["tenant_binding"].append({"id": name(artifact, "binding artifact"), "scope": scope})
    return rows


def landed_deliveries(values):
    rows = []
    seen = set()
    for value in sequence(values, "landed deliveries"):
        receipt = fields(value, "landed delivery", ("request", "revision", *DIMENSIONS))
        request, revision = receipt["request"], receipt["revision"]
        if not isinstance(request, str) or len(request.split("/")) != 2:
            raise ValueError("landed delivery requires a team/service request identifier")
        for part in request.split("/"):
            name(part, "landed request identifier")
        if request in seen or not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("landed deliveries require unique requests and full merge revisions")
        seen.add(request)
        rows.append({
            "id": request, "revision": revision,
            **{field: quantity(receipt[key]) for field, key in zip(RESOURCE_FIELDS, DIMENSIONS, strict=True)},
        })
    return rows


def add_review_inputs(rows, catalog):
    grants = defaultdict(list)
    for grant in sequence(catalog.get("reviewGrants", []), "review grants"):
        if not isinstance(grant, list) or len(grant) != 2:
            raise ValueError("a review grant requires a reviewer and an action")
        grants[name(grant[0], "reviewer")].append(name(grant[1], "review action"))
    rows["tenant_reviewer"] = [{"id": reviewer, "action": actions} for reviewer, actions in grants.items()]
    for value in sequence(catalog.get("decisionsByReviewer", []), "review decisions"):
        decision = fields(value, "review decision", ("reviewer", "sourceDelivery", "target", "port"))
        reviewer = name(decision["reviewer"], "reviewer")
        delivery = name(decision["sourceDelivery"], "source delivery")
        target, port = target_text(decision["target"]), port_number(decision["port"])
        row = {"id": f"{reviewer}/{delivery}/{port}/{target}", "reviewer": reviewer,
               "source_delivery": delivery, "target": target, "port": port}
        source = delivery_reference(delivery, catalog)
        if source is not None:
            row["source_tenant"], row["source_number"] = source
        rows["tenant_review_decision"].append(row)


def delivery_reference(text, catalog):
    """Bind a delivery display key, the tenant's catalog key and a one-based ordinal, to its tenant."""
    key, separator, number = text.rpartition("-")
    if not separator or not re.fullmatch(r"[1-9][0-9]*", number):
        return None
    tenants = [tenant for tenant, entry in mapping(catalog["teams"], "teams").items()
               if isinstance(entry, dict) and entry.get("key") == key]
    return (tenants[0], int(number)) if len(tenants) == 1 else None


def names_tenant(text, catalog):
    """A target segment that is a tenant's catalog key, or begins with one and a hyphen, refers to that tenant."""
    keys = {entry.get("key") for entry in mapping(catalog["teams"], "teams").values() if isinstance(entry, dict)}
    return any(isinstance(key, str) and (text == key or text.startswith(key + "-")) for key in keys)


def readable_quotas(catalog):
    rows = []
    seen = set()
    for value in sequence(catalog.get("readableQuotas", []), "readable quotas"):
        quota = fields(value, "readable quota", ("id", "owner", "dimension", "amount"))
        identifier = name(quota["id"], "quota identifier")
        if identifier in seen:
            raise ValueError(f"duplicate quota identifier {identifier!r}")
        seen.add(identifier)
        owner = name(quota["owner"], "quota owner")
        if owner not in catalog["teams"]:
            raise ValueError(f"unknown quota owner {owner!r}")
        rows.append({
            "id": identifier, "owner": owner,
            "dimension": dimension(quota["dimension"]), "amount": quantity(quota["amount"]),
        })
    return rows


def request_rows(teams_path, catalog):
    teams = mapping(catalog["teams"], "teams")
    profiles = mapping(catalog["profiles"], "profiles")
    records = catalog_rows(catalog)
    for tenant, value in teams.items():
        name(tenant, "catalog tenant")
        entry = fields(value, "catalog team", ("key",))
        if entry["key"] != tenant:
            raise ValueError("catalog team key does not match its tenant identifier")
    for profile, value in profiles.items():
        name(profile, "catalog profile")
        entry = fields(value, "catalog profile", ("zone", "sizes", "unlisted"))
        if entry["unlisted"] not in ("review", "denied"):
            raise ValueError("profile decision must be review or denied")
        records["tenant_profile"].append({
            "id": profile, "zone": name(entry["zone"], "profile zone"), "unlisted": entry["unlisted"],
            "size": [name(size, "profile size") for size in sequence(entry["sizes"], "profile sizes")],
        })
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
            target = target_text(connection["target"])
            port = port_number(connection["port"])
            row = {"id": f"{request_id}/{index}", **scope, "target_zone": target_zone,
                   "target": target, "port": port}
            delivery, _, component = target.partition("/")
            if names_tenant(delivery, catalog):
                row["target_reference"] = delivery
            owner = delivery_reference(delivery, catalog)
            if owner is not None:
                row["target_tenant"], row["target_number"] = owner
                if component:
                    row["target_component"] = component
            if "peer" in connection:
                peer = name(connection["peer"], "peer")
                if peer not in teams:
                    raise ValueError(f"unknown peer {peer!r}")
                row["peer"] = peer
            records["tenant_request_connection"].append(row)
    add_request_order_keys(records["tenant_service_request"])
    return records


def add_request_order_keys(requests):
    """Encode independent ordering fields without assigning an ordinal to any request."""
    instants = [(request, submission_instant(request["submitted_at"])) for request in requests]
    global_times = ordering_keys(instant for _, instant in instants)
    tenants = ordering_keys(request["tenant"] for request in requests)
    global_services = ordering_keys(request["service"] for request in requests)
    by_tenant = defaultdict(list)
    for request, instant in instants:
        request["global_submitted_at_key"] = global_times[instant]
        request["tenant_key"] = tenants[request["tenant"]]
        request["global_service_key"] = global_services[request["service"]]
        by_tenant[request["tenant"]].append((request, instant))
    for tenant_requests in by_tenant.values():
        time_keys = ordering_keys(instant for _, instant in tenant_requests)
        service_keys = ordering_keys(request["service"] for request, _ in tenant_requests)
        for request, instant in tenant_requests:
            request["submitted_at_key"] = time_keys[instant]
            request["service_key"] = service_keys[request["service"]]


def ordering_keys(values):
    return {value: index for index, value in enumerate(sorted(set(values)))}


def submission_instant(timestamp):
    whole, _, fraction = timestamp.removesuffix("Z").partition(".")
    return whole, fraction.rstrip("0")


def preview_inputs(model, pack_path, teams_path, catalog_path):
    if not teams_path.is_dir():
        raise ValueError("teams must be a directory")
    catalog = fields(read_json(catalog_path), "catalog", ("teams", "profiles", "catalog"),
                     ("capacity", "zoneMatrix", "decisions", "bindings", "landedDeliveries",
                      "reviewGrants", "decisionsByReviewer", "readableQuotas"))
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
        result = connection.execute(f"SELECT * FROM {q(name)}").fetchall()
    if name == "tenant_delivery_scope":
        result = [
            (tenant, artifact, tenant if number == 0 else f"{tenant}-{number}")
            for tenant, artifact, number in result
        ]
    elif name == "tenant_connection_review":
        result = [(team, f"{team}-{number}", *rest) for team, number, *rest in result]
    return sorted(result)


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
