# An unknown value keeps its reason code

Source `docs/semantics/value-cases.yaml#value-reason`.

## Adopted behavior

A snapshot cell with an authored reason `not_assigned` carries `{"state":"unknown","reason":"not_assigned"}`. Readers preserve that code and the absence of a payload. The presentation layer can look up the code in the pack's message catalogue.

The case should round-trip the cell and check that a supplied prose reason is rejected. The [Value contract](../contracts/value.yaml) defines the code and the [checker snapshot tests](../checker/tests/test_snapshot_values.py) exercise both round-trip and rejection.
