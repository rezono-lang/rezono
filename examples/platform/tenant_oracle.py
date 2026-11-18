"""Reference calculation for file-based tenant requests. Prices are integer EUR cents."""

import json
import re
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
DIMENSIONS = ("cores", "memoryGiB", "storageGiB")


def load_requests(directory):
    requests = []
    for path in sorted(directory.glob("*/*/request.json")):
        team, service, _ = path.relative_to(directory).parts
        requests.append(dict(json.loads(path.read_text()), team=team, service=service))
    return requests


def landed_usage(model):
    """Return trusted landed usage, or None when the inventory is unmeasured."""
    if "landedDeliveries" not in model:
        return None
    receipts = model["landedDeliveries"]
    if not isinstance(receipts, list):
        raise ValueError("landedDeliveries must be a list")
    usage = {}
    for receipt in receipts:
        ident = receipt["request"]
        if ident in usage or not re.fullmatch(r"[0-9a-f]{40}", receipt["revision"]):
            raise ValueError("Expected a unique delivery with a pinned landing revision")
        amounts = {dim: receipt[dim] for dim in DIMENSIONS}
        if any(type(value) is not int or value < 0 for value in amounts.values()):
            raise ValueError("Landed quantities must be nonnegative integers")
        usage[ident] = amounts
    return usage


def calculate(model, requests):
    capacities = model["capacity"]
    matrix = {tuple(row) for row in model["zoneMatrix"]}
    decisions = {tuple(row) for row in model["decisions"]}
    rows = {key: [] for key in ("capacity", "shortages", "monthlyCost", "deliveries",
                                "connections", "isolationFindings", "catalog", "proposal", "scope", "placements", "applicationTargets")}
    charged = landed_usage(model)
    totals = {dim: None if charged is None else sum(row[dim] for row in charged.values())
              for dim in DIMENSIONS}
    projected = totals.copy()
    requirements = {}
    shortages = Counter()
    costs = dict.fromkeys(model["teams"], 0)
    orders = {}
    links = set()
    resources = {}
    sequence = Counter()
    identities = set()
    for request in sorted(requests, key=lambda r: (r["submittedAt"], r["team"], r["service"])):
        team = request["team"]
        identity = (team, request["service"])
        if identity in identities:
            raise ValueError("More than one proposal for the same request")
        identities.add(identity)
        profile = model["profiles"][request["profile"]]
        sequence[team] += 1
        seq = sequence[team]
        key = f"{model['teams'][team]['key']}-{seq}"
        if key in orders:
            raise ValueError("Repeated delivery identity")
        orders[key] = request
        amounts_by_dimension = dict.fromkeys(DIMENSIONS, 0)
        requirements[key] = amounts_by_dimension
        for item, size in request["items"].items():
            if size not in profile["sizes"]:
                raise ValueError("Size unavailable in selected profile")
            product = model["catalog"][item]
            *amounts, cents = product["sizes"][size]
            if any(type(n) is not int or n < 0 for n in [*amounts, cents]):
                raise ValueError("Catalog quantities and cents must be nonnegative integers")
            for dimension, amount in zip(DIMENSIONS, amounts, strict=True):
                amounts_by_dimension[dimension] += amount
            costs[team] += cents
            component = product["component"]
            resources[f"{key}/{component}"] = (team, profile["zone"])
            rows["deliveries"].append([team, key, component, item, size])
            for resource in product["provisions"]:
                rows["placements"].append([team, key, resource, component])
        for artifact, scope in model["bindings"].items():
            rows["scope"].append([team, artifact, team if scope == "tenant" else key])
        rows["applicationTargets"].append([team, key])
        for connection in request["connections"]:
            links.add((key, connection["target"], connection["port"]))

    for key, request in orders.items():
        team = request["team"]
        profile = model["profiles"][request["profile"]]
        states = set()
        for conn in request["connections"]:
            target, port = conn["target"], conn["port"]
            peer, zone = resources.get(target, (None, conn["targetZone"]))
            if "peer" in conn and peer != conn["peer"]:
                raise ValueError("Requested resource has no matching owner")
            status = "standard" if (profile["zone"], zone, port) in matrix else profile["unlisted"]
            reason = "matrix" if status == "standard" else "profile"
            if peer is not None and peer != team:
                remote = target.split("/")[0]
                reciprocal = any(s == remote and t.startswith(key + "/") and p == port for s, t, p in links)
                approved = (key, target, port) in decisions
                if not (reciprocal and approved):
                    status, reason = "denied", "isolation"
                    rows["isolationFindings"].append([team, key, target, port, reciprocal, approved])
            states.add(status)
            rows["connections"].append([team, key, target, port, status, reason])
        outcome = "denied" if "denied" in states else "review" if "review" in states else "standard"
        if outcome != "denied" and charged is None:
            outcome = "unknown"
        elif outcome != "denied":
            ident = f"{team}/{request['service']}"
            existing = charged.get(ident, {})
            candidate = {dim: projected[dim] - existing.get(dim, 0) + requirements[key][dim]
                         for dim in DIMENSIONS}
            for pool, limits in capacities.items():
                for dim, limit in limits.items():
                    excess = candidate[dim] - limit
                    if excess > 0:
                        shortages[pool, dim] = max(shortages[pool, dim], excess)
                        outcome = "denied"
            if outcome == "standard":
                projected = candidate
        rows["proposal"].append([team, key, outcome])
        entity = {"apiVersion": "backstage.io/v1alpha1", "kind": "Component",
                  "metadata": {"namespace": team, "name": request["service"]},
                  "spec": {"type": "service", "owner": f"group:{team}/{team}",
                           "lifecycle": request["profile"]}}
        rows["catalog"].append([team, key, entity])
    for pool, limits in capacities.items():
        for dimension, limit in limits.items():
            rows["capacity"].append([pool, dimension, totals[dimension], limit])
    rows["shortages"] = [[pool, dim, amount] for (pool, dim), amount in shortages.items()]
    rows["monthlyCost"] = [[team, amount, "EUR-cent"] for team, amount in costs.items()]
    rows["scope"] = [list(row) for row in set(map(tuple, rows["scope"]))]
    return {name: sorted(relation) for name, relation in rows.items()}


def tenant_publication(results, team):
    """Publish tenant-owned proposal rows only. Capacity totals have platform scope."""
    visible = ("monthlyCost", "deliveries", "connections", "isolationFindings", "catalog",
               "proposal", "scope", "placements", "applicationTargets")
    return {name: [row for row in results[name] if row[0] == team] for name in visible}


def scenarios():
    model = json.loads((HERE / "tenant-catalog.json").read_text())
    requests = load_requests(HERE / "teams")
    extra = json.loads((HERE / "tenant-scenarios/third-request.json").read_text())
    return {"requested": calculate(model, requests), "third": calculate(model, requests + [extra])}


if __name__ == "__main__":
    print(json.dumps(scenarios(), indent=2, sort_keys=True))
