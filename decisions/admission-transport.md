# Admit verified evidence at the batch boundary

Rules may rely on a completeness receipt or a certified round only after the independent checker has verified it. One admission step fills a small set of protected input relations before the rules run, and the publisher repeats the same step when it checks the epoch. This decision fixes the transport: the interface, the archive layout, where authority comes from, the outcomes and the protected relations. The receipt itself is fixed in [scoped completeness](scoped-completeness.md) and the round certificate in [safe transition rounds](safe-step-rounds.md).

## 1. One admission step, two kinds of evidence

| Evidence | Verifier | Fills |
| --- | --- | --- |
| Completeness receipt | `rezono_checker.completeness` | `verified_receipt`, `verified_member` |
| Certified round | a round verifier in `rezono_checker`, built on `check_transition_certificate` | `verified_round`, `verified_round_member` |

Both kinds share one entry point, one trusted context, one submitted index and one comparison in `check_epoch`. Each kind keeps its own verifier. Receipts are admitted first, because a round certificate cites scope receipts as premises (`missing_scope_coverage`): the round verifier receives the identities of the receipts admitted in the same step and nothing else.

A caller outside the batch boundary, such as a month-close replay that never runs rules, calls the receipt verifier directly with the same context shape. It does not need this transport.

## 2. Interface

The admission module is `checker/rezono_checker/evidence.py`. The name avoids the fact-admission package `rezono_admission`.

```python
@dataclass(frozen=True)
class Evidence:
    context: dict             # archived-file reference {file, uri, sha256} to the trusted context
    candidates: dict | None   # archived-file reference to the submitted index; None: nothing submitted
    read_bytes: Callable      # uri -> bytes, the storage resolver of the snapshots

def admit(evidence: Evidence) -> Admitted   # .rows {relation: [row]}, .findings, .references
```

`batch.epoch` gains the keyword `evidence: Evidence | None = None`. The default keeps every existing caller unchanged. `Epoch` gains the field `evidence`. `publish.verify` passes it to `check_epoch` on the complete side only, where the checker admits again and compares. `publish.plan` writes the candidate references of the admitted step to the complete manifest under `completeness_receipts` and `rounds`, each a list of archived-file references.

This replaces the three keywords `completeness_receipts`, `completeness_authority` and `archive` that an earlier draft of the receipt transport used. One object keeps the trusted and the submitted half apart by construction and carries the resolver to the checker.

## 3. Archive layout

```
observations/retained/context.json    {"completeness": [context, ...], "rounds": [round context, ...]}
observations/retained/<name>.json     objects a trusted context pins
observations/submitted/index.json     {"completeness_receipts": [reference, ...], "rounds": [reference, ...]}
observations/submitted/<name>.json    candidate receipts, round claims, certificates and what they pin
```

Every object is canonical JSON written once (`put_new`). Every reference is an archived-file reference. A completeness context has the six receipt fields of the scoped-completeness fixture convention. A round context pins `run`, `cut`, `manifest`, `definition_sha256`, the compiled `program`, the certified `base` and the candidate `domain` with its steps, integer priorities and batch width. A round claim names `run`, `cut`, the chosen `batch` with its member steps, and the certificates of every visible subset of that batch and of the alternatives that precede it.

The build, Loop and Run fixtures each used a layout of their own. They converge on this one when their helpers pass `evidence`.

## 4. Authority

Authority comes only from the SHA-256 of the context reference that the protected caller passes. Admission reads the context bytes, requires that hash, and then reads only what the context and the index reference. It never lists or searches the archive, and a candidate's own references select bytes to check without conferring authority over them.

The protected caller produces the trusted content from pinned inputs it already holds, and writes it under `observations/retained/` before the batch:

- Loop: the runner, from the pinned desired publication (expected sweep nodes, step domain, priorities, width) and its pinned program.
- Build: the job at the protected build engine commit, from the pinned scope definition and repository bundle.
- Run: the closer, from the receipt-log frontier and the declared intake partitions.

A source reader, a consumer or a pack fact file submits candidates only. None of them writes a trusted context.

## 5. Moment and outcomes

Admission runs in `batch.epoch` after the facts are loaded and before the rules are evaluated. The admitted rows enter as base rows of the protected relations and appear in the epoch's snapshots like any other base relation. The checker admits again in `check_epoch` and requires the protected snapshots to equal its own admitted rows.

| Situation | Outcome |
| --- | --- |
| No `evidence` | The protected relations stay empty. What depends on them stays unknown. No finding. |
| Context unreadable, mispinned, not canonical or malformed | `Blocked`. The protected caller's own input is broken. |
| Index unreadable, mispinned or malformed | `Blocked`. The caller pinned the index it assembled. |
| No index (`candidates` is `None`) | The protected relations stay empty. No finding. |
| A candidate fails verification | No row. A warning (`receipt_unverified`, `round_unverified`) names the candidate and the failed check. The publication stays green and the candidate stays listed in the complete manifest. |
| A protected row that admission did not produce | An error (`receipt_not_admitted`, `round_not_admitted`). The publication is blocked. |
| Admitted rows for a relation the pack does not declare | Not inserted. The manifest still lists the candidates. |

