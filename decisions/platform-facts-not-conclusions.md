---
decider: [owner, platform]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: platform-facts
---

# Derive the platform's ports, release order, start order, running release and verified supply instead of writing them down

The [vision](../docs/vision.md#facts-and-conclusions) says: "A conclusion is derived by a rule. If a rule can derive it from what the same publication holds, it is not written down", and "A row without an origin is not a fact." A review of `examples/platform` at commit `b77fd2a` found seven places where the pack writes down a row that repeats a pinned vendor statement, holds a number nobody published, or states what a rule could derive. The owner adopted, on 2026-11-20, the advice to put the seven points out together. This decision gives each point its current state, its target and its migration order, states the equivalence each step keeps, and names the red test of the step a worker takes. [Fact origins](fact-origin-required.md) · [Standard packs everywhere](standard-packs-everywhere.md) · [Rezono 1 defaults](language-rezono-1-defaults.md) · [Vendor transport evidence](platform-vendor-transport-evidence.md) · [Rezono 1, section 7](language-rezono-1.md#7-per-derivation-intended-semantic-differences-for-examplesplatformrulescoredl)

## 1. The seven points

| # | Written today | What it is | Target | Red test |
| --- | --- | --- | --- | --- |
| 1 | `Offer.port` in `facts/core.yaml` | for five products a copy of a pinned vendor statement; for the others a design choice without origin | a service's port follows from the vendor statement for the release it runs, unless a written port decision overrides it (section 3) | `test_platform_derived_ports.py`, `M2` |
| 2 | `Release.released_on_day` (1, 50, 100, 150, 200, 250) | ordinals nobody published, beside a sourced date | a release's date is its maker's published date, read from the pinned statement; `runs` orders by date (section 4) | `test_platform_release_dates.py`, `M3` |
| 3 | `Service.step` (1 or 2) | a hand-numbered order that `needs` already implies | the start order follows from `needs` through `std-order` (section 5) | `test_platform_start_order.py`, `M2` |
| 4 | `supported_service_release` in `facts/support_window.yaml` | a second way to say which release a service runs, beside `Pin` and `runs` | `support_window_result` reads `runs` (section 6) | `test_platform_support_window_runs.py`, `M2` |
| 5 | `Artifact.signed` (`yes`/`no`) | an observation written as a design fact | an observed signature, open, complete within a verifier's scan (section 7) | `test_platform_signature_observations.py`, `M2` |
| 6 | zones, roles, function flags, catalogue prices, placement | design choices without origin | an origin for every row, as [fact origins](fact-origin-required.md) requires | that decision's `examples/platform/test_platform_fact_origins.py`, `M2` |
| 7 | `Demand` | a maker's requirements mixed with the platform's own design, without origin | a maker's page for a maker's requirement, a decision for the platform's design (section 8) | `test_platform_demand_origins.py`, `M2` |

The test files are in `examples/platform/`.

## 2. How each change lands

Each point moves in three steps, so that each step can be checked against the state before it.

1. **Sources.** The sourced facts the target reads are added beside the old facts. No rule reads them yet, so every derived row stays the same, except where a point lists an intended difference. This step changes tests a worker may not change, so a planner takes it.
2. **Rules.** The rules read the sources instead of the old facts. The old facts stay, and the independent oracle (`examples/platform/oracle.py`) still computes from them, so `test_platform_reference.py` compares the new derivation with the old facts row by row. The point's red test turns green in this step, which a worker takes.
3. **Retire.** A planner removes the old slot, its rows, the oracle's reading of it and its labels, moves the oracle to the sources, and restates the tests that wrote the old slot. Each red test reads the old slot only to show that no rule depends on it, and skips that check once the slot is gone, so it stays green.

A red test whose step 1 has not landed says so in its reason ("Waits for the planner's sources step of section N"). `scripts/red_list.py` then lists it as waiting. The planner who takes step 1 removes that clause in the same pull request.

## 3. Ports (point 1)

### Now

`provides(s, f, port)` in `rules/core.dl` joins a service's product with a hand-written `offer` row that carries the port. Nine `facts/*_transport_source.yaml` files hold the makers' pinned statements of the default port per series ([vendor transport evidence](platform-vendor-transport-evidence.md)); only `published_default_transport` in `rules/postgres_transport.dl` reads them.

| Product, function | Offer port | Vendor statement | |
| --- | --- | --- | --- |
| keycloak, identity | 8443 | 26.0.0: TCP 8443 | the same |
| postgresql, database | 5432 | 17: TCP 5432 | the same; there is no statement for 16, which `db-git` runs |
| chrony, time | 123 | 4.6: UDP 123 | the same |
| openbao, secrets | 8200 | 2.3.0: TCP 8200 | the same |
| kube-control, control-plane | 6443 | 1.32: TCP 6443 | the same |
| registry, registry | 443 | 3.0.0: TCP 5000 | differs |
| argocd, gitops | 443 | 3.0.0: TCP 8080 | differs |
| forgejo, git | 443 and 22 | 9.0: TCP 3000 | differs |
| ceph, object-storage | 443 | 19.2.0: TCP 3300 and 6789 | differs: the statement names the monitor ports, not object storage |
| loadbalancer, ingress | 443 | none | |
| coredns, dns | 53 | none: it waits for a page that states protocol and port together | |
| signer, signing | 443 | none: the platform's own product | |

Two truths stand side by side: where they agree the offer is a copy, and where they differ nothing says why.

### Target

- `Offer` keeps `product` and `function`: what a product offers. `Offer.port` retires.
- A new kind `PortDecision` in `schema/core.yaml`, all slots required: `id`, `product` (`Product`), `function` (`Function`), `port` (integer from 1 to 65535). A row says that the platform serves a product's function on a port, whatever its maker's default. Its origin is a decision ([fact origins](fact-origin-required.md), section 1). The eight rows below keep the values that `facts/core.yaml` holds at `b77fd2a` where no vendor statement gives them; this decision is their origin until a later decision changes one, cited as a `git` source that names `decisions/platform-facts-not-conclusions.md` at the revision that adds the row.

| Port decision | Product | Function | Port |
| --- | --- | --- | --- |
| `pd-lb-ingress` | loadbalancer | ingress | 443 |
| `pd-dns` | coredns | dns | 53 |
| `pd-reg` | registry | registry | 443 |
| `pd-gitops` | argocd | gitops | 443 |
| `pd-git-https` | forgejo | git | 443 |
| `pd-git-ssh` | forgejo | git | 22 |
| `pd-s3` | ceph | object-storage | 443 |
| `pd-sign` | signer | signing | 443 |

- No port decision repeats its maker's default: a decision is written only where the platform departs from the statement or no statement exists. When a statement later appears that gives a decided port, the decision goes.
- `provides(s, f, port)`, for a service `s` whose product `p` offers `f`, by the first of these that applies:
  1. **Decided.** A port decision for `(p, f)` gives its port, and no vendor statement is read for `(p, f)`.
  2. **The release it runs.** The port of each vendor statement of `p` whose `series` is the `version` or the `series` of the release `s` runs (`runs`). A statement's series is the tag or the release branch named in its URL ([vendor transport evidence](platform-vendor-transport-evidence.md), "Which pages qualify"), so it can match either.
  3. **The reference series.** When `s` runs no known release and the statements of `p` name exactly one series, that series' port, as the licence rule falls back to a reference release (`rules/product_licence.dl`). It is the weaker ground, and the witness shows which rule gave the row.
  4. Otherwise no port follows, and `port_unknown(s, f)` names the service and the function. On the facts of `b77fd2a` plus the sources below it is empty.

```prolog
.decl port_decided(p: symbol, f: symbol)
port_decided(p, f) :- port_decision__product(d, p), port_decision__function(d, f).
.decl release_names(r: symbol, x: symbol)
release_names(r, x) :- release__version(r, x).
release_names(r, x) :- release__series(r, x).
provides(s, f, port) :- service__product(s, p), offer__product(o, p), offer__function(o, f),
    port_decision__product(d, p), port_decision__function(d, f), port_decision__port(d, port).
provides(s, f, port) :- service__product(s, p), offer__product(o, p), offer__function(o, f), !port_decided(p, f),
    runs(s, r), release_names(r, x), vendor_default_transport_source__product(v, p),
    vendor_default_transport_source__series(v, x), vendor_default_transport_source__port(v, port).
```

  The reference-series rule and `port_unknown` follow the same pattern; their shape is the worker's.
- A vendor statement does not prove that a running deployment listens on its port ([vendor transport evidence](platform-vendor-transport-evidence.md), "What the evidence proves"). The target claims no more: a service keeps its maker's default unless a port decision says otherwise, and that assumption is this decision.
- `rules/choice_evidence.dl` and `rules/unique_evidence.dl` join `offer__port` to find a provider's port; they read `provides` instead.

### Sources first

- The eight `PortDecision` rows, with their origin.
- A vendor statement for PostgreSQL 16 in the form of [vendor transport evidence](platform-vendor-transport-evidence.md). `db-git` is pinned to `postgresql-16`, and the one PostgreSQL statement is for 17; without a statement for 16, rule 2 finds none and rule 3 does not apply, because `db-git` runs a release. `acceptance/test_postgres_transport.py` then expects both rows.
- `examples/test_platform_incremental_proof.py` changes the port of `o-lb` and expects `provides` to retract the old row and prove the new one through the single rule of `provides`. After step 2, `lb`'s port comes from `pd-lb-ingress`, and `provides` has several rules. The planner restates both tests in this step: they select the port decision rows beside the offer rows, change the port in both, and take the rule whose witness proves the row, so they hold before and after step 2.

### Equivalence

On the facts of `b77fd2a` plus the sources above, `provides` holds the same 14 rows as `oracle-rows.json`: 8 from port decisions; 3 from the release the service runs (`idp` 8443 through version 26.0.0 of `keycloak-26`, `db-idp` 5432 through series 17, `db-git` 5432 through series 16); and 3 from the reference series (`time` 123, `vault` 8200, `cp` 6443). `cp` moves to rule 2 when point 4 gives it a release of series 1.32, with the same port. `flow`, `crossing`, `firewall_rule`, `in_zone_policy` and `unauthenticated_target`, which read `provides`, do not change.

### Retire

`Offer.port`, its rows, its label (`offer.port`) and the port in the oracle's `offers`; the oracle reads the port decisions and the statements as section 3 says.

## 4. Release dates (point 2)

### Now

`stable_release`, `newest_day`, `runs` and `behind_newest` order releases by `Release.released_on_day`, a whole number in `facts/core.yaml`: 1 for distribution 3.0.0, 50 and 150 for PostgreSQL 16 and 17, 100, 200 and 250 for Keycloak 25, 26 and 27rc. None is a date and none has an origin. `facts/keycloak_release_source.yaml` holds the publisher's announcement of Keycloak 26.0.0 with `published: '2024-10-04'`, its URL and its hash; `rules/keycloak_release.dl` publishes it as `published_release` and compares it with the register.

### Target

- A release's date is the day its maker published it, read from a pinned `ProductReleaseSource` statement (product, version, published, URL and SHA-256), as Keycloak 26.0.0 already has. A rule derives `released_on(r, d)` from the statement whose product and version are the release's; in Rezono 1 it is the derived property `Release.released_on: Date?`. Nothing is written on the release itself: a written date beside the statement would be the second copy of one reading that [vendor transport evidence](platform-vendor-transport-evidence.md) removed for ports.
- Every release row names the `version` its statement dates. A row that stands for a series names the series' first release: `postgresql-16` names 16.0 and `postgresql-17` 17.0, the versions their licence notices already name; `keycloak-25` names 25.0.0. `keycloak-27rc` exists to exercise `stable: 'no'`; it gets the `synthetic` origin of [fact origins](fact-origin-required.md), section 3, no statement and no date.
- `published` of `ProductReleaseSource` and of `ProductReleaseReference` becomes a `date` slot. Rules compare dates in native order ([standard packs everywhere](standard-packs-everywhere.md), section 1.2); no day number is computed and `@days` is not used.
- A stable release is newest when no stable release of the same product has a later date. A product with a stable release that has no dated statement has no newest release, so an unpinned service of it runs nothing known, and `release_undated(r)` names the release: unknown stays explicit ([AGENTS.md](../AGENTS.md), rule 4).

```prolog
stable_release(r, p, d) :- release__product(r, p), release__stable(r, "yes"), released_on(r, d).
.decl newer_stable(r: symbol)
newer_stable(r) :- stable_release(r, p, d), stable_release(_, p, e), d < e.
runs(s, r) :- service__product(s, p), !pinned(s), stable_release(r, p, _), !newer_stable(r),
    !has_undated_stable(p).
behind_newest(s, r) :- runs(s, r), release__product(r, p), released_on(r, d), stable_release(_, p, e), d < e.
```

- `newest_day` and `has_stable` retire; `newer_stable` and `has_undated_stable` are helpers.

### Sources first

- A `ProductReleaseSource` row with its sidecar for distribution 3.0.0, Keycloak 25.0.0, PostgreSQL 16.0 and PostgreSQL 17.0 (Keycloak 26.0.0 has one), read from the maker's release announcement or tagged release; and `version` on the release rows that lack one.
- `released_on_day` becomes optional, so a release added later (point 4) needs no number. The rows that have one keep it until step 3, and `oracle.py` keeps ordering by it, skipping a release without one.
- `proof_cases/test_registry_release_licence.py` and `proof_cases/test_support_version_policy.py` write release rows with `released_on_day`. The planner gives the releases of their scenarios a version and a dated statement where their cases depend on an order, so they hold before and after step 2.

### Waits for

Rules that compare two dates in native order, which [standard packs everywhere](standard-packs-everywhere.md) adds in section 1.4, step 1, with its red test A, `compiler/tests/test_std_decision_dates.py::test_std_decision_rules_read_dates`. That test is `M3`, and a test is never on an earlier milestone than a test it waits for ([release 1 scope](release-1-scope.md)), so this point's red test is `M3`, not `M2`.

### Equivalence

With the makers' dates the stable releases of each product keep today's order: Keycloak 25.0.0 before 26.0.0, PostgreSQL 16.0 before 17.0. So `runs` holds the same four rows, and `behind_newest` the same row `(db-git, postgresql-16)`.

### Retire

`released_on_day`, its rows and its label; `newest_day` in `labels/en.yaml`. The forward note in [Rezono 1, section 7](language-rezono-1.md#7-per-derivation-intended-semantic-differences-for-examplesplatformrulescoredl) records the change of the rows `newest_day` and `runs`. `SupportQuery.as_of_day` stays with [standard packs everywhere](standard-packs-everywhere.md), section 1.4, step 5.

## 5. Start order (point 3)

### Now

`Service.step` is 1 for sixteen services and 2 for `lab`, `restore` and `restore-bad`. `flow_from_step(a, b, n)` gives each need the later step of its two ends. On every need the provider's step is at most the consumer's, so the numbers say nothing that `needs` does not, and nothing checks them against it: a step-1 service that came to need a step-2 service would go unnoticed.

### Target

- `std-order` gets one extension point in `rules/order.dl`, closed into `before`:

```prolog
// The order a domain's own rules state: a comes directly before b. A declaration alone denotes the empty set.
// @extend
.decl stated_precedes(a: symbol, b: symbol)
before(a, b) :- stated_precedes(a, b).
before(a, c) :- before(a, b), stated_precedes(b, c).
```

  Its invariants then hold for a stated order too: a cycle of needs is an `order_cycle`, which blocks a publication. The staged candidate (`candidate/order.rezono`, `candidate/order.json`) changes with the rules, and the importers re-pin the new hash: `packs/std-loop/pack.yaml` and `examples/platform/pack.yaml`, and onward for the packs that import `std-loop`.
- The platform states its start order in `rules/core.dl`: `stated_precedes(b, a) :- needs(a, b, _).` A provider starts before whoever needs it.
- `flow_from_step` retires. A flow holds from the start of its consumer, which `before` places after its provider; no relation is needed to say so.
- The elements of the start order are service ids. `before` is one relation for every ordered element of the platform, today also the proposal stages `request`, `review` and `apply`, so no service may share an id with another ordered element, and `before` never links a service with an element that is not one.
- There is no sources step: `needs` is derived already. A worker can take this point now.

### Equivalence

- `stated_precedes`, over services, is `{(b, a) | needs(a, b, _)}`: the 34 pairs of `needs` in `oracle-rows.json`, reversed.
- Every pair that the steps order strictly is in `before`, and no pair of `before` runs against the steps.
- In every `flow_from_step` row the consumer is the later end, in the step order and in `before`.
- `before` among services is acyclic.

The question `dependency-order` (`proof_cases/test_standard_order.py`) reads `before` among the proposal stages only and does not change.

### Retire

`Service.step`, its rows and its label; `flow_from_step` in `rules/core.dl`, in the oracle, in `oracle-rows.json` and in `labels/en.yaml`. The oracle adds `stated_precedes` in the same pull request, so `test_platform_reference.py` keeps at least 20 reference relations. The forward note in [Rezono 1, section 7](language-rezono-1.md#7-per-derivation-intended-semantic-differences-for-examplesplatformrulescoredl) records the change of the rows `needs_service` and `flow_from_step`.

## 6. The running release and the support window (point 4)

### Now

`facts/support_window.yaml` holds one `supported_service_release` row: service `cp`, product `kubernetes`, series 1.32, version 1.32.13, and `support_window_result` reads it. `runs` has no row for `cp`: its product, `kube-control`, has no release and no pin. So the row does not copy `runs`, as the review put it; it is a second way to say which release a service runs, in a kind of its own, beside `Pin` and the newest stable release. It also names the product `kubernetes`, while the service, its transport statement and its licence notice (`kube-control-1.32.13`) name `kube-control`: two ids for one product.

### Target

- `cp`'s release is written the way every other service's is: a release `kube-control-1.32.13` (product `kube-control`, version 1.32.13, series 1.32, stable) and a pin of `cp` to it. The pin needs an origin like every row ([fact origins](fact-origin-required.md)): the decision or the observation of the running cluster that says `cp` runs 1.32.13. The row it replaces has none today.
- One product, one id: the support register and its source (`facts/kubernetes_support.yaml`, `facts/kubernetes_support_source.yaml`) name `kube-control`. The id is the platform's; the maker's page, its URL and its hash do not change.
- `support_window_result(q, s, v, end, url, sha256)` reads `runs(s, r)`, `release__version(r, v)`, `release__series(r, x)`, `release__product(r, p)` and `published_series_support(p, x, _, end, url, sha256)`.
- `SupportedServiceRelease` and its rows retire.

### Sources first

After point 2's sources step, because the new release has no day number:

- The release `kube-control-1.32.13` with its pin, its dated `ProductReleaseSource` statement, and a licence binding `bind-kube-control-1.32.13` (basis `exact-scenario-release`, notice `kube-control-1.32.13`).
- The rename of `kubernetes` to `kube-control` in the support register, its source, their expected standalone violations and `acceptance/test_kubernetes_support.py`; `facts/kubernetes_support.yaml` drops its own product row, because `facts/core.yaml` declares `kube-control`.
- Intended differences, which the planner restates in the same pull request: `runs` gains `(cp, kube-control-1.32.13)` (`acceptance/test_support_unknown.py` asserts four rows); `support_unknown` gains `(cp, kube-control-1.32.13, unknown)`, because `VendorSupportStatement` has no row for it (section 9); and `component_product_licence` gives `cp` the basis `exact-scenario-release` instead of `reference-source-release`, with the same version 1.32.13. `provides(cp, control-plane, 6443)` stays, now through rule 2 of section 3.

### Equivalence

`support_window_result` is the same for the four windows of `acceptance/test_support_window.py`.

### Retire

`facts/support_window.yaml`, the class `SupportedServiceRelease` and `expected/violations/support_window.json`.

## 7. Signatures (point 5)

### Now

`Artifact.signed` is `yes` for `a-shop` and `no` for `a-lab` in `facts/core.yaml`, and `verified` reads it. Whether an artifact carries a valid signature is what a verifier observes, not a design choice; written as a fact it can only say yes or no, never "not checked". The admission example already reads signatures as observations (`image_signature` in `k8s-admission/fixtures/translator/verified-supply.rules.yaml`).

### Target

- `schema/artifact_signature.yaml`, in the layer `observation`:
  - `ArtifactSignature`, with `world: open`: `id`, `artifact` (`Artifact`, required), `scan` (`SignatureScan`, required). A valid signature that the scan's verifier found on the artifact.
  - `SignatureScan`: `id`, `covers` (`Artifact`, multivalued, required). One verifier run over the artifacts it lists. Within it, an artifact without an `ArtifactSignature` row has no valid signature; outside it, the absence says nothing. In Rezono 1 this is `kind ArtifactSignature world open, complete by scanned` ([Rezono 1 defaults](language-rezono-1-defaults.md), section 2).
- The rules:

```prolog
.decl scanned(x: symbol)
scanned(x) :- signature_scan__covers(_, x).
.decl could_verify(x: symbol, s: symbol)
could_verify(x, s) :- artifact__for_service(x, s), artifact__built_by(x, b), service__role(b, r),
    platform_role__build_authority(r, "yes").
verified(s) :- could_verify(x, s), artifact_signature__artifact(_, x).
.decl supply_unknown(s: symbol)
supply_unknown(s) :- service__role(s, r), platform_role__runs_images(r, "yes"), !verified(s),
    could_verify(x, s), !scanned(x).
unverified_supply(s) :- service__role(s, r), platform_role__runs_images(r, "yes"), !verified(s), !supply_unknown(s).
```

  A service with no artifact (`restore`, `restore-bad`) has nothing that could verify it and stays unverified, as today.
- The scenario's observations go in `facts/artifact_signature.yaml`: a scan `scan-1` that covers `a-shop` and `a-lab`, and one signature on `a-shop`. The two artifacts are made up, so the sidecar is `synthetic` ([fact origins](fact-origin-required.md), section 3) and names this decision; a real verifier's output would be a `tool` source.
- There is no planner sources step: the worker adds the schema, the facts and the rules, and `Artifact.signed` stays until step 3.

### Equivalence

With those observations: `verified` is `{shop}`, `unverified_supply` is `{lab, restore, restore-bad}` as today, and `supply_unknown` is empty. Without `a-lab` in the scan, `lab` moves from `unverified_supply` to `supply_unknown`.

### Retire

`Artifact.signed`, its rows and its label; the oracle reads the observations.

## 8. Origins of design facts and demands (points 6 and 7)

**Point 6** is [fact origins](fact-origin-required.md), whose platform test asks an origin of every row of the platform's fact files. This decision adds nothing to it. The port decisions (section 3), the release statements (section 4) and the signature observations (section 7) carry their origins from the start.

**Point 7.** `Demand` says which function a product asks for. Some rows are its maker's requirement, others the platform's own design, and nothing tells them apart. That decision accepts any origin, so it does not settle the split. Here it is:

- A demand that a third-party product's maker requires, such as Keycloak's relational database, cites the maker's page: a `document` or `tool` source with the URL and the fragment hash, as the transport statements do.
- A demand that is the platform's choice about a third-party product, such as signing in through the platform's identity provider, cites the decision that chose it.
- A demand of a product the platform designs itself cites a decision. These are the products that `facts/licence-bindings.yaml` lists in `product_licence_gap` with the reason `unknown-implementation`: `client`, `loadbalancer`, `app`, `builder`, `signer` and `recovery-env`.
- No demand is `synthetic`: the demands describe the platform's design, not data made up to exercise rules.

A decision is a `git` source that names a file in `decisions/` (or a `proposal` source); a maker's page is a `document` or `tool` source with a URL outside this repository, or a `git` source at the maker's repository.

## 9. Not decided here

- `VendorSupportStatement` in `schema/core.yaml` (read by `rules/support_unknown.dl`, with no rows) and `SeriesSupportSource` (`facts/kubernetes_support_source.yaml`) both hold a maker's support end. After point 4, `support_unknown` reports `cp` while a series statement for 1.32 exists. Whether one kind replaces the other is a later decision.
- `SupportQuery.as_of_day` belongs to [standard packs everywhere](standard-packs-everywhere.md).
- The origin of `Offer` rows (which product offers which function) is the same question as point 7 and follows the same split.

## 10. Red tests

Each test takes its expectations from this decision, from the pinned vendor statements in `facts/`, and from the independent reference rows in `oracle-rows.json` and `acceptance/product-evidence.json`. Each fails today with an `AssertionError`, or with `MissingDemandOrigin`, a subclass of it.

| Test | Mark | Ready | Expects |
| --- | --- | --- | --- |
| `test_platform_derived_ports.py::test_service_port_follows_the_vendor_statement_unless_decided` | `M2` | after the sources step of section 3 | the 14 `provides` rows; none changes when every offer port does; a changed Keycloak statement changes `idp`'s port; without `pd-reg`, `reg` gets the registry statement's port; no port decision repeats a statement of its product, and each cites a decision file |
| `test_platform_release_dates.py::test_runs_orders_releases_by_their_sourced_date` | `M3` | after red test A of standard packs everywhere and the sources step of section 4 | no rule reads `released_on_day`; `released_on` of `keycloak-26` is the published date of its statement; every stable release has one; the same `runs` and `behind_newest`; reversed day numbers change nothing; swapped Keycloak dates make `idp` run `keycloak-25` |
| `test_platform_start_order.py::test_start_order_follows_from_needs_through_std_order` | `M2` | now | `stated_precedes` is `needs` reversed; `before` among services is its closure and never links a service with another element; no `order_cycle`; the step numbers of `b77fd2a` never run against it; equal steps for all services change nothing |
| `test_platform_support_window_runs.py::test_support_window_reads_the_release_the_service_runs` | `M2` | after the sources steps of sections 4 and 6 | `cp` runs one release, version 1.32.13; the same `support_window_result` for the four windows; another patch version on that release gives that version; another version on the retired row changes nothing |
| `test_platform_signature_observations.py::test_supply_is_verified_from_observed_signatures` | `M2` | now | the observation kinds of section 7; `verified` `{shop}`, `unverified_supply` as in `oracle-rows.json`, no `supply_unknown`; flipped `signed` values change nothing; without `a-lab` in the scan `lab` is unknown; without the signature on `a-shop`, `shop` is unverified |
| `test_platform_demand_origins.py::test_demands_cite_the_vendor_or_a_decision` | `M2` | now | the split of section 8 for every `demand` row; Keycloak's database demand cites Keycloak's page |

Tests that already exist and change with these steps, each restated by a planner in the step named:

| Test | Step |
| --- | --- |
| `examples/test_platform_incremental_proof.py` (both tests) | sources, section 3 |
| `acceptance/test_postgres_transport.py` | sources, section 3 |
| `proof_cases/test_registry_release_licence.py`, `proof_cases/test_support_version_policy.py` | sources, section 4 |
| `acceptance/test_kubernetes_support.py`, `acceptance/test_support_unknown.py`, the licence proof cases that read `cp`'s basis | sources, section 6 |
| `test_platform_reference.py` through `oracle.py` and `oracle-rows.json` | sources, section 4 (a release without a day number); retire, every section |

## 11. Order

1. Section 5 (start order), section 7 (signatures) and section 8 (demands): workers, now.
2. The sources step of section 3, then its rules step.
3. The sources step of section 4, then the sources step of section 6, then the rules step of section 6.
4. The rules step of section 4, once red test A of [standard packs everywhere](standard-packs-everywhere.md) is green.
5. Each retire step after its rules step, one planner pull request per point.

## Alternatives

- **Write `Release.released_on` as a date slot with a source, as the review proposed.** The date would then be written twice from one announcement: once on the release and once in its `ProductReleaseSource` statement, which the release comparison already reads. Deriving it from the statement keeps one copy; the name and the type stay those the review asked for.
- **Write the port per service instead of per product and function.** Two services of one product would then repeat the same port. Today every port follows the product; a per-service decision can come when a service departs from its product.
- **Keep the offer port and only compare it with the vendor statement.** That would keep two truths and turn their disagreement into a drift finding, but four ports differ on purpose, and a design choice is not drift.
- **Port decisions for every product, with the vendor statements only as a check.** Five of the thirteen would repeat a pinned statement, which the vision rules out.
- **Derive the start order in the platform's own rules.** A closure of its own would be a variant beside `std-order`, which [standard packs everywhere](standard-packs-everywhere.md) rules out, and it would not get `std-order`'s cycle invariant.
- **Keep `kubernetes` as the product id and rename `kube-control`.** The service, the offer, the demands, the transport statement, the licence notice and their tests name `kube-control`; the support register and its source are the smaller side.
- **Record a signature as a fact with a `tool` source.** It would have an origin, but a missing row would still read as "not signed". Only the scan's coverage turns an absent signature into a known one.
