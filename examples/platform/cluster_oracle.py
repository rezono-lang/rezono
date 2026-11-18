"""Compute the synthetic cluster scenario independently from the engine."""


def cluster_relations(scenario, services, baseline_flow, baseline_zones):
    clusters = scenario["clusters"]
    placement = scenario["service_clusters"]
    ports = scenario["transports"]
    if set(placement) != services or not set(placement.values()) <= clusters.keys():
        raise ValueError("Every service needs one known cluster")

    def unique_host(role):
        host, = (name for name, value in clusters.items() if value == role)
        return host

    hub = unique_host("hub")
    management = unique_host("management")
    virtualization = unique_host("virtualization")
    storage = unique_host("storage")
    control_hosts = {}
    worker_hosts = {}
    members = set()
    endpoints = {}
    zones = {}
    networks = {}
    flows = set()

    def endpoint(name, host, zone=None, network=None):
        endpoints[name] = host
        networks[name] = network or host
        zones[name] = zone or scenario["zones"][clusters[host]]
        return name

    fleet = endpoint("fleet-hub", hub)
    disks = endpoint("storage-data", storage)
    for service, cluster in placement.items():
        if service == "cp":
            continue  # The management control endpoint represents the baseline control service.
        zone = baseline_zones[service] if service == "user" else None
        endpoint(service, cluster, zone)
    for cluster, role in clusters.items():
        if role == "storage":
            continue
        hosted = role == "application"
        control_host = management if hosted else cluster
        worker_host = virtualization if hosted else cluster
        control_hosts[cluster] = control_host
        worker_hosts[cluster] = worker_host
        members.add((cluster, hub))
        control = endpoint(f"control-{cluster}", control_host)
        agent = endpoint(f"agent-{cluster}", worker_host, scenario["zones"][role], network=cluster)
        worker = endpoint(f"workers-{cluster}", worker_host, scenario["zones"][role], network=cluster)
        flows.add((agent, fleet, "fleet-registration", ports["fleet-registration"]))
        flows.add((fleet, control, "fleet-apply", ports["fleet-apply"]))
        if hosted:
            flows.add((worker, control, "control-plane", ports["control-plane"]))
        for use in scenario["storage_uses"].get(cluster, []):
            if use == "vm-disk":
                source = endpoint(f"disk-{cluster}", worker_host)
            elif use == "persistent-volume":
                source = worker
            else:
                raise ValueError(f"Unknown storage use: {use}")
            flows.add((source, disks, use, ports[use]))

    for source, target, function, port in baseline_flow:
        consumer_cluster = placement[source]
        if source == "cp":
            source = f"control-{consumer_cluster}"
        if function == "control-plane":
            # The consumer owns the control endpoint, regardless of its physical host.
            target = f"control-{consumer_cluster}"
        flows.add((source, target, function, port))

    machines = {(f"node-{cluster}", cluster, worker_hosts[cluster]) for cluster in worker_hosts}
    stack = scenario["machine_stack"]
    network = scenario["network_stack"]
    return {
        "cluster_endpoint_network": set(networks.items()),
        "cluster_network_stack": {(cluster, network["policy"], network["observation"]) for cluster in control_hosts},
        "cluster_machine_stack": {(name, owner, host, stack["os"], stack["distribution"],
                                   f"{name}.{stack['bootstrap_extension']}") for name, owner, host in machines},
        "cluster_worker_interface": {(name, owner, "secondary" if owner != host else "native")
                                     for name, owner, host in machines},
        "cluster_service_placement": set(placement.items()),
        "cluster_control_host": set(control_hosts.items()),
        "cluster_worker_host": set(worker_hosts.items()),
        "cluster_fleet_member": members,
        "cluster_endpoint_host": set(endpoints.items()),
        "cluster_endpoint_zone": set(zones.items()),
        "cluster_flow": flows,
        "cluster_firewall_rule": {(zones[a], zones[b], port) for a, b, _, port in flows
                                  if zones[a] != zones[b]},
        "cluster_in_zone_policy": {(a, b, port) for a, b, _, port in flows
                                   if zones[a] == zones[b]},
    }
