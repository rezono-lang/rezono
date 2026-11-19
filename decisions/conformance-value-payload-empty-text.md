# Reject an empty payload on an unknown value

Source `docs/semantics/value-cases.yaml#payload-empty-text`.

## Adopted behavior

Reject a wire cell carrying `{"state":"unknown","value":""}`. The canonical unknown cell has no payload member. A known Text cell may have the same empty string as its actual value.

Use the unknown cell without `value` and the known empty cell as controls. The [Value contract](../contracts/value.yaml) and [checker snapshot tests](../checker/tests/test_snapshot_values.py) distinguish both from the malformed cell.
