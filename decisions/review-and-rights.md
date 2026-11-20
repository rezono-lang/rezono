---
decider: [core]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: review-and-rights
---

# Proposing and reviewing: rights with evidence

[contracts/change.yaml](../contracts/change.yaml) already describes a change and its life cycle: a `Change` has an `author` (an `Actor`) and a `content_sha256`, a `Review` names a reviewer, a verdict, a moment and the content hash it is about, and `may_review` is evaluated at the moment of the review. [contracts/proposal.yaml](../contracts/proposal.yaml) records who proposed, in which role. Reading per role works: `packs/std-access` declares `may_read`, and [central read access](central-read-access.md) settles who reads what. The compiler knows the names `may_propose`, `may_review` and `may_publish` (`ACCESS` in `compiler/rezono_compiler/pack.py`), but no pack declares them and nothing refuses or assesses a review on their ground. This decision says how proposing and reviewing work, on top of the change contract. It is the page the change contract and the proposal sentences of `packs/std-view` refer to for the life cycle.

## 1. Rights are rules with evidence, in `std-access`

`packs/std-access` declares four more rights beside `may_read`, each as an extensible relation (`// @extend`) without a single grant clause, exactly like `may_read`. Importing `std-access` grants nothing; a consumer pack writes the clauses, and every right it derives has a proof like any other conclusion.

| Right | Columns | Means | Checked by |
|---|---|---|---|
| `may_propose` | `role: symbol, kind: symbol, element: symbol` | the role may propose a change to this element | the gate, when it accepts a proposal (section 11) |
| `may_review` | `role: symbol, kind: symbol, element: symbol` | the role may accept or reject a change to this element | `std-review` (sections 3 and 8) |
| `may_publish` | `role: symbol, kind: symbol` | the role may publish an epoch that changes this kind | the publisher (section 11) |
| `may_execute` | `role: symbol, plugin: symbol` | the role may apply an approved plan of this plugin | the effect port; the contract fixtures already ask for `may_execute` |

The second column of the first three names a kind, so kind renaming across pinned imports rewrites it, as `ACCESS` already does. `may_execute` names a plugin, not a kind, and stays out of `ACCESS`.

## 2. A review is a fixed fact about one content hash; merging is not accepting

A review is a row that is never edited: who reviewed, in which role, the verdict, a reason (required when rejecting), the day, and the two hashes it saw: the content hash of the change and the hash of what the change rests on (its support). It counts only while both are the change's current hashes. Merging a pull request integrates; it accepts nothing. There is no input "merged" anywhere in the assessment: a merged change without a valid review is `proposed`, and a review that is withdrawn on the host is recorded as a separate dismissal row, never by deleting or rewriting the review.

## 3. Review rights count at the moment of review

Reading uses today's rights. Reviewing uses the rights held on the day of the review. Holding a role is a dated fact, `role_grant` (subject, role, first day, optional exclusive last day). A review is authorised when its reviewer held the role it names on its day, and that role has `may_review` over every element the change touches. A grant that ends after the review leaves the review valid; a grant that starts after it does not make it valid. A grant introduced by the change under review never authorises a review of that same change.

A grant that no change introduced is a founding grant, such as the owner's from the start of an installation. A grant that a change introduces counts only once that change is accepted: from the day of the review that accepted it, and only while the change stays accepted, so not once it is stale or rejected. That acceptance rests on founding grants alone: the review that accepts a change to rights must be authorised by a founding grant, not by a grant that another change introduced. So two changes cannot accept each other into being, each granting the role that the reviewer of the other one needs, and a still proposed change grants nothing. It also keeps the rules stratified: whether a grant counts never depends on a review that the grant itself authorises.

## 4. Read to judge

Whoever accepts or rejects must be able to read everything the judgement rests on: every element the change touches and every element of its support, through `may_read` of the role the review names. A review that cannot read one of them is blind.

## 5. Typed rights, and no leaks through a status

A right holds for an element together with its kind: a right over `(note, x1)` says nothing about `(shelf, x1)`. Review rows, statuses and the work queue are rows like any other: a role sees them only under its read rights, and a derived status is published to a role only with a proof from rows that role reads (the existing non-interference of the publisher and the checker). A role that does not read a change or its support learns nothing about it through a status, a cause or the length of a queue.

## 6. A changed content or support makes an acceptance stale

A valid acceptance is about one pair (content, support). When the change's current content hash or support hash differs from that pair, the acceptance no longer counts and the change is `stale` and due for review. A re-review is a new review of the new pair; the old review row stays as it was. A change whose only reviews are about another change is not stale but `proposed`.

## 7. Changing rights is itself a proposal

