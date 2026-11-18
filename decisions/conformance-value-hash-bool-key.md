# Canonical text for a Boolean key component

Source `docs/semantics/value-cases.yaml#hash-bool-key`.

## Adopted behavior

A typed Boolean key component has the lowercase text `true` or `false` in the shared snapshot key. The publisher's fact-source lookup and the proof RowRef must identify the same row with that text.

Use both truth values and compare the resulting key with the same row's provenance key. The [publisher Boolean key test](../edge/publisher/tests/test_source_sets.py) gives the canonical true example and verifies that the input has the required key shape.
