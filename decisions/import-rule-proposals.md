# Propose rules when importing data

An import may propose a rule to replace rows whose meaning follows from other facts. A person or agent can identify the rule by inspecting a source. A learner can supply candidates from examples. Either path produces an ordinary proposal for review. A successful check supplies evidence for that review and leaves the pack unchanged.

## Compare exact rows on a pinned pack

The compiler command takes a pack, the target relation and a candidate rule. Resolve the pack and its imports to immutable inputs. Record the input pins and the candidate digest in the result. Use the ordinary typed rule checks and the repository-pinned DuckDB and Soufflé versions. Both engines receive the same typed inputs and the same candidate. Soufflé provides an independent evaluation of the rule.

1. Record the original set of complete, typed rows of the target relation. Withhold those rows from the input to both engines. Recompute dependent relations from the withheld input so a materialized copy cannot supply the answer.
2. Compare the inferred sets by typed row identity, including their values. Engine disagreement is a Rezono error and blocks the check. If the agreed set contains any row outside the original set, reject the candidate and report the excess rows.
3. The agreed subset is the explained set. The difference between the original and explained sets is the remainder. Check the original provenance of every remainder row before accepting it as a fact. With verified remainder rows restored in the isolated check, both engines must produce the original set. This second evaluation covers rules whose inferences change when retained facts are restored.
4. Require the candidate to be strictly smaller than its explained set. Compare the RFC 8785 canonical byte count of the candidate rule files plus the facts they require with the canonical byte count of the explained rows. The charged facts include required facts already present in the pinned input, added supporting facts and any completeness evidence the rule needs. Use deterministic ordering and typed row encodings. Include both counts and the charged inputs in the result. Equal sizes fail.

The initial acceptance cases use the [neutral conformance pack](../tests/fixtures/neutral/) to exercise a complete explanation, a partial explanation with retained sources, one excess row, a candidate that fails the size check, and a retained row whose origin is missing.

## Retained rows and provenance

For each row in the remainder, report its verified original sources and a `reason` message key using the [source contract](../contracts/source.yaml). An original source must resolve to the actual row or observation in the pinned evidence. A copy of a derived result cannot establish its own primary origin. Report a missing or unverified origin as a gap. A reason identifies why a sourced row remains a fact. It cannot fill a gap. Ordinary proposal review decides whether the evidence and resulting rule warrant acceptance.

Learners may use an absent tuple as a negative example only from a closed kind read in full, or from a verified completeness row covering that tuple in the relevant scope and snapshot. In every other case absence supplies no label. Confidence can order candidates. The exact compiler check still decides whether each candidate is eligible for review.

## Candidate learners

AnyBURL can search bottom-up, AMIE 3 can enumerate short Horn rules top-down, and Popper can propose small recursive logic programs. These are possible candidate sources. Learner trials generally require a concrete acceptance question. Run them outside the required checks with pinned releases and dependencies, verified licences, and a fixed seed or retained raw output.

One initial trial of AnyBURL is planned after the compiler command is available:

- Use the publication of `examples/platform/` at a pinned commit. Map kind membership `K(id)` to `(id, is, K)` and slot rows `K__slot(id, value)` to `(id, K__slot, value)`. Encode each identifier and value reversibly with its kind or type. Use the same projection for every kind and slot.
- Build official AnyBURL release `23-1x` from source archive SHA-256 `ef9857ffa918e93ac99884447e9ec1ddca987803af478f4c02d872136c35fd13` with a pinned JDK. Record the official project page as evidence of the BSD-3-Clause licence.
- Use a manually triggered workflow outside required checks with a 60-second learning run. Retain the raw output because the learner does not expose a seed. Replay that output against the same pinned publication and identify the replay as such.
- Translate every candidate with confidence of at least 0.9 into the ordinary rule language and run the exact compiler check. Report any candidate that cannot be expressed and explain why. An inexact candidate whose missing and excess rows together are at most 5% of the original set can suggest exceptions for review. An exception becomes a finding when a rule in the pack derives it with a proof.
- Record input, AnyBURL and JDK hashes, settings, raw candidates, check results, counterexamples, suggested exceptions, runtime and peak memory in `probes/anyburl/README.md`. Compare the replayed results with the original run. A separate decision will determine whether AnyBURL belongs in the import workflow.
