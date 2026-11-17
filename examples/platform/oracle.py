"""An independent recomputation of the trial pack's derived relations.

Plain Python sets and no engine: it reads facts/core.yaml and applies the rules
of rules/core.dl by hand, one function per relation. It prints the number of
rows per relation and, with --write, stores the rows in oracle-rows.json.

    python oracle.py [--write]
"""

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
FACTS = yaml.safe_load((HERE / "facts" / "core.yaml").read_text())


def ids(kind):
    return {row["id"] for row in FACTS.get(kind, [])}


def attr(kind, name):
    return {(row["id"], row[name]) for row in FACTS.get(kind, []) if name in row}


def lookup(pairs):
    out = {}
    for key, value in pairs:
        out.setdefault(key, set()).add(value)
    return out


service_product = attr("service", "product")
service_role = attr("service", "role")
service_step = dict(attr("service", "step"))
role_zone = dict(attr("platform_role", "zone"))
role_cluster = dict(attr("platform_role", "cluster_class"))
role_runs_images = dict(attr("platform_role", "runs_images"))
recovery_allowed = dict(attr("function", "recovery_allowed"))
open_by_design = dict(attr("function", "open_by_design"))
offers = [(r["product"], r["function"], r["port"]) for r in FACTS.get("offer", [])]
demands = [(r["product"], r["function"]) for r in FACTS.get("demand", [])]
choices = [(r["service"], r["function"], r["provider"]) for r in FACTS.get("choice", [])]
releases = FACTS.get("release", [])
pins = [(r["service"], r["release"]) for r in FACTS.get("pin", [])]
artifacts = FACTS.get("artifact", [])
role_of = dict(service_role)

provides = {(s, f, p) for s, pr in service_product for opr, f, p in offers if opr == pr}
provider = {(s, f) for s, f, _ in provides}
asks = {(s, f) for s, pr in service_product for dpr, f in demands if dpr == pr}
chosen = {(s, f) for s, f, _ in choices}
providers = {f: len({s for s, g in provider if g == f}) for f in ids("function")}

needs = {(a, b, f) for a, f, b in choices if (a, f) in asks}
needs |= {
    (a, b, f)
    for a, f in asks
    if (a, f) not in chosen and providers.get(f) == 1
    for b, g in provider
    if g == f
}
ambiguous_provider = {(a, f) for a, f in asks if (a, f) not in chosen and providers.get(f, 0) > 1}
unmet_need = {(a, f) for a, f in asks if providers.get(f) == 0}

zone_of = {s: role_zone[r] for s, r in service_role if r in role_zone}
on_cluster = {s: role_cluster[r] for s, r in service_role if r in role_cluster}
must_separate = {(a, b) for a in on_cluster for b in on_cluster if on_cluster[a] != on_cluster[b]}

ports = lookup(((b, f), p) for b, f, p in provides)
flow = {(a, b, f, p) for a, b, f in needs for p in ports.get((b, f), ())}
crossing = {
    (a, b, zone_of[a], zone_of[b], p)
    for a, b, _, p in flow
    if a in zone_of and b in zone_of and zone_of[a] != zone_of[b]
}
firewall_rule = {(za, zb, p) for _, _, za, zb, p in crossing}
in_zone_policy = {
    (a, b, p) for a, b, _, p in flow if a in zone_of and b in zone_of and zone_of[a] == zone_of[b]
}
flow_from_step = {
    (a, b, max(service_step[a], service_step[b]))
    for a, b, _ in needs
    if a in service_step and b in service_step
}

stable_release = {
    (r["id"], r["product"], r["released_on_day"]) for r in releases if r.get("stable") == "yes"
}
newest_day = {}
for _, product, day in stable_release:
    newest_day[product] = max(day, newest_day.get(product, day))
pinned = {s for s, _ in pins}
runs = set(pins)
runs |= {
    (s, r)
    for s, product in service_product
    if s not in pinned and product in newest_day
    for r, p, d in stable_release
    if p == product and d == newest_day[product]
}
release_product = {r["id"]: r["product"] for r in releases}
release_day = {r["id"]: r["released_on_day"] for r in releases}
behind_newest = {
    (s, r)
    for s, r in runs
    if r in release_day
    and release_product[r] in newest_day
    and release_day[r] < newest_day[release_product[r]]
}

outside_reaches_inside = {(a, b) for a, b, za, zb, _ in crossing if za == "external" and zb != "entry"}
recovery_reached = {(a, b) for a, b, _, zb, _ in crossing if zb == "recovery"}
recovery_reaches_out = {
    (a, b, f)
    for a, b, f, _ in flow
    if zone_of.get(a) == "recovery"
    and b in zone_of
    and zone_of[b] != "recovery"
    and recovery_allowed.get(f) == "no"
}
authenticates = {s for s, f in asks if f == "identity"} | {s for s, f in provider if f == "identity"}
unauthenticated_target = {
    (b, f)
    for _, b, _, _, p in crossing
    for s, f, q in provides
    if s == b and q == p and open_by_design.get(f) == "no" and b not in authenticates
}
verified = {
    a["for_service"]
    for a in artifacts
    if role_of.get(a["built_by"]) == "build" and a.get("signed") == "yes"
}
unverified_supply = {
    s for s, r in service_role if role_runs_images.get(r) == "yes" and s not in verified
}
build_reaches_tenant = {
    (a, b) for a, b, _, _ in flow if role_of.get(a) == "build" and zone_of.get(b) == "tenant"
}

RELATIONS = {
    "provides": provides,
    "asks": asks,
    "needs": needs,
    "ambiguous_provider": ambiguous_provider,
    "unmet_need": unmet_need,
    "zone_of": set(zone_of.items()),
    "on_cluster": set(on_cluster.items()),
    "flow": flow,
    "crossing": crossing,
    "firewall_rule": firewall_rule,
    "in_zone_policy": in_zone_policy,
    "flow_from_step": flow_from_step,
    "runs": runs,
    "behind_newest": behind_newest,
    "outside_reaches_inside": outside_reaches_inside,
    "recovery_reached": recovery_reached,
    "recovery_reaches_out": recovery_reaches_out,
    "unauthenticated_target": unauthenticated_target,
    "unverified_supply": {(s,) for s in unverified_supply},
    "build_reaches_tenant": build_reaches_tenant,
}


def rows(relation):
    return sorted(list(row) for row in relation)


if __name__ == "__main__":
    for name, relation in RELATIONS.items():
        print(f"{name}\t{len(relation)}")
    if "--write" in sys.argv:
        out = {name: rows(relation) for name, relation in RELATIONS.items()}
        (HERE / "oracle-rows.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
