---
decider: [core]
decided_on: 2026-11-19
valid_from: 2026-11-19
state: in_force
subject: central-read-access
---

# Central read-access authority and independent verification

Read access governs what a filtered role may see, when it may rely on absences and aggregates, when it may read a sweep variant's status, when a difference may be published for an assumption, and when an earlier manifest remains readable. [Witnessed read completeness](witnessed-read-completeness.md) introduced the explicit `may_read_full(role, kind)` relation for opt-in programs, and [checker and access review](checker-and-access-review.md) established the trust boundary around checker and access code. Five gaps remained across `packs/std-access`, the checker, the publisher and the local gate. This decision closes all five under one model.

## 1. Explicit `may_read_full(role, kind)` in `packs/std-access` and its consumers

- `packs/std-access` declares `may_read_full(role: symbol, kind: symbol)` as an extensible relation (`// @extend`) with no grant clauses, alongside `may_read(role: symbol, kind: symbol, element: symbol)`. Importing `packs/std-access` alone grants neither individual element rights nor full-read authority.
- Both `compiler/rezono_compiler/pack.py` (`ACCESS`) and `compiler/tests/souffle.py` (`ACCESS`) include `may_read_full` so kind renaming across pinned imports rewrites its second column the same way as `may_read`.
- Every pack that imports `packs/std-access` (`examples/subsidy`, `examples/platform`, `run/packs/probe-profiles`, `tests/fixtures/neutral`, and `tests/fixtures/slip`) states its full-kind grants explicitly with `may_read_full(role, kind)` clauses instead of relying on the legacy shape heuristic over `may_read`.
- Because declaring `may_read_full` switches every importing pack into explicit coverage mode, this change waits for the Rezono conversion of `packs/std-access` (`compiler/tests/rezono/test_whole_std_access.py::test_whole_std_access_has_the_same_meaning`) and updates `packs/std-access`, its consumers and their import pins together.

## 2. Checker verification of variant `status_readers`

A sweep variant's `status_readers` list determines which roles may see whether the variant's checks are green or red; every other reader sees `unavailable` so a check outcome cannot disclose hidden rows.

- The checker never trusts the publisher's `status_readers` list. `checker/rezono_checker/access.py` provides `check_variant_status_readers(variant: dict, role_full: Mapping[str, AbstractSet[str]], all_relations: AbstractSet[str], complete_roles: AbstractSet[str] = frozenset()) -> list[dict]`:
  - Every role listed in `variant.get("status_readers", ())` must also appear in `variant.get("readers", ())`; otherwise the checker returns an error finding (`reason: "status_reader_not_reader"`).
  - Every role in `variant.get("status_readers", ())` that is not in `complete_roles` must appear in `role_full` (derived independently by `check_role`) and must cover every relation of the complete epoch (`set(all_relations) <= set(role_full[role])`). Otherwise the checker refuses the variant with an error finding (`reason: "status_reader_incomplete"`).
- `edge/publisher/rezono_publisher/sweep.py` verifies `status_readers` through `check_variant_status_readers` using the checker's derived `full` sets before writing a variant manifest or diagnosis.

## 3. Independent checker check for access-changing assumptions

A proposal, local supposition or variant delta that may change what any role can read must yield no difference for any filtered role (`withheld`), decided solely from the rule IR, schema bundle and delta (never from data, avoiding existence leaks).

