"""Static IPv4 boundary-policy oracle for the synthetic platform."""


def firewall_expectations(inputs, relations):
    hosts = dict(relations["cluster_endpoint_host"])
    zones = dict(relations["cluster_endpoint_zone"])
    ranges = inputs["node_ranges"]
    addresses = inputs["endpoint_addresses"]
    protocols = inputs["protocols"]
    if set(ranges) != set(hosts.values()) or set(addresses) != set(hosts):
        raise ValueError("Declare every host range and endpoint address")
    previous = -1
    for lo, hi in sorted(ranges.values()):
        if type(lo) is not int or type(hi) is not int or not previous < lo <= hi < 2**32:
            raise ValueError("Invalid or overlapping IPv4 range")
        previous = hi
    if len(set(addresses.values())) != len(addresses):
        raise ValueError("Duplicate endpoint address")
    for name, addr in addresses.items():
        lo, hi = ranges[hosts[name]]
        if type(addr) is not int or not lo <= addr <= hi:
            raise ValueError("Endpoint address outside its host range")

    flows = sorted((a, b, f, protocols[f], port) for a, b, f, port in relations["cluster_flow"]
                   if zones[a] != zones[b])
    rules = []
    for a, b, f, proto, port in flows:
        lo, hi = ranges[hosts[a]]
        rules.append(dict(source=a, destination=b, function=f, sourceFrom=lo, sourceTo=hi,
                          destinationAddress=addresses[b], protocol=proto, fromPort=port, toPort=port))

    def matches(rule, src, dst, proto, port):
        return (rule["sourceFrom"] <= addresses[src] <= rule["sourceTo"]
                and addresses[dst] == rule["destinationAddress"] and proto == rule["protocol"]
                and rule["fromPort"] <= port <= rule["toPort"])

    desired = {(a, b, proto, port) for a, b, _, proto, port in flows}
    uncovered = sorted(row for row in desired if not any(matches(r, *row) for r in rules))
    unused = [r for r in rules if not any(matches(r, *row) for row in desired)]
    alternatives = set()
    for a, b, _, proto, port in flows:
        for src in hosts:
            if hosts[src] != hosts[a]:
                continue
            for dst in hosts:
                if dst != b and zones[dst] == zones[b] and zones[src] != zones[dst]:
                    alternatives.add((src, dst, proto, port))

    # Keep allowances inherited from another source distinct from true denials.
    residual = set()
    for rule in rules:
        dst = rule["destination"]
        for src in hosts:
            row = (src, dst, rule["protocol"], rule["fromPort"])
            if zones[src] != zones[dst] and row not in desired and matches(rule, *row):
                residual.add((*row, rule["source"], rule["function"]))
    negatives = sorted(row for row in alternatives - desired if not any(matches(r, *row) for r in rules))
    return {"rules": rules, "positiveCases": sorted(desired), "negativeCases": negatives,
            "excessEvidence": sorted(residual), "excessPairCount": len({row[:4] for row in residual}),
            "uncoveredCases": uncovered, "unusedRules": unused}