A change to role grants or to grant rules is proposed and reviewed like any other change, and is accepted on the authority of founding grants (section 3). Every beneficiary of a grant that a change introduces counts as an author of that change, so the beneficiary cannot accept it. This holds in the lab phase too (section 10).

## 8. Four checks that block

`std-review` derives four invariants, so each one blocks the publication of the epoch it occurs in, and a review that triggers one is not valid:

| Check | Fires for an active review when |
|---|---|
| `review_self(review)` | the reviewer is an author of the change (its author, or a beneficiary of a grant it introduces), except the owner's own work in the lab phase |
| `review_unauthorized(review)` | the reviewer did not hold the named role on the review day through a grant that counts on that day (a founding grant, or one whose change was accepted on founding grants by that day and is still accepted) and that this change did not introduce, or that role lacks `may_review` over one element the change touches |
| `review_blind(review)` | the named role lacks `may_read` over one element the change touches or rests on |
| `review_conflict(change)` | two valid reviews about the current content and support have opposite verdicts |

A dismissed review is not active: it triggers no check and counts for nothing. Dismissal is the way out of a blocking review.

## 9. Publication policy per kind: `require`, `mark` or `none`

A pack states per kind, as a `review_policy` fact, what publication does with a change that touches that kind and is not accepted:

| Policy | A change that is not accepted |
|---|---|
| `require` | holds the epoch: the invariant `unreviewed_required(change)` blocks it, and the last good manifest stays visible |
| `mark` | is published, and `unreviewed_marked(change)` lets the viewer and exports show its status |
| `none` | needs no review |

A kind without a policy fact has `none`. The status of a calculation, the freshness of a source and the review status stay three separate things.

## 10. The lab phase

The phase is a fact, `review_phase`, with the value `lab` or `strict` and the owner's subject. Without a phase fact the phase is `strict`. In the lab phase there is one reviewer: the owner may accept their own work, so `review_self` does not fire when the author and the reviewer are both the owner. Authority and read-to-judge still hold for the owner. In the lab phase a pack uses `none` or `mark`, never `require`: `require_in_lab(policy)` is an invariant. Otherwise the self-review check would block every review there is. Moving to `strict` is a decision of the owner, recorded as a change to the phase fact; nothing switches it by implication.

## The standard pack `std-review`

`std-review` is a new standard pack, imported beside `std-access`. It assesses reviews that were already admitted; it authenticates nobody. Its schema is laid out in full by its first task, and each check lives in a rule file of its own (`self.dl`, `authority.dl`, `blind.dl`, `conflict.dl`, `policy.dl`) beside `state.dl`. A rule for a relation lives in the file that declares it, so a check that makes a review invalid also adds its negation to the one rule for `review_valid` in `state.dl`; those three tasks follow each other. The tables, with day numbers as whole numbers `YYYYMMDD` as in `std-decision`:

| Kind | Tables |
|---|---|
| `change` | `change`, `change__author`, `change__content_sha256`, `change__support_sha256` |
| `change_member` (an element the change touches) | `change_member`, `change_member__change`, `change_member__kind`, `change_member__element` |
| `change_support` (an element the change rests on) | `change_support`, `change_support__change`, `change_support__kind`, `change_support__element` |
| `review` | `review`, `review__change`, `review__reviewer`, `review__role`, `review__verdict` (`accepted` or `rejected`), `review__reason`, `review__day`, `review__content_sha256`, `review__support_sha256` |
| `review_dismissal` | `review_dismissal`, `review_dismissal__review` |
| `role_grant` | `role_grant`, `role_grant__subject`, `role_grant__role`, `role_grant__from_day`, `role_grant__until_day` (exclusive, optional), `role_grant__change` (optional: the change that introduces it) |
| `review_phase` | `review_phase`, `review_phase__phase` (`lab` or `strict`), `review_phase__owner` |
| `review_policy` | `review_policy`, `review_policy__kind`, `review_policy__policy` (`require`, `mark` or `none`) |

The derived relations:

- `review_active(review)`: not dismissed. `review_current(review)`: active, and both hashes equal those of its change.
- `review_valid(review)`: active, and none of `review_self`, `review_unauthorized` and `review_blind` holds for it.
- `change_accepted(change)`: a valid current acceptance and no valid current rejection. `change_rejected(change)`: the reverse. `change_stale(change)`: neither, and a valid acceptance of the change about another pair exists. `change_proposed(change)`: none of the three. `review_due(change)`: proposed or stale.
- The invariants `review_self`, `review_unauthorized`, `review_blind`, `review_conflict`, `unreviewed_required` and `require_in_lab`, and the derived `unreviewed_marked`.

