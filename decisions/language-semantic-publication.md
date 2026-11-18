# Comparing two source forms of a pack

A migration uses the same pack identity, imported definitions, data, evaluation dates, roles and scenarios on both sides. Publish once from the existing source and once from the Rezono source. Keep the two build directories and manifests separate.

| Part of the oracle | Compare across the two publications |
| --- | --- |
| Facts | Every relation, typed column, primary key and row for each dataset. Preserve multiplicity, missing versus explicit unknown, units, validity and knowledge dates. |
| Conclusions | All computed rows, values, states and reason codes, including empty relations and negative findings. Compare within the same role and scenario. |
| Proof | Validate every witness in its own publication, including on-demand alternatives. For each conclusion, compare the union of grounds across all founded witnesses. Include positive base and intermediate relation keys, exact negative keys, group scopes and contributors, and selection candidates, exclusions and tie-break inputs. Repeated reads contribute one ground. A substituted premise fails even when its key and the conclusion are unchanged. [Migration equivalence](language-expression-semantics.md#4-migration-equivalence) |
| Presentation | Compare roles, visibility, page and field order, message keys and arguments, labels and rendered values per language. Preserve ordered arrays. |

Enumerate the expected relations, states, roles and languages from the authored inputs. Missing output on both sides must fail. Give each new publication field an explicit comparison or provenance check before accepting its output. Sort a collection only when its contract treats it as unordered.

Within **each** publication, resolve source files beneath that publication's own input root. Check bindings, rule and witness references, declarations and source locations against the owning rule or slot. Validate manifest and definition pins against that publication's own bytes using the applicable contract. Retain checked origins for replay. Rule and witness IDs, variable names, ordinals, locations and hashes may differ across publications whose checked grounds and visible results agree.

The first executable slice uses the independently written kinds.yaml and kinds.rezono module fixtures, with explicit data, expected integrity results and presentation sentences. Each representation has its own declaration-location oracle. This schema fixture has no derivation rule. A conversion with rules requires proof coverage before its original files can be retired. For each later pack, record its reviewed semantic projection only after the two live paths and both provenance checks pass. A single publication digest would mix source edits with changes in meaning.

The platform example supplies five concrete uses. Exercise a step sequence and position for std-order, product and delivery membership for std-part, agreement and a conflicting identification for std-identity, release support with a missing time boundary for std-time, and role-specific access for std-access. Each case needs a named input, an independently reasoned conclusion and a witness checked against its local source. A pack import alone supplies none of these outcomes. Platform owns these cases until its work and the loop example are complete.
