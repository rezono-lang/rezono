---
decider: [loop, run, k8s-admission]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: code-does-not-decide
---

# Move the decisions left in loop and run code into packs, and ship the compiled admission policy

The [vision](../docs/vision.md#rules-not-scripts) says: "No production code walks a graph, sums a column or picks a winner. Code may read input, render output from derived rows, apply a plan, and observe. It does not decide." [AGENTS.md](../AGENTS.md) rules 1, 2 and 7 say the same in short: no domain knowledge in code, everything that follows is compiled, and no code of our own where a component already exists.

An audit at commit `8d1fa9c` found the compiler, the publisher and the renderers in line with that rule. It found small modules in `loop/` and `run/` that still decide an outcome, most of them imported by nothing but their own test, several duplicating a `std-loop` rule, and a shipped admission policy that is written by hand although a compiled translator exists. This decision gives each of them one fate.

## 1. The four fates

- **(a) Delete.** The module is imported by nothing but its own test, and a standard pack already decides the same thing. The module and its test are removed together.
- **(b) Oracle.** Only tests use the module, and it computes an answer that a rule or a compiled artifact also gives, its own way. It moves under the `tests/` folder of its component, with a docstring that says which rule or artifact it checks, and gets an entry in [the formal foundations, section 11](../docs/formal.md#11-independent-oracles) in the same pull request.
- **(c) Pack rule.** Production needs the decision, and no rule decides it yet, or production does not read the rule yet. A red test states the rows the named pack derives, with the expectation taken from the module's current behaviour or its decision. Reading the input stays in Python; the classification moves into the pack. Where the module keeps its entry point as the reader of those rows, it is a (d) afterwards, and the test checks through `rezono_compiler.batch.read` that the answer is read from the named relation. Where nothing reads the module afterwards, a planner deletes it with its test or turns it into an oracle under (b).
- **(d) Keep.** The module reads input, applies a plan, observes, or renders from derived rows. A module that decides under an earlier decision is kept as **transitional** until that decision is replaced.

## 2. One row per module

| Module | What it decides today | Fate | Where the decision goes | Test or next step |
| --- | --- | --- | --- | --- |
| `loop/round_outcome.py` | success, pending or failure of a round; `loop/replay.py` falls back to it when a snapshot has no `round_outcome` row | (c) | `packs/std-loop/rules/round_outcome.dl`, which exists | `loop/tests/test_round_outcome_from_pack.py`, M2 |
| `loop/replay.py`, `replay()` | known, done and ready of an untyped recording from token evidence (lines 55 to 77); used by `loop/recording_cli.py` and `run/offline_replay.py` | (c) | `std-loop` `known.dl`, `done.dl`, `round_outcome.dl` and `ready.dl`, or `unblocked.dl` once the readers of `ready` switch to it; `replay_report` stays as the executor (d) | `loop/tests/test_untyped_replay_reads_pack.py`, M2 |
| `loop/round_limit.py` | whether the executor may take another round | (d) | an executor bound, a separate finding from any rule ([safe step rounds](safe-step-rounds.md)); its pending steps come from the derived `declared` and `done` rows | none |
| `loop/typed_recording.py` | nothing; it admits records and reads the derived rows of the pinned pack | (d) | `round_outcome` becomes a required relation under the first row | covered by the first row's test |
| `loop/status_projection.py` | nothing; it reads `current_delivery_status` from `std-loop` | (d) | the move that [loop apply and read-back](loop-apply-readback.md) asked for is done | none |
| `loop/status_times.py` | waiting time and completion time of a delivery step; imported only by its test | (c) | `packs/std-loop/rules/delivery_status.dl`; [delivery commit status](delivery-commit-status.md) and [platform tenants](platform-tenants.md) require both from loop evidence | `loop/tests/test_delivery_times_rule.py`, M2 |
| `loop/sweep_watermark.py` | seconds from a start to the latest sweep of the run | (a) | `std-loop` `quiet_round.dl`: `current_sweep` and `deadline_until` | deleted with `loop/tests/test_sweep_watermark.py` |
| `loop/event_deadline.py` | whether a deadline expired, inclusive | (a) | `std-loop` `quiet_round.dl`: `deadline_expired` (`until <= time`) | deleted with `loop/tests/test_event_deadline.py` |
| `loop/status_visibility.py` | which tenant sees which status record | (a) | the read rules of a pack (`may_read`, `std-access`) and the publisher's publication per role; a Python filter would be a second, unreviewed access path | deleted with `loop/tests/test_status_visibility.py` |
| `loop/sweep_absence.py` | absence only from a complete sweep | (a) | `std-loop` `comparison.dl`: `current(run, token, "absent", ...)` needs `complete_sweep` | deleted with `loop/tests/test_sweep_absence.py` |
| `loop/flow_evidence.py` | confirmed, disagreement or incomplete for a flow case with a probe and a Hubble witness | (c) | `std-loop`; [loop design](loop-design.md#verify-network-policy-in-the-disposable-cluster): "A rule reports disagreement between the expected decision and either witness, or between the two witnesses" | `loop/tests/test_flow_witness_rule.py`, M2; then (b) as the oracle of that rule in `loop/tests/test_live_network_pairs.py` |
| `loop/isolation_findings.py` | mismatches of expected and observed verdicts per case and layer | (b) | oracle of `std-loop` `drift.dl` on the network case table: loop design derives these findings "through the drift rule" | move to `loop/tests/`; used by `test_live_network_pairs.py` |
| `loop/router_cases.py` | allow, deny or inapplicable of each fixture case against the router allowances | (b) | oracle of the compiled router allowances ([platform firewall output](platform-firewall-output.md)) on `loop/tests/fixtures/network.json` | move to `loop/tests/` |
| `loop/rule_coverage.py` | which positive fixture cases witness each allowance | (b) | oracle of the same render; loop design: "account for each allowance exactly once" | move to `loop/tests/` |
| `loop/boundary_excess.py` | cases the router allows and service isolation denies | (b) | oracle of the control case per enforcement layer in loop design | move to `loop/tests/` |
| `loop/attempt_approval.py` | whether a planned effect with an approved digest may be claimed | (b) | oracle of `run/packs/dispatch` `authorized`, which already binds approval to the exact plan hash; [the formal models](../formal/README.md) cite its test | move to `loop/tests/`, and update the link in `formal/README.md` in the same pull request |
| `loop/uncertain_attempt.py` | a status read, never a repeat, after an uncertain attempt | (b) | oracle of the executor's follow-up to the formal `LoseReply` and `Reconcile` actions; `formal/README.md` cites its test | move to `loop/tests/`, and update the link in `formal/README.md` |
| `loop/build_transition_choice.py` | the Python selection during the comparison week | (d), transitional | [build reconciliation](build-reconciliation.md) keeps Python authoritative while it compares | retire with that decision |
| `run/ovh_renewal.py` | blocking codes for a service that could renew or outlast its bound (lines 49 to 77) | (c) | `run/packs/provider-terms` (new): `renewal_block(service, code)`; the codes and field meanings are those of [price enforcement](run-price-enforcement.md) | `run/tests/test_renewal_bound_rule.py`, M4 |
| `run/ovh_order_status.py` | what a vendor status string means | (c) | `run/packs/provider-terms`: the status vocabulary as pack facts and `order_outcome(order, outcome)` | `run/tests/test_order_status_rule.py`, M4 |
| `run/ovh_order.py` | refusing usage-billed detail types (`CONSUMPTION`, `OUTPLAN`, line 95), cutting the expiry at the next UTC midnight (`min(expiration_utc, day_end)`, line 115), and assigning quote mode `binding_quote` (line 119); JSON shape, order-id and currency agreement, and exact microcent arithmetic are input-integrity checks | (c) for detail types, expiry bound and quote mode, (d) for input-integrity checks and parsing | `run/packs/provider-terms`: usage-billed detail types and quote mode as pack facts, and `order_guarantee(order, mode, expires_us)` under [price enforcement](run-price-enforcement.md) | `run/tests/test_order_guarantee_rule.py`, M4 |
| `run/ovh_inventory.py` | `remaining()`: delivered services still listed; `request()` only names the read | (c) for `remaining()`, (d) for `request()` and the parsing | `run/packs/cleanup`: `still_listed(listing, service)` | `run/tests/test_still_listed_rule.py`, M4 |
| `run/read_only_preflight.py` | changed price, insufficient stock and unknown reads | (c) for the findings, (d) for reading each observation once | `run/packs/offer-selection`: `preflight_finding(sku, finding)` ([offline acceptance](run-offline-acceptance.md), "Read-only preflight") | `run/tests/test_preflight_rule.py`, M4 |
| `run/effective_quote.py` | the USD to EUR conversion (line 126) and the accepted pair (line 83); the effective edition is already read through `std-time` | (c) | `run/packs/exact-quote`: `effective_amount(quote, currency, numerator, denominator)`; [effective currency](run-effective-currency.md) keeps its answers, only the place of the conversion changes | `run/tests/test_effective_amount_rule.py`, M4 |
| `run/ceph_storage.py` | the Ceph monitor quorum count (`3` with three or more nodes, `1` otherwise, line 47); rendering the Rook `CephCluster` JSON is a converter | (c) for the quorum count, (d) for rendering | `run/packs/cluster-shape`: `ceph_monitor_count(cluster, count)`, passed as an input to `render()` (which reads it from the pack when omitted) | `run/tests/test_ceph_monitor_count_rule.py`, M4 |
| `run/closed_month.py` | the closed month report | (d), transitional | [closed month](run-closed-month.md); its currency literal falls under the currency row | currency row |
| `run/order_day_review.py` | the review of an order day; it already reads `authorized` from `run/packs/dispatch` | (d), transitional | [order day review](run-order-day-review.md); its currency literals fall under the currency row | currency row |
| Currency literals in `run/*.py` | `"USD"` and `"EUR"` in `closed_month.py:99`, `effective_quote.py:83` and `:125`, `order_day_review.py:121`, `:136` and `:162` | (c) | pack facts: the currencies of a run and the pair of a rate capture are facts of `run/packs/exact-quote`, next to the `CurrencyCode` enums of `run/packs/dispatch` and `run/packs/invoice-drift` | `run/tests/test_no_currency_literals.py`, M4 |
| `k8s-admission/policy_renderer.py` | the hand-written CEL of the shipped policy | (b) once the release switches | stays only as the test expectation, as [the admission translator](k8s-admission-translator.md#order) says | the release test below |
| `k8s-admission/admission_release.py` | nothing of its own; it composes the release from the checked publication | (d) | renders each policy with `admission_translator.translate` from the checked rule program and its binding | `k8s-admission/test_translated_policy.py::test_release_renders_the_translated_policy`, M2 |
| The preflight oracles in `k8s-admission/` | independent CEL and API server outcomes | (b), already | covered by [the admission rules](k8s-admission-rules.md) | leave |

Count: (a) 4, (b) 7, (c) 12, (d) 7, plus the admission oracles that already are oracles.

## 3. Vocabulary

A vendor's words and a currency are domain knowledge, so they are facts with an origin, not literals in code:

- **Order status.** `notPaid` is not committed; `checking`, `documentsRequested` and `delivering` are pending; `delivered` is delivered; `cancelled` is refused. These come from the provider's order documentation as [price enforcement](run-price-enforcement.md), "Correlation", records them. Any other status, including a different spelling, is unresolved: unknown is explicit.
- **Order detail types and quote guarantee.** Detail types `CONSUMPTION` and `OUTPLAN` are usage-billed and give no guarantee, even at zero ([price enforcement](run-price-enforcement.md), "Every charge is in the order"). Any structurally valid unpaid order without a usage-billed detail type yields quote mode `binding_quote` and expires at `min(expirationDate, next UTC midnight of the approved day)` in UTC microseconds ("Expiry").
- **Renewal fields.** `renew.automatic` true, `renew.forced` true and `renew.deleteAtExpiration` false each block; a missing or ill-typed field is `renewal_unknown`. The expiration date counts from its UTC midnight, and equality with the cleanup deadline blocks.
- **Currencies.** The quote currency of a capture, the pair of a rate capture and the currency of a price publication are facts of the run pack. Code passes the recorded strings through and never compares them with a literal.

## 4. Admission

[The admission translator](k8s-admission-translator.md#order) already says that the generated policy replaces the hand-written one once both give the same outcome on the same requests. That comparison exists in `k8s-admission/test_translated_policy.py`. The red test added beside it requires the release itself to carry the translated policy for the checked-in `verified-supply` and `in-zone-flow` programs and bindings, and to give the outcomes of [the hand-calculated fixtures](k8s-admission-rules.md#hand-calculated-fixtures) in the standalone CEL evaluator and the offline API server. The disposable cluster renders its admission fixture with the same `render_release` (`loop/cluster/admission_fixture.py`), so the third oracle of the translator decision runs on the switch as well. `k8s-admission/` is read before landing; the test is exempt, the switch in `admission_release.py` is not.

## 5. Order

The deletions under (a) land with this decision. The red tests under (c) are independent, except that the first two `loop` rows land together: removing the fallback to `outcome()` leaves untyped recordings without an outcome until `replay()` reads the pack. The moves under (b) are planner work and each adds its row to section 11 of the formal foundations; none needs a new rule.

## Considered

- **Move every module into a pack at once.** Several are oracles that should stay independent of the rules they check; moving them into the pack would leave those rules unchecked.
- **Keep the orphaned modules as documentation.** A module that nothing imports still reads as the place where the decision lives, and drifts from the rule that actually decides.
- **Leave the hand-written policy shipped until a separate cluster comparison.** The cluster job already applies what `render_release` renders, so it compares the translated release on the same fixture once the switch lands; a second, separate comparison would add a step and no evidence.
