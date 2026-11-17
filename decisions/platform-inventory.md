# Reference platform inventory

The example models a small Kubernetes platform with Ceph storage and Keycloak identity. The fixture declares the following service instances. Separate database instances demonstrate explicit provider choice. Two application environments and two recovery workloads exercise isolation and supply checks.

| Service | Product | Role | First step |
| --- | --- | --- | --- |
| user | client | outside | 1 |
| lb | loadbalancer | entry | 1 |
| idp | keycloak | shared | 1 |
| db-idp | postgresql | shared | 1 |
| db-git | postgresql | shared | 1 |
| dns | coredns | shared | 1 |
| time | chrony | shared | 1 |
| reg | registry | shared | 1 |
| vault | openbao | shared | 1 |
| cp | kube-control | control | 1 |
| gitops | argocd | shared | 1 |
| git | forgejo | shared | 1 |
| store | ceph | storage | 1 |
| sign | signer | shared | 1 |
| build | builder | build | 1 |
| shop | app | workload-prod | 1 |
| lab | app | workload-dev | 2 |
| restore | recovery-env | recovery | 2 |
| restore-bad | app | recovery | 2 |

The twelve authored kinds are zone and cluster class (placement vocabulary), platform role (placement mapping), function (capability and policy), product, offer and demand (product knowledge), service (deployment intent), choice (provider selection), release and pin (version selection), and artifact (build evidence). These inputs carry information that the derived flow and placement relations cannot establish. Product offers, demands and releases in this baseline are illustrative fixtures pending release-specific evidence.
