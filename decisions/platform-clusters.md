# Cluster placement and fleet management

The cluster scenario replaces the baseline's shared control endpoint with one endpoint per Kubernetes cluster. Cluster identity, role and service placement are authored intent. Neither network reachability nor a product name establishes ownership. Use these inputs to explain reachability and to project firewall boundaries. Keep the original service example as a reproducible baseline.

| Role | Instance | Control host | Worker host |
| --- | --- | --- | --- |
| Fleet hub | hub | self | own machines |
| Shared services | base | self | own machines |
| Hosted control | management | self | own machines |
| VM infrastructure | virtualization | self | own machines |
| Application | production, development | management | virtualization |
| External storage | storage | none | storage machines |
| Build | build | self | own machines |
| Edge | edge | self | own machines |
| Recovery | recovery | self | own machines |

Separate build and edge clusters keep their workloads outside application and management hosts. Recovery owns its control plane and workers so loss of either host for application clusters does not prevent recovery. It remains a fleet member, with only its declared fleet connections. Ceph provides external storage and has no Kubernetes control plane or fleet agent. The example client is a simulated probe placed on edge with the external trust label.

Open Cluster Management and Argo CD are the candidate hub products. Cluster API and k0smotron provide hosted control, KubeVirt and its Cluster API provider supply virtual workers, and k0s supplies the application clusters. Keycloak and the other shared services occupy base. Products are inventory choices. Hosting and fleet rules use roles, with no product names in their conditions. Product capabilities and real port ranges require release-specific evidence. The transport table in the scenario contains synthetic test inputs only.

Each Kubernetes cluster owns one control endpoint. Its placement is physical hosting, distinct from ownership. A per-cluster agent on the workers registers with the hub, and the hub applies to that cluster's own control endpoint. Application workers contact their own hosted control. VM disks originate on the VM infrastructure. Persistent volumes originate with their owning workers. Both use the external storage endpoint. Endpoint trust follows the hosting infrastructure for hosted control and VM disks. Workload endpoints retain their logical tenant zone. Network allowances are projections of directional flows, with a separate set for same-zone traffic.

The fixture declares cluster rows, role-based service placement, storage use and synthetic transports. Standalone calculation derives endpoint placement, fleet membership and flows by joining these inputs. A service-level request for the control-plane function resolves to its own cluster. For the old shared control service, the management cluster's control endpoint takes its place. Every other service keeps its own identity. The baseline service facts and their original expectations stay available for comparison.

A future product substitution can be compared after both products have sourced capabilities. Comparing observed placement with desired placement requires a recorded run of this scenario with evidence for each discrepancy.
