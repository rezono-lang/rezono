# Profile `kubernetes`: the manifests

The target profile ([operations](../../../docs/operations.md#profiles)) as Kustomize manifests: the same containers as on `edge`, on any conformant Kubernetes (OpenShift, Rancher, a plain cluster), with plain Kubernetes features only. The profile's data (roles, storage, Git host) stays in [`../kubernetes.yaml`](../kubernetes.yaml); this directory is how it runs. An installation builds its viewer for [`../kubernetes-gate.yaml`](../kubernetes-gate.yaml), which is `kubernetes` plus the gate: a name of its own because `kubernetes` stays the viewer's default profile for development and its tests, which read the example data without a gate.

```
browser ──> Gateway (the platform's; TLS) ──HTTPRoute──> front :4180 (oauth2-proxy: OIDC login, passes the ID token)
                                                           └──> viewer :3000 (adapter-node) ──> gate :8080 (verifies the token, decides the role)
                                                                                                  ├──> store (S3 API, read-only keys)
                                                                                                  ├──> Git host API (components/propose: dispatch only)
                                                                                                  └──> engine 127.0.0.1:8091 (components/live: same pod)
```

| Path | What |
|---|---|
| [`base/`](base/kustomization.yaml) | the namespace (Pod Security `restricted`), the front, the viewer, the gate, their Services, the NetworkPolicies (deny all, then each hop), the ExternalSecrets and the HTTPRoute |
| [`components/propose/`](components/propose/kustomization.yaml) | proposals: the gate's dispatch token (it may only start workflows and read pull requests) |
| [`components/live/`](components/live/kustomization.yaml) | live `suppose`: the engine of [`deploy/engine`](../../engine/README.md) as a second container in the gate's pod, on loopback only, with its deploy key and read-only store keys |
| [`overlays/example/`](overlays/example/kustomization.yaml) | one installation with placeholder values under `example.org` and placeholder image digests |
| [`overlays/kind/`](overlays/kind/kustomization.yaml) | the installation the run brings up on a local cluster: the base without components, every egress rule narrowed to where it goes |
| [`run/`](run/README.md) | the run: `run/kind.sh` brings the profile up on a plain local cluster (kind), publishes the profile's packs and reads them through the front door |
| [`policy/`](policy/) | the policies every render must meet (Rego, run by conftest) and their unit tests |
| [`check.sh`](check.sh) | render, validate, hold to the policies; in CI as the workflow `kubernetes` |
| [`deploy/gate`](../../gate/Containerfile), [`deploy/viewer`](../../viewer/Containerfile), [`deploy/engine`](../../engine/Containerfile) | the images' recipes, each with the `.dockerignore` that lets in only what the image is made of |

**Why these choices.** An overlay composes the base with the components it wants, and an overlay without a component is the base (the empty overlay is the identity, AGENTS.md rule 4). The engine sits beside the gate because it holds the complete facts and must be reached by its own gate only: on loopback no other pod can reach it and no certificate is needed (the gate accepts loopback, or https with a token). The front is oauth2-proxy, an existing component (rule 7): it turns the platform's login into the bearer token the gate already verifies, so the gate stays the only place that decides a role. Every secret is an ExternalSecret against the platform's store; no value is in Git.

## The check

```sh
deploy/profiles/kubernetes/check.sh            # every overlay; warnings (placeholder digests) do not fail
deploy/profiles/kubernetes/check.sh --live my  # one overlay of a real installation: a warning fails too
deploy/profiles/kubernetes/check.sh --live ../platform/rezono  # an overlay outside overlays/, by its directory
```

1. **Render twice** with Kustomize and require the same bytes (non-negotiable 6).
2. **kubeconform `--strict`** against the schemas of Kubernetes 1.34 and of the CRDs used (ExternalSecret, HTTPRoute), read from pinned commits of `yannh/kubernetes-json-schema` and `datreeio/CRDs-catalog`: an unknown or invalid field fails.
3. **conftest** with the policies below; then `conftest verify` runs their unit tests (`policy/*_test.rego`: one passing input and one refused change per rule).
4. **The gate's packs** against `packs.rego`: the render, the profile and every `pack.yaml` in one input, so the gate of each overlay serves exactly the packs the profile publishes, for exactly the roles it publishes for a reader (`REZONO_ROLES`, RV-S21).
5. **The images' recipes** (`deploy/*/Containerfile`) against `containerfile.rego`, and **the two profiles** against `profiles.rego`: static checks, before any image is built.

The tools (Kustomize 5.8.3, kubeconform 0.8.0, conftest 0.71.1) are pinned by version and SHA-256 and downloaded once on linux-amd64; on another platform `KUSTOMIZE`, `KUBECONFORM` and `CONFTEST` name binaries to use. The check reads and renders only; it never talks to a cluster.

## The policies

A failed policy blocks; a warning (the placeholder digest) only warns, except with `--live`.

| File | Refuses |
|---|---|
| [`images.rego`](policy/images.rego) | an image not pinned by digest (`name@sha256:<64 hex>`); warns on the zero digest of an image not built yet |
| [`pods.rego`](policy/pods.rego) | host namespaces and hostPath; a Kubernetes API token in a pod; root, a missing `runAsNonRoot` or seccomp profile; privilege escalation, privileged containers, a writable root filesystem, a capability kept or added; a container without CPU and memory requests and a memory limit; a serving container without readiness and liveness probes |
| [`secrets.rego`](policy/secrets.rego) | a Secret object in Git; a reference to a Secret, or a key of one, that no ExternalSecret of the render makes (env, envFrom, secret and projected volumes, imagePullSecrets, a CSI volume's driver credential); a secrets-store CSI volume; a ConfigMap key, a literal environment value or a literal in an ExternalSecret's template that looks like a secret |
| [`configmaps.rego`](policy/configmaps.rego) | a reference to a ConfigMap, or a key of one, that the render does not make in the pod's namespace (envFrom, env, volumes, projected volumes): an overlay that generates a ConfigMap without the base's namespace |
| [`network.rego`](policy/network.rego) | a render with pods but no NetworkPolicy denying all ingress and egress; a namespace not enforcing Pod Security `restricted`; warns on an egress rule without `to` (every address, in the cluster too) |
| [`containerfile.rego`](policy/containerfile.rego) | a base image not pinned by digest (an earlier stage may be named instead); a final stage without a numeric `USER` other than root, or without an `ENTRYPOINT`; `ADD`; an `ARG` or `ENV` named like a secret; an `ENTRYPOINT` or `CMD` in shell form |
| [`profiles.rego`](policy/profiles.rego) | `kubernetes-gate.yaml` differing from `kubernetes.yaml` in anything but `profile` and `gate`, or without `gate.url`; a `gate` in `kubernetes.yaml` |
| [`packs.rego`](policy/packs.rego) | a gate without `REZONO_PACKS` (it would not start); `REZONO_PACKS` other than the names of `publish.packs` in [`../kubernetes.yaml`](../kubernetes.yaml), in that order (a name on one side only fails, RV-S15); `REZONO_LIVE_PACKS` other than the names of `live.packs`; a pack that takes proposals or is held live and is not served (the gate's own rule at start); a gate without `REZONO_ROLES`, or with roles other than the `may_read` roles of `access.roles` (compared as sets; a `complete` role is never served), or a role named twice; `REZONO_ROLE_GROUPS` for a role it does not serve (RV-S21) |
| [`lib.rego`](policy/lib.rego) | a pod template in a kind the policies do not read (a ReplicationController, an operator's kind) until it is listed there |

The base's egress rules on 443 (the store, the issuer, the Git host) and the live engine's on 22 have no `to`: the base cannot know the platform's address ranges. The example warns about them; an installation narrows them with `to` in its overlay, and `--live` refuses them until it does. DNS egress names `kube-system` on port 53; on OpenShift the DNS is in `openshift-dns` on port 5353, an overlay patch of the policy `dns`.

The namespace's Pod Security admission enforces the pod rules again in the cluster: the check finds a breach at review, admission refuses it at apply.

## Making it live (the owner's)

Nothing here is applied by CI or by a session; Argo CD (or another GitOps controller) reconciles what is merged. To run it:

1. **A cluster** with a Gateway API implementation, the External Secrets Operator, and a NetworkPolicy-enforcing CNI.
2. **A registry and the images.** Rezono's three images (gate, viewer, live engine) built and pushed, and their digests written into the overlay's `images:`. The recipes: [`deploy/gate`](../../gate/Containerfile) (Node 24, the gate's sources run as they are), [`deploy/viewer`](../../viewer/Containerfile) (built for `kubernetes-gate`, so it holds no example data) and [`deploy/engine`](../../engine/Containerfile); build each from the repository root, `docker build -f deploy/<name>/Containerfile .`. The gate's and the viewer's are built and run by [`run/kind.sh`](run/README.md) on a machine with Docker; no runner pool has a container builder yet, so no CI job builds them or writes their digests.
3. **The secret store.** A `ClusterSecretStore` named `rezono` and, in it, the keys the ExternalSecrets name: `rezono/front` (`client-id`, `client-secret`, `cookie-secret`), `rezono/viewer` (`draft-key`, at least 32 bytes), `rezono/gate` (`store-key-id`, `store-secret`: read-only), `rezono/propose` (`dispatch-token`), `rezono/engine` (`live-token`, `store-key-id`, `store-secret`, `git-key`, `known-hosts`).
4. **An OIDC client** at the identity provider (Keycloak or another) for the front, with the redirect `https://<host>/oauth2/callback`, an audience the gate expects (`REZONO_OIDC_AUDIENCE`) and the role claim (`REZONO_OIDC_ROLE_CLAIM`, for example `groups`).
5. **An overlay of the installation's own**, copied from `overlays/example`, with its hostnames, issuer, store and digests, and `REZONO_PACKS` naming the packs its profile publishes; `check.sh --live <overlay>` passes; then point Argo CD at it.
