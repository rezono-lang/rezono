"""Static IPv4 boundary-policy oracle for the synthetic platform."""


def firewall_expectations(inputs, relations, fixed=False):
    hosts = dict(relations["cluster_endpoint_network"])
    zones = dict(relations["cluster_endpoint_zone"])
    ranges = inputs["node_ranges"]
    addresses = inputs["endpoint_addresses"]
    protocols = inputs["protocols"]
    if set(ranges) != set(hosts.values()) or set(addresses) != set(hosts):
        raise ValueError("Declare every host range and endpoint address")
    egress_ranges = inputs["egress_ranges"]
    if egress_ranges.keys() != ranges.keys():
        raise ValueError("Declare an egress pool per network")
    previous = -1
    for lo, hi in sorted([*ranges.values(), *egress_ranges.values()]):
        if type(lo) is not int or type(hi) is not int or not previous < lo <= hi < 2**32:
            raise ValueError("Invalid or overlapping IPv4 range")
        previous = hi
    if len(set(addresses.values())) != len(addresses):
        raise ValueError("Duplicate endpoint address")
    for name, addr in addresses.items():
        lo, hi = ranges[hosts[name]]
        if type(addr) is not int or not lo <= addr <= hi:
            raise ValueError("Endpoint address outside its host range")

    source_addresses = addresses.copy()
    if fixed:
        required = {"addressFamily": "IPv4", "egressGateway": True, "bpfMasquerade": True,
                    "kubeProxyReplacement": True, "hostedKubeProxy": False}
        if inputs["fixed_source_features"] != required:
            raise ValueError("Fixed source simulation requires the declared IPv4 gateway features")
        overrides = inputs["fixed_source_addresses"]
        if set(overrides.values()) & set(addresses.values()) or len(set(overrides.values())) != len(overrides):
            raise ValueError("Egress addresses must be exclusive")
        for src, address in overrides.items():
            lo, hi = egress_ranges[hosts[src]]
            if type(address) is not int or not lo <= address <= hi:
                raise ValueError("Invalid egress address for source network")
        source_addresses.update(overrides)

    flows = sorted((a, b, f, protocols[f], port) for a, b, f, port in relations["cluster_flow"]
                   if zones[a] != zones[b])
    rules = []
    for a, b, f, proto, port in flows:
        lo, hi = ranges[hosts[a]]
        if fixed and a in overrides:
            lo = hi = source_addresses[a]
        rules.append(dict(source=a, destination=b, function=f, sourceFrom=lo, sourceTo=hi,
                          destinationAddress=addresses[b], protocol=proto, fromPort=port, toPort=port))

    def matches(rule, src, dst, proto, port):
        return (rule["sourceFrom"] <= source_addresses[src] <= rule["sourceTo"]
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
