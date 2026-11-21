"""Parsing, canonical printing, and malformed-syntax diagnostics for `rezono 1` existential
and cardinality `require` declarations (decisions/language-requirements.md, section 1)."""

import json

import pytest
from reader_probe import read_modules

VALID_REQUIREMENTS = """\
rezono 1
pack sample

enum Flag = yes | no
enum Bus = bus_a | bus_b
enum Tier = critical | standard

kind Rack
  in_cage: Flag
kind PowerFeed
  rack: Rack
  bus: Bus
kind Service
  tier: Tier
  isolated: Flag
kind Replica
  service: Service
  healthy: Flag
kind Cluster
  active: Flag
kind Node
  cluster: Cluster
  role: Text
kind EgressRule
  service: Service
kind FactRecord
kind Origin
  fact: FactRecord
kind Conclusion
kind Witness
  conclusion: Conclusion
kind CmdbExport
kind Function

derived asks(a: Service, f: Function): Bool = true
derived provides(s: Service, f: Function): Bool = true

require active: rack.in_cage is known

require rack_dual_feed(r: Rack)
  when r.in_cage = yes
  exists feed_a: PowerFeed where feed_a.rack = r and feed_a.bus = bus_a
  exists feed_b: PowerFeed where feed_b.rack = r and feed_b.bus = bus_b
  means "{$r} in cage must have both feed A and feed B." @ dc-policy#power-1

require service_ha(s: Service)
  when s.tier = critical
  exists at least 3 r: Replica where r.service = s and r.healthy = yes
  means "{$s} must run at least 3 healthy replicas." @ slo#ha-3

require single_primary(c: Cluster)
  when c.active = yes
  exists exactly 1 n: Node where n.cluster = c and n.role = "primary"

require bounded_egress(s: Service)
  when s.isolated = yes
  exists at most 2 e: EgressRule where e.service = s

require fact_has_origin(f: FactRecord)
  exists o: Origin where o.fact = f

require conclusion_has_witness(c: Conclusion) invariant
  exists w: Witness where w.conclusion = c

require service_provider_exists(a: Service, f: Function)
  over asks(a, f)
  exists row in provides where row.f = f
"""

MISSING_EXISTS = """\
rezono 1
pack sample
kind Service
  tier: Text
require empty_req(s: Service)
  when s.tier = "critical"
"""

ZERO_AT_LEAST = """\
rezono 1
pack sample
kind Service
kind Replica
  service: Service
require vacuous_req(s: Service)
  exists at least 0 r: Replica where r.service = s
"""

MULTI_KEY_NO_OVER = """\
rezono 1
pack sample
kind Service
kind Function
kind Binding
  service: Service
  fn: Function
require pair_req(a: Service, f: Function)
  exists b: Binding where b.service = a and b.fn = f
"""

DUPLICATE_WHEN = """\
rezono 1
pack sample
kind Service
  tier: Text
kind Replica
  service: Service
require double_when(s: Service)
  when s.tier = "critical"
  when s.tier = "standard"
  exists r: Replica where r.service = s
"""

REZONO_0_REFUSED = """\
rezono 0
pack sample
kind Service world closed
kind Replica world closed
  service: Service
require service_ha(s: Service)
  exists at least 3 r: Replica where r.service = s
"""


class MissingRequirementSyntax(AssertionError):
    """The reader did not parse, round-trip, or validate rezono 1 `require` declarations."""


def test_rezono_1_requirement_parsing_and_diagnostics():
    valid, missing_exists, zero_at_least, multi_no_over, dup_when, v0_refused = read_modules(
        VALID_REQUIREMENTS,
        MISSING_EXISTS,
        ZERO_AT_LEAST,
        MULTI_KEY_NO_OVER,
        DUPLICATE_WHEN,
        REZONO_0_REFUSED,
    )
    problems = []
    if valid["diagnostics"] or valid["format"] != "rezono.module/5" or valid["module"] is None:
        problems.append({"valid": valid})
    else:
        decls = valid["module"]["decls"]
        plain_checks = [d for d in decls if d.get("check") == "require" and d.get("name") == "active"]
        if len(plain_checks) != 1:
            problems.append({"plain_require_check_collision": plain_checks})

        reqs = {d["require"]: d for d in decls if isinstance(d.get("require"), str)}
        expected_names = {
            "rack_dual_feed",
            "service_ha",
            "single_primary",
            "bounded_egress",
            "fact_has_origin",
            "conclusion_has_witness",
            "service_provider_exists",
        }
        if set(reqs) != expected_names:
            problems.append({"requirement_names": sorted(reqs), "expected": sorted(expected_names)})
        else:
            dual = reqs["rack_dual_feed"]
            if (
                len(dual.get("exists", [])) != 2
                or dual.get("means") != "{$r} in cage must have both feed A and feed B."
                or dual.get("source") != "dc-policy#power-1"
                or "when" not in dual
            ):
                problems.append({"rack_dual_feed": dual})

            ha = reqs["service_ha"]
            if ha.get("exists", [{}])[0].get("bound") != {"op": "at_least", "count": "3"}:
                problems.append({"service_ha_bound": ha})

            primary = reqs["single_primary"]
            if primary.get("exists", [{}])[0].get("bound") != {"op": "exactly", "count": "1"}:
                problems.append({"single_primary_bound": primary})

            egress = reqs["bounded_egress"]
            if egress.get("exists", [{}])[0].get("bound") != {"op": "at_most", "count": "2"}:
                problems.append({"bounded_egress_bound": egress})

            origin = reqs["fact_has_origin"]
            if "when" in origin or "bound" in origin.get("exists", [{}])[0]:
                problems.append({"fact_has_origin": origin})

            witness = reqs["conclusion_has_witness"]
            if witness.get("options") != [{"invariant": True}]:
                problems.append({"conclusion_has_witness_options": witness})

            provider = reqs["service_provider_exists"]
            if (
                provider.get("over") != {"relation": "asks", "args": ["a", "f"]}
                or provider.get("exists", [{}])[0].get("relation") != "provides"
            ):
                problems.append({"service_provider_exists": provider})

        if valid["printed"] is None:
            problems.append({"valid_printed": None})
        else:
            [reparsed] = read_modules(valid["printed"])
            if reparsed["diagnostics"] or reparsed["module"] != valid["module"]:
                problems.append({"roundtrip_mismatch": reparsed})

    for label, result in (
        ("missing_exists", missing_exists),
        ("zero_at_least", zero_at_least),
        ("multi_key_no_over", multi_no_over),
        ("duplicate_when", dup_when),
        ("rezono_0_refused", v0_refused),
    ):
        codes = [d["code"] for d in result["diagnostics"]]
        if result["module"] is not None or "R000" not in codes:
            problems.append({f"{label}_not_refused": result})

    if problems:
        raise MissingRequirementSyntax(json.dumps(problems, indent=2))