- Both `may_read` and `may_read_full` determine a role's readable view, so both are roots of the access dependency closure.
- `checker/rezono_checker/access.py` provides an independent `may_change_access(rules_doc: dict | None, bundle: dict | None, delta: dict | None) -> bool` sharing no code with `edge/publisher/rezono_publisher/difference.py`:
  - It fails closed (`True`) when `bundle` or `delta` is missing, when seals cannot be loaded, when a change has an unknown operation or lacks a string `kind`, or when any `calc` relation lies in the dependency closure of `may_read` or `may_read_full`.
  - Any change touching a relation in that closure (including ancestor kinds along the bundle's parent chain, their slot tables, or any table feeding a seal relation in the closure) returns `True`, with the sole exception of an `insert` into a kind `K` whose only uses in the closure are positive `K(?x)` premises of `may_read(?r, "K", ?x)` (which grants only the inserted element itself and never changes `may_read_full`).
- `edge/publisher/rezono_publisher/difference.py` extends its own `withheld` to include `may_read_full` and compares its verdict with `rezono_checker.access.may_change_access` in `difference.plan`: if publisher and checker disagree on whether a delta may change access, publication is refused (`views.Blocked`).

## 4. Self-sufficient `check_role` and checker-owned proof-index bounds

- `check_role` in `checker/rezono_checker/access.py` no longer takes `columns`, `kinds` or `parents` from the publisher. Instead it accepts the compiled `bundle` (`schema-bundle.json`, stored under `definition_sha256`):

  ```python
  check_role(role: str, complete: dict, snapshots: dict, claimed_full, bundle: dict,
             doc: dict, calc_ir: dict | None = None, instances=(), calc_all=(),
             calc_witnesses=(), witnesses=(), claimed_evidence=None) -> tuple[frozenset, list[dict]]
  ```

- From `bundle`, `doc` and `calc_ir` alone, `check_role` derives `kinds`, `parents` and `columns` itself:
  - each kind `k` in `bundle["kinds"]` gives `k["id"]: (k["id"],)` and optional `parents[k["id"]] = k["parent"]`;
  - each arrow `a` in `bundle["arrows"]` gives `a["table"]: (a["kind"], a["target"])`;
  - each attribute `a` in `bundle["attributes"]` gives `a["table"]: (a["kind"], None)`;
  - each enum `e` in `bundle["enums"]` gives `e["id"]: (None,)`;
  - slot-facet parameter base tables declared in `doc` (`<slot_table>__<suffix>`) give `(None,)`;
  - each seal in `doc.get("seals", ())` gives `refused: (kind, "period_close")`, `accepted: (kind,)`, `row_sha256: (kind, None)`, and per part `p["accepted"]: (p["kind"],)`;
  - calculation views and `as_of` come from `calc_ir`.
  A missing or malformed `bundle` fails closed with an error finding. `edge/publisher/rezono_publisher/publish.py` passes `json.loads(e.bundle)` to `check_role`.
- Proof-index bounds belong to the checker, not to the caller. `checker/rezono_checker/proof.py` fixes its own upper bounds: `MAX_PIECE = 64 * 1024` (65,536 bytes), `MAX_FANOUT = 128`, and `MAX_LEVELS = 8`. `_Walk` (used by `check_proof`, `check_rows`, `check_indexes`, `check_sources`, and `check_difference`) refuses any call with `limit < 1`, `limit > MAX_PIECE`, `fanout < 2`, or `fanout > MAX_FANOUT`, and refuses any tree root with `levels > MAX_LEVELS`. Callers may pass stricter bounds in tests, never looser ones.

## 5. Historical manifest readability in the local gate (`stillReadable`)

When `edge/gate/src/local.ts` receives a request pinned to an earlier main manifest `then` (`then.epoch < now.epoch`), it serves `then` only if the role's current authority at `now` still covers everything `then` would expose; otherwise it returns `404 not found` (`missing()`), indistinguishable from an absent manifest.

For every `(relation, past)` in `then.snaps`, `stillReadable(then, now)` requires:

1. `present = now.snaps.get(relation)` exists.
2. If `past.complete` is true, `present.complete` must be true. Downgrading a role from an unfiltered `complete` publication to a filtered role (even with `present.full === true`) revokes access to earlier `complete` manifests.
3. If `past.full` is true, `present.complete || present.full` must be true: a current partial snapshot cannot substantiate the absence claims of an earlier full snapshot.
4. If `present.complete` is true, the relation is covered. If `present.full` is true (and `past.complete` is false), the relation is covered without row-by-row checks only when `then.manifest.definition_sha256` is present and equals `now.manifest.definition_sha256`; otherwise, and whenever `present` is partial (`!present.complete && !present.full`), every key in `then.rows(relation)` must still appear in `now.rows(relation)` (or `past.sha256 === present.sha256`).

## Considered

- **Keep the legacy `may_read` shape heuristic for standard consumers.** Empty populations and multi-premise rules make syntax inspection fragile; explicit `may_read_full` makes full-read authority witnessed like every other conclusion.
- **Share the access-change classifier between publisher and checker.** That would violate the checker trust boundary (`edge/publisher/tests/test_checker_boundary.py`), where a bug in the publisher must be caught independently by the checker.
- **Keep `columns`, `kinds` and `parents` as optional parameters on `check_role`.** An optional publisher-supplied shortcut lets a faulty publisher steer what the checker believes the schema contains; deriving them from the signed schema bundle removes that trust path altogether.
- **Treat `present.full` as equivalent to `present.complete` in `stillReadable`.** `complete` bypasses role filtering whereas `full` is a filtered role's coverage flag; downgrading a role from `complete` to filtered must revoke historical `complete` manifests, and a definition change must not widen `present.full` across unrelated earlier rows.
