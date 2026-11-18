# Comparing two source forms of a pack

A migration uses the same pack identity, imported definitions, data, evaluation dates, roles and scenarios on both sides. Publish once from the existing source and once from the Rezono source. Keep the two build directories and manifests separate.

| Part of the oracle | Compare across the two publications |
| --- | --- |
| Facts | Every relation, typed column, primary key and row for each dataset. Preserve multiplicity, missing versus explicit unknown, units, validity and knowledge dates. |
| Conclusions | All computed rows, values, states and reason codes, including empty relations and negative findings. Compare within the same role and scenario. |
| Proof | Resolve each witness in its own publication. Compare the conclusion, rule meaning, bindings, premise relation and key, polarity, stratum and dependencies. Preserve witness multiplicity and any order that affects interpretation. A changed premise must fail even when the conclusion holds. |
| Presentation | Compare roles, visibility, page and field order, message keys and arguments, labels and rendered values per language. Preserve ordered arrays. |

Enumerate the expected relations, states, roles and languages from the authored inputs. Missing output on both sides must fail. Give each new publication field an explicit comparison or provenance check before accepting its output. Sort a collection only when its contract treats it as unordered.

Within **each** publication, resolve source files beneath that publication's own input root. Check the declaration, source location and the owning rule or slot. Validate manifest and definition references against that publication's own bytes using the applicable contract. Keep the checked origin attached to each normalized witness. A valid reference in the other publication cannot repair a stale reference here.

The first executable slice uses the independently written kinds.yaml and kinds.rezono module fixtures, with explicit data, expected integrity results and presentation sentences. Each representation has its own declaration-location oracle. This schema fixture has no derivation rule. A conversion with rules requires proof coverage before its original files can be retired. For each later pack, record its reviewed semantic projection only after the two live paths and both provenance checks pass. A single publication digest would mix source edits with changes in meaning.

The platform example supplies five concrete uses. Exercise a step sequence and position for std-order, product and delivery membership for std-part, agreement and a conflicting identification for std-identity, release support with a missing time boundary for std-time, and role-specific access for std-access. Each case needs a named input, an independently reasoned conclusion and a witness checked against its local source. A pack import alone supplies none of these outcomes. Platform owns these cases until its work and the loop example are complete.