During a conflict there is no extra state: the change is neither accepted nor rejected, so it is `proposed` or `stale` and stays due for review.

## Three open cases, decided

- **A beneficiary in the lab phase.** A change that grants a right to someone cannot be accepted by that someone, also not by the owner in the lab phase. The lab exception is for the owner's own work, and the owner holds the rights the lab needs from the start; a grant to the owner is not something the owner accepts alone. So `review_self` fires for a beneficiary, without the lab exception.
- **Two opposite valid reviews.** No last-write-wins and no new state: `review_conflict` blocks, the change shows `proposed` (or `stale` after an earlier acceptance) and stays in the queue. It is resolved by dismissing one of the reviews, or by a new content or support, which makes both reviews old.
- **A dismissed approval.** A dismissal is a new row about the review; the review row stays. A dismissed review is not active: an approval that was dismissed accepts nothing, and the change falls back to `proposed`, or to `stale` when an earlier valid acceptance about another pair exists.

## Where the acceptance cases go

The cases about assessment and rights are red tests now, with the mark `extra:` and this decision in their reason:

- `compiler/tests/test_std_access.py::test_standard_access_declares_the_four_rights`: the declarations of section 1.
- `compiler/tests/test_std_review.py`, one test per task: the review states (no review, accepted, rejected with a reason, a new content, a new support, an unrelated change, a review of another change, a re-review); `review_self` (four eyes, the owner in the lab phase, a non-owner in the lab phase, two people with one role, a beneficiary); `review_unauthorized` (a grant revoked later, a grant that starts later, an exclusive last day, a grant in the change itself, a grant from a change that is proposed, accepted on founding grants, reviewed before that acceptance or stale, two changes that grant each other's reviewer, a typed right, a role that is claimed but not held, a role without the review capability); `review_blind`; `review_conflict` with dismissal; and the publication policy with the lab phase.

The other cases are not red tests now:

- **The boundary of the gate:** refusing a rejection without a reason, a reviewer without a verified identity, an actor that a file claims is verified, a host review whose commit cannot be bound to the canonical content, missing grant history, a support list that does not match its hash, a replayed or rewritten review event, identities from two providers, a proposal by a service account that lost its human, a historical name used as a reviewer, and a bot review taken as a human one. These belong to a review intake at the gate, which turns a verified host or OIDC identity into the `review`, `role_grant` and `review_dismissal` rows above. The local gate takes its role from its caller and carries no verified subject today, and the change contract has no review event id, so these cases come with that intake, in `edge/gate/` and `contracts/`, not before.
- **Publication:** an accepted change in a red epoch, and a blocking error that a review cannot overrule. They are the publisher's existing rule that an invariant blocks the epoch, and come with the publisher's use of `std-review`.
- **Access to statuses:** two worlds that differ in a hidden row giving the same statuses, and a reader who loses access to a premise. They are the publisher's non-interference over derived rows, tested with the publisher once `std-review` exists.
- **A required decider:** `std-decision` already derives `in_force_without_decider`.
- **Replay:** the assessment is a pure rule program over fixed rows; it reads no clock and no host.

## The fixture

The tests use a small consumer pack of their own, not an extension of `tests/fixtures/neutral`. Every conformance case shares the neutral pack, and review kinds there would change all of their pins and outputs for no gain. The consumer pack is written by the test module into a temporary directory: two kinds, `note` and `shelf`, three roles, and grant clauses for `may_read` and `may_review`. It imports `std-access` and `std-review` by path with the hash computed when the test runs, because `std-review` does not exist yet and a static fixture could not pin it. Once `std-review` is on main, a planner may move the consumer pack to `tests/fixtures/review/` with fixed pins.

## Considered

- **Rights as fields of a role in the deploy profile.** Then a grant has no proof and no history, and a review could not be checked against the rights of its day.
- **Evaluate review rights with today's grants.** Revoking a role would erase every earlier acceptance, and a role granted today would approve old reviews retroactively.
- **Accept on merge.** The host's merge says the change is integrated, not that someone allowed to judge it did. It would make every merged change accepted, including the author's own.
- **Let a grant count once its change is accepted on any grant that counts.** That would allow delegation in chains, but whether a grant counts would then depend on reviews that such grants authorise: a recursion through the negations of the checks, which the rule program cannot stratify, and a door for changes that approve each other. A chain of delegation can come later as an explicit, bounded rule.
- **A `conflict` state.** It would add a state the change contract does not have, and the queue already says what to do: review again.
- **The last review wins.** It makes the outcome depend on the order in which a journal is read, and hides a real disagreement.
- **Put the assessment in `std-access`.** `std-access` stays the small vocabulary of rights; what a review means is a pack of its own that a consumer imports when it reviews.
