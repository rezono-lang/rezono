# A state for an entire set

Source `docs/semantics/value-cases.yaml#set-state-whole`.

## Deferral

The source asks for an explicit unknown collection carrying `no_inventory`. The [rule program contract](../contracts/rules.yaml) represents the members of a relation as rows. The language's [state rules](../docs/rezono/v0.md#7b-truth-and-value-states) describe aggregation over a known set. Neither provides an authored row form that distinguishes the proposed unknown collection from a completely known empty collection.

Revisit when the collection contract and both readers can represent those distinct inputs. The case must compare their counts and preserve the reason and cause of the unknown collection.
