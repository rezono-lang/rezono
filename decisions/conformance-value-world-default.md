# Default world for a LinkML kind

Source `docs/semantics/value-cases.yaml#world-default`.

## Adopted behavior

A kind loaded from LinkML without a world annotation is closed. A missing row is false as a membership proposition. An explicit open annotation makes the same missing row unknown. Slot cardinality still determines the value state for a missing value.

This decision covers the LinkML schema input and its rule IR. Native Rezono declarations have the open default described in the language reference. The [RuleProgram contract](../contracts/rules.yaml), [publication lowering](../docs/rezono/publication.md#4-value-states) and [compiler world tests](../compiler/tests/test_rules_dl.py) describe the boundary.
