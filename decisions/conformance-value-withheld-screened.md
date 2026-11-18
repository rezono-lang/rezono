# Choose a complete readable proof

Source `docs/semantics/value-cases.yaml#withheld-screened`.

## Adopted behavior

Under access semantics 2 a role receives a conclusion when it has a complete readable proof. If its first proof depends on a hidden premise, select an available fully readable proof. Withhold the conclusion when no such proof exists. The role witness set has an empty `hidden` list.

Verify both cases using the same conclusion with and without a readable alternative. The [manifest witness contract](../contracts/manifest.yaml) and [publisher proof-choice tests](../edge/publisher/tests/test_publish.py) establish the expected evidence.
