# Keep a known Text value that spells unknown

Source `docs/semantics/value-cases.yaml#bare-state-text`.

## Adopted behavior

A known Text slot containing the word `unknown` keeps that string as its payload, with state `known` and no reason. An explicitly typed unknown cell instead carries a state and any authored reason.

Compare the literal text and explicitly unknown form through the value reader. The [Value contract](../contracts/value.yaml) distinguishes payload from state, and the [native rule decision](language-native-rules.md) names the string and the state as separate inputs.
