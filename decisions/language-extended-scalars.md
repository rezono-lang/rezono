# Use Int for whole-number slots

An `Int` slot writes the same exact signed whole number as a LinkML slot with `range: integer`. Use the slot and cardinality syntax from [slot types and constraints](language-slots.md).

```rezono
rezono 0
pack sample
kind Gauge world closed
  quantity: Int?
```

The reader already gives the slot this JSON form.

```json
{"card":"?","slot":"quantity","type":"Int"}
```

Keep the ordinary module envelope selected by the authored tree. The example uses `rezono.module/1`. An independent extended declaration selects `rezono.module/2`, and a native rule selects `rezono.module/3`. All three use the same slot type text and ordinary pointer spans. Preserve the canonical bytes of the existing reader fixtures. Test the closed ModuleForm contract through its ordinary entry point.

Resolve a slot's type name against the declarations of its pack first, including names from another module of that pack. A declaration named `Int` keeps its existing meaning. Resolve an otherwise unbound `Int` as the built-in `integer` in each module format the compiler admits. The name resolution belongs to the compiler because the reader handles one module at a time. A named scalar alias keeps its authored schema identity under the existing alias decision.

Lower the slot through the same integer schema and storage path as LinkML. Preserve required and optional cardinalities, canonical decimal text in snapshots, and the existing signed BIGINT admission boundary. An absent optional value supplies no scalar row.

## Evidence

The native reader already parses, prints and reads back the existing type text in all three envelopes. The current compiler accepts `Int` in an extended form and refuses an otherwise unbound `Int` in the ordinary form of the example. The missing behavior is name resolution during lowering. A same-pack declaration named `Int` already produces a reference in the ordinary form.

Compare an authored module with a separately written LinkML integer schema. Require the same typed bundle attribute, engine column and rule IR. Admit `-4` and `9007199254740993` through the ordinary fact input. Include an absent optional value. Compare the stored and derived rows and check each result's ordinary witness independently. A probe of existing extended lowering and the equivalent LinkML schema produced the same two exact values, SQL, rule IR and checked witnesses.

Use positive reader coverage for the existing syntax and a red lowering case for the missing ordinary-form resolution. Include a same-module and a separate-module `Int` declaration as compatibility controls. Test the native envelope's slot form through its closed contract. End-to-end native rule lowering follows its [own acceptance cases](language-native-rules.md#11-red-tests-and-dependencies).

## Coverage

Count support for the authored whole-number input separately from the preview scalar forms. The native preview uses `DateTime` and `Money<EUR>`; these and `Ratio` need their own publication evidence. The existing [unit decision](language-units.md) and the [typed rule order decision](ordered-rule-scalars.md) describe their respective boundaries. The coverage inventory's other recognized LinkML ranges retain the compiler's existing admission rules.
