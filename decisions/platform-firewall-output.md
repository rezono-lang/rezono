# How to emit firewall rules

Emit cross-zone allowances as a UTF-8 JSON array of objects with sourceZone, destinationZone, protocol, fromPort and toPort. Sort by these fields in that order, deduplicate identical objects and treat both port bounds as inclusive. Obtain protocol and range from versioned product evidence. A lone port has equal bounds. Never guess protocol from a port number.

For in-zone pod traffic, use Kubernetes networking.k8s.io/v1 NetworkPolicy. Give each modeled zone its own namespace and identify pods by the rezono.org/service label. Emit a namespace-wide baseline selecting all pods with both ingress and egress isolation, then matching ingress and egress allowances for the exact peer and transport. Set endPort only for a range. Service and namespace labels are prerequisites for applying these example policies. Cross-zone enforcement belongs at the firewall. A single vendor configuration would bind the example to a particular firewall.