## 6. Protected relations

The compiler reserves these exact names and signatures. A pack declares one without a clause to use it. The compiler refuses a fact, rule, proposal or scenario row that supplies or derives it, and refuses the reserved name with another signature. `batch.columns` reports them like other base relations. Other names that start with `verified_` stay ordinary relations.

```prolog
.decl verified_receipt(receipt: symbol, source: symbol, scope: symbol, cut: symbol, inventory: symbol, content: symbol)
.decl verified_member(receipt: symbol, member: symbol, part: number, value: symbol)
.decl verified_round(round: symbol, run: symbol, cut: symbol, batch: symbol)
.decl verified_round_member(round: symbol, step: symbol)
```

- `verified_receipt` holds the receipt digest, the source name and the digests of the bound scope, cut, inventory and content, as scoped completeness fixes.
- `verified_member` exposes the typed member keys of an admitted receipt's trusted inventory. `member` is the canonical JSON text of the key, `part` its zero-based position and `value` the canonical text of that part. A rule reads a one-part key as `verified_member(r, _, 0, node)` and a mapping edge as two parts of the same member. No rule parses JSON.
- `verified_round` holds the round claim digest and the run, cut and batch that the round verifier checked and whose choice it replayed itself.
- `verified_round_member` lists the steps of that batch.

Content values beyond the member keys are not exposed in this version. A pack that needs a value in its rules makes that value part of the member key of its own scope, as a reader mapping does with a path and a reader. A consumer that needs the full content, such as the month close, reads it through the receipt verifier.

The protected relations are published on the complete side only. They carry no element column, and their rows expose the trusted inventory, member keys included, so no right of a kind can decide who reads them. Until a decision gives them an explicit read rule or element columns for the member keys, every filtered role has them withheld, as the relations of a sealed kind are withheld (`access.Scope.withheld`, and independently `rezono_checker.access.withheld_admission`). A derived conclusion that rests on a withheld row reaches a role only through a proof whose grounds that role may read ([scoped completeness](scoped-completeness.md), section 2); a conclusion whose only proofs rest on a protected relation stays hidden from every filtered role.

## 7. Round verification

The round verifier builds its context only from the retained round context. It enumerates the candidate batches over the pinned domain up to the width, checks a certificate for every visible subset of the claimed batch with `check_transition_certificate`, and recomputes the deterministic selection of safe transition rounds. Every alternative that would precede the claimed batch needs a certificate for one of its visible subsets that the checker finds violating. Missing evidence for an alternative leaves the round unverified, so readiness waits instead of trusting a supplied verdict.

Each step in the retained domain lists the plan hashes of its effects in their fixed order. A certificate binds `effect` to the canonical SHA-256 of the ordered list of plan hashes it applies, never to a step name. The verifier recomputes that digest from the domain and refuses a mismatch. A step with several effects has a visible boundary after each prefix of its effects, and each prefix needs its own certificate from the same base.

## 8. Names that apply

This decision fixes the names at the admission boundary. Earlier drafts used others, and those names lapse.

| Applies | Lapses |
| --- | --- |
| `batch.epoch(..., evidence=Evidence(context, candidates, read_bytes))` | the `batch.epoch` keywords `completeness_receipts`, `completeness_authority`, `transition_certificates`, `transition_authority` and `archive` |
| `context.json` with `completeness` and `rounds`; `index.json` with `completeness_receipts` and `rounds` | a list of trusted contexts or round objects passed beside the archive |
| complete manifest lists `completeness_receipts` and `rounds` | a manifest list `transition_certificates` |
| `verified_round(round, run, cut, batch)` and `verified_round_member(round, step)` | the protected inputs `loop_certified_step` and `loop_certified_member` |

A pack that needs a step that is safe on its own reads a verified round whose batch has that single member. A pack that needs the certified batch reads `verified_round` and its members. The round digest is what a witness cites. Inside the certifier's own speculative evaluation, a pack may keep internal relations under other names. They are not admission inputs.

## Alternatives considered

- **Separate keywords for candidates, authorities and the store.** Simple for receipts alone, but a second evidence kind would add three more, and inline trusted dictionaries leave no pin a replay can check. Replaced by one `Evidence` object with a pinned context.
- **Authority found in the archive** by listing retained objects or trusting a manifest field. Rejected: whoever can write the archive could then grant authority.
- **Supplied verdict rows**, such as a `proved` fact on a candidate batch. Rejected: a fact file can claim anything. A verdict enters only through admission.
- **A protected relation with JSON content.** Rejected: rules would have to parse text. Typed key parts cover membership and mappings, and content stays with the verifier.
- **Admission only in `publish.verify`.** Rejected: the rules would run without the evidence and their conclusions would stay unknown. Admission runs before the rules, and the checker repeats it.
