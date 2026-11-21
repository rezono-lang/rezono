---
decider: [owner, language, core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: facts-and-derivations
---

# Facts are stated, conclusions are derived, and a conclusion comes back only through the loop

The [vision](../docs/vision.md#facts-and-conclusions) says: "A fact has an origin: a decision, a vendor publication, a design choice or an observation", and "If a rule can derive it from what the same publication holds, it is not written down." Shortcuts have broken this more than once. The platform wrote ports, release order, start order and the running release down beside the rules that derive them ([platform facts are not conclusions](platform-facts-not-conclusions.md)). The repository's own steering wrote "this head was read" down as a label ([landing gate as a rule](landing-gate-as-rule.md)). Each time a conclusion was stored as a fact, it drifted from its grounds and nothing noticed. [Fact origins](fact-origin-required.md) made every fact name its origin; this decision says what may be a fact at all, how a conclusion is referred to later, and the one way a conclusion becomes a fact. It adds the warning W116 and the kind `ConclusionCitation` of `std-decision`. [Conclusion addresses](publication-conclusion-addresses.md) · [std-decision](../packs/std-decision/README.md) · [Loop engine epoch](loop-engine-epoch.md)

## 1. Derive, don't store

A fact is only what a source states. There are four:

| Source | A pack writes it as ([fact origins, section 1](fact-origin-required.md#1-what-an-origin-is)) |
| --- | --- |
| a decision | a `decide` block, a `Decision` the record is bound to, or a `git` source that names the decision's file |
| an observation | a `query`, `tool` or `person` source, or an observation the loop admits |
| a vendor statement | a `document` source, or a `git` source at the vendor's pinned commit |
| a design | a decision, written as above |

Everything else is derived. When a rule of the pack can derive a row from the pack's other facts, the row is not written in `facts/`, whatever origin it would cite. Citing an origin does not make a copy a fact: a port copied from a vendor page cites the page, and is still a copy of what the rules derive from the page's own row.

## 2. Cite, don't copy

A later reference to a conclusion uses its address: the canonical conclusion IRI pinned to the epoch and dataset hash it was read in, `<kind iri>/<spelled id>?pin=m-<epoch>@d-<64 hex>`, and, where it matters why it held, the canonical witness IRI `<base>witness/<64 hex>` ([conclusion addresses, sections 1 to 3](publication-conclusion-addresses.md#1-canonical-conclusion-iris)). A decision, a document, a test expectation that names a published conclusion, or another pack refers to it this way. It is never copied into `facts/`.

An address is a citation, not an origin. A row that cites only a conclusion has no origin of its own and still needs one of section 1.

## 3. Feed back only through the loop

A conclusion becomes a fact in exactly two ways:

- **Through a decision.** Someone decides to take the conclusion as given: a `std-decision` `Decision` records it, with its decider and its day, and a `ConclusionCitation` names the conclusion's pinned address and its witness. The fact rows are bound to that decision by an arrow to `Decision`, so their origin is the decision ([fact origins](fact-origin-required.md#1-what-an-origin-is)). Freezing a computed value for a period, or adopting a derived plan as the plan, goes this way.
- **Through an observed effect.** The loop applies an effect that a conclusion asked for, and what comes back is an observation of the world: a `std-loop` read-back or observation, with its observer's source (`query`, `tool` or `person`). Its origin is the observation. That the world now matches the conclusion is a finding the rules derive; it is not the conclusion written down.

`std-decision` gets one kind for the first way, beside the justification layer:

| Kind | Slots | Means |
| --- | --- | --- |
| `ConclusionCitation` | `id`; `decision` (`Decision`, required); `conclusion` (required: a conclusion IRI pinned with both `m-<epoch>` and `d-<64 hex>`); `witness` (required: a canonical witness IRI) | the decision takes this conclusion, as derived in that epoch and for this reason, as a fact |

The schema holds the shapes: `conclusion` matches `^[^?#]+\?pin=m-[^@?#]+@d-[0-9a-f]{64}$` and `witness` matches `^[^?#]+/witness/[0-9a-f]{64}$`. A hash pin alone is not enough: the epoch says when the conclusion held.

## 4. Within an epoch the fixpoint, across epochs the loop

Within one epoch the engine evaluates the rules over that epoch's facts to their fixpoint. No conclusion of an epoch is an input of the same epoch, except as its own derivation. A conclusion of an epoch enters a later epoch only as a fact by section 3. A citation cannot point into its own epoch: the dataset hash in its pin covers every base row of that epoch, the citation's own row among them.

So a cycle that passes through the world, such as plan, apply, observe and plan again, always passes through a decision or an observation, each with an origin and a time. That is the loop of [the vision](../docs/vision.md#the-loop) and of `std-loop`; the engine itself never feeds its output back.

## 5. The warning W116: a fact that restates a conclusion

The compiler warns when a fact row restates what the rules derive. It is the check a pack's author meets on every compile, like W113 for a missing origin ([fact origins, section 4](fact-origin-required.md#4-phasing-and-codes)).

- **Restates.** A record of a base kind restates a conclusion when a derived relation of the pack's rule program with two or more columns has, for each of its columns, a slot of that kind with the same name, the record holds exactly one value in each of those slots, those values are a row the rules derive from the main fact state, and the rules still derive that row from the main fact state without the record's rows. The last condition keeps a record that is itself a ground of the row out of it.
- **Unless it cites or observes.** It is not reported when every row of the record has an observation origin (a `query`, `tool` or `person` source), or when the record is bound by an arrow to a `Decision` that has a `ConclusionCitation` whose `conclusion`, without its pin, is the conclusion IRI of the restated row.
- **One diagnostic per record and relation,** at the record's place, as W113 places it: the record's line in the fact file, or its row's line in a module. On the command line it is one line, `warning: W116 <file>:<line>:` and the sentence.
- **The sentence names the address to cite**, the unpinned conclusion IRI of the restated row under the pack's publication base, so the author can cite instead of copy. `{0}` is the kind, `{1}` the identifier, `{2}` the derived relation and `{3}` the IRI.

| Code | en | nl |
| --- | --- | --- |
| W116 | `{0}` `{1}` restates the conclusion `{3}` of `{2}`, which the rules derive without it; remove the row and let the rules derive it, or bind it to a `Decision` with a `ConclusionCitation` of that conclusion, or give it an observation source | `{0}` `{1}` herhaalt de conclusie `{3}` van `{2}`, die de regels ook zonder dit record afleiden; verwijder de rij en laat de regels haar afleiden, of bind het record aan een `Decision` met een `ConclusionCitation` van die conclusie, of geef het een waarnemingsbron |

- **A warning in every language version.** W116 never refuses, in `rezono 0` or later, and changes no output: the compile goes on and every row stays as written. The match is by slot names, so it can name a coincidence; that is taste, and taste warns ([AGENTS.md](../AGENTS.md), rule 5). A copy that matters breaks a test or an oracle, which blocks.
- **The code.** W116 is the first W code after W115, which [Rezono 1 refinements](language-rezono-1-refinements.md) took; W113 is the missing origin and W114 the redundant default ([Rezono 1 defaults](language-rezono-1-defaults.md)). No open pull request used W116 on 2026-11-21. It goes into `rezono/messages/en.json`, `rezono/messages/nl.json` and the table of [v0 §10](../docs/rezono/v0.md#10-diagnostics) when it is built.
- **Only the compiler judges it.** Whether a row was written or derived is a property of how the pack was authored, not of a proof, as the origin of a row is ([fact origins, section 5](fact-origin-required.md#5-the-publishers-check-row-rezonoorigins)). The independent checker does not repeat it. The compiler runs the rule program on the main fact state for it, on the batch backend that `explain` already uses.

## 6. Where it applies now

- The eight points of [platform facts are not conclusions](platform-facts-not-conclusions.md#1-the-eight-points) are this rule applied to the platform; that decision's migration order stands.
- The read label `p1-read-<sha>` was a stored conclusion. [Landing gate as a rule](landing-gate-as-rule.md#4-the-label-is-a-projection-of-the-conclusion) makes it a projection.
- A red test takes its expectation from an independent source (root [AGENTS.md](../AGENTS.md)). Where that source is a published conclusion, the test cites its address; it does not copy the value into a fact file of the pack under test.

## 7. Red test

| Test | Mark | Expects |
| --- | --- | --- |
| `compiler/tests/test_restated_conclusions.py::test_a_fact_that_restates_a_conclusion_warns` | `extra` | a `rezono 0` pack whose fact record restates a counted conclusion compiles (status 0) with one W116 at that record's place naming the kind, the identifier, the relation and the unpinned conclusion IRI; no W116 for a record that differs from the conclusion, for a record with a `tool` source, or for a record bound to a `Decision` whose `ConclusionCitation` pins that conclusion; a W116 for a record whose decision cites another row's conclusion |

The mark is `extra`: release 1 does not need the warning ([release 1 scope](release-1-scope.md)).

## 8. Follow-up worker tasks

1. `std-decision`: the kind `ConclusionCitation` of section 3, its labels, its new hash in `compiler/rezono_compiler/standard_packs.py`, and the re-pin of the packs that import `std-decision`.
2. The compiler: W116 of section 5 in the compile command, its sentences in both message files, and its line in v0 §10. This turns the red test green.
3. Later, not now: the publisher resolves each `ConclusionCitation` against the retained epoch it pins (`resolve_iri` of [conclusion addresses, section 4](publication-conclusion-addresses.md#4-resolution-back-to-one-row)) and reports one that does not resolve. That needs retained epochs in the publication store and gets its own decision and red test.

## Alternatives

- **Refuse in `rezono 1`, as R053 refuses a missing origin.** A missing origin is certain; a restatement is matched by slot names and can be a coincidence. A refusal on a guess would block correct packs.
- **Let the checker find restatements.** The checker verifies proofs; that a row was written rather than derived is not part of any proof ([fact origins](fact-origin-required.md#5-the-publishers-check-row-rezonoorigins) reasons the same way).
- **Allow a conclusion as a fact when it cites its address.** A citation alone has no decider and no day. Through a decision, someone answers for taking the conclusion as given, and `in_force_on` says from when.
- **Feed a conclusion back within the epoch.** It would make the fixpoint depend on its own output and the dataset hash on itself. The loop across epochs keeps each epoch a function of its facts.
- **A source kind `conclusion` in the source contract.** It would make a conclusion look like an origin. A `ConclusionCitation` on a decision keeps the decision as the origin and the conclusion as what it cites.
