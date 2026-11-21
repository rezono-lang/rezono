---
decider: [core, language]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: facts-versus-derivations
---

# Facts versus derivations: derive, don't store; cite, don't copy; feed back only through the loop

The [project vision](../docs/vision.md#facts-and-conclusions) states: "A fact has an origin: a decision, a vendor publication, a design choice or an observation" and "If a rule can derive it from what the same publication holds, it is not written down." [Fact origins](fact-origin-required.md) enforces that every fact row names an origin, and [publication conclusion addresses](publication-conclusion-addresses.md) gives every derived conclusion and every witness a canonical, epoch-and-hash-pinnable IRI. This decision states the three boundary rules separating facts from derivations across epochs, and adds a non-blocking warning in the independent checker when a stored fact repeats an independently derivable conclusion without citing it. [Fact origins](fact-origin-required.md) · [Publication conclusion addresses](publication-conclusion-addresses.md) · [Platform facts not conclusions](platform-facts-not-conclusions.md) · [Import rule proposals](import-rule-proposals.md) · [Source contract](../contracts/source.yaml)

## 1. The three rules

1. **Derive, don't store.** A fact is only what an external source states — a decision, a vendor publication, a design choice or an observation. Anything that follows by rule from facts already present in the same publication is derived with a checker-verified witness and is never written into `facts/` as a base row.
2. **Cite, don't copy.** When a later document, proposal, report or downstream system refers to a derived conclusion from a publication, it cites the pinned canonical conclusion address ([publication conclusion addresses](publication-conclusion-addresses.md), section 3) — `<kind iri>/<spelled id>?pin=m-<epoch>@d-<64 hex>` or `<kind iri>/<spelled id>?pin=d-<64 hex>`, together with the pinned witness address `<base>witness/<H(witness)>?pin=...` when citing its proof — never a value copied into `facts/` as an uncited base row.
3. **Feed back only through the loop.** Within an epoch the engine computes to a deterministic fixed point; a derived conclusion never turns back into a base fact inside the same epoch. Across epochs the loop runs: a conclusion from an earlier epoch becomes a fact in a later epoch **only** via one of two explicit origins:
   - **An explicit decision (`origin: decision`):** a recorded decision (`std-decision` `Decision`, `decide` block, or `proposal` / `git` decision source) that explicitly adopts or acts on the earlier conclusion and cites its pinned canonical conclusion address (and its pinned witness address when citing the proof).
   - **An observed outcome (`origin: observation`):** an independent external observation (`query`, `tool`, or `person` source admitted through the loop's observation boundary) recording what actually happened in the world after an effect ran — never a copy of a prior epoch's desired-state derivation.

## 2. Checker warning: `stored_derivable_fact`

The independent checker (`checker/rezono_checker/check.py`) enforces this boundary as a **non-blocking warning** so existing packs can surface copies without halting publication:

- **API:** `check_epoch(..., fact_sources=None)` accepts an optional `fact_sources` argument (a sequence of `SourceEntry` dicts matching `contracts/source.yaml`, or `bytes` of a `sources.json` list). When `fact_sources` is provided on a complete epoch (`full is None`), the checker inspects every stored base relation row against the epoch's derived conclusions.
- **When a stored fact equals a derivable conclusion:** For every base relation `B` with arity at least 2 (multi-column fact, attribute or relationship tables; single-column kind membership tables `K(id)` are excluded because an entity identifier may legitimately appear in unary derived predicates) and every row `(B, k)` present in `snapshots[B]`:
  - Find any derived relation `D` in `derived` whose key column types match `B`'s key column types and whose snapshot contains the exact same canonical key `k`.
  - Verify that `(B, k)` is **not** in the transitive premise graph of the witness proving `(D, k)` (a base premise such as `edge(a, b)` feeding `path(a, b) :- edge(a, b)` is a ground premise, never a stored copy of a conclusion).
- **When the stored fact carries no reference/citation:** Look up `(B, k)` in `fact_sources`. The stored fact is permitted without warning if at least one of its `sources` satisfies either:
  1. **Pinned conclusion citation (`origin: decision`):** `url` or `position` contains a valid pinned canonical address matching [publication conclusion addresses](publication-conclusion-addresses.md) section 3 (`?pin=m-<epoch>@d-<64 lowercase hex>` or `?pin=d-<64 lowercase hex>`; an epoch pin `m-<epoch>` without `@d-<64 hex>` is rejected and does not suppress the warning); or
  2. **External observation (`origin: observation`):** `kind` is one of `"query"`, `"tool"` or `"person"`.
- **Finding shape and severity:** When `(B, k)` equals an independently derivable `(D, k)` and has no qualifying citation or observation source, `check_epoch` appends:

```json
{
  "reason": "stored_derivable_fact",
  "severity": "warning",
  "relation": "<B>",
  "key": "<canonical key k>",
  "detail": "<D>"
}
```

- **Non-blocking:** `"stored_derivable_fact"` is registered in `WARNINGS` in `checker/rezono_checker/check.py`, so `report["valid"]` remains `True` when no error findings are present. Implementing `stored_derivable_fact` also registers the code in [`contracts/checker-refusal.yaml`](../contracts/checker-refusal.yaml) and `checker/rezono_checker/messages/{en,nl}.json`. Because changing `checker/rezono_checker/check.py` touches a pre-landing review path ([checker and access review](checker-and-access-review.md)), the implementation pull request requires an independent reading label `p1-read-<head_sha>` before landing.

## 3. Red test (`extra`)

| Test | Mark | Expects |
| --- | --- | --- |
| `checker/tests/test_facts_versus_derivations.py::test_checker_warns_without_blocking_on_uncited_stored_derivable_fact` | `extra` | `check_epoch(..., fact_sources=...)` keeps `report["valid"] == True` and emits warning `stored_derivable_fact` for a stored base fact whose canonical key equals an independently derivable conclusion without a pinned conclusion citation (including when given an invalid unpinned `?pin=m-1` without `@d-<64 hex>`); does not warn on a base premise used in the conclusion's proof, does not warn when the stored fact cites a pinned conclusion address (`?pin=m-1@d-<64 hex>`), and does not warn when the stored fact carries an observation source (`tool`). |

## Alternatives considered

- **Make `stored_derivable_fact` a blocking error immediately.** A blocking error would reject legacy packs during incremental migration (such as the staged retirements in [platform facts not conclusions](platform-facts-not-conclusions.md)). A checker warning surfaces every uncited copy with its exact relation, key and derived counterpart without halting publications, and can be tightened in a later decision once packs are migrated.
- **Check only relation names instead of canonical row tuples and proof independence.** Stored copies in `facts/` almost always use a different relation name from the derived rule (for example `offer__port` beside `provides`, or `stored_port` beside `derived_port`). Comparing canonical typed tuples while excluding rows in the derived witness's transitive premise graph catches real copies without flagging ground premises.
- **Check single-column kind membership tables too.** A kind table `service(id)` declares entity existence; flagging it whenever a unary derived predicate such as `verified(id)` derives the same identifier would produce false positives on every pack. Restricting the check to arity at least 2 targets stored property and relationship facts cleanly.
