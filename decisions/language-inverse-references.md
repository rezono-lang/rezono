# Inverse references

A slot that lists the records pointing at its kind writes `inverse` and the name of the forward slot after its type and cardinality: `parties: Party+ inverse holder` on `Holder` reads every `Party` whose `holder` is this holder. The slot member `inverse` holds that name (contracts/rezono-module.yaml, `SlotShape`). An inverse holds no data of its own: it is the forward slot read with its two ends exchanged, as the [native rules decision](language-native-rules.md) already reads it in a rule.

```rezono
kind Party world closed
  holder: Holder

kind Holder world closed
  parties: Party+ inverse holder
```

The corresponding JSON fragment is the second slot:

```json
{
  "slot": "parties",
  "type": "Party",
  "card": "+",
  "inverse": "holder"
}
```

## Lowering

- **LinkML `inverse`.** The slot lowers as the same slot without `inverse` lowers, plus the LinkML slot property `inverse` with the forward slot's name. Cardinality keeps its meaning: `+` at least one, `*` any number, no suffix exactly one.
- **The forward slot must exist and point back.** The kind named by the type must have a slot with the name after `inverse`, and that slot's type must be the kind that declares the inverse. Anything else is refused at the inverse slot's line.
- **No facts of its own.** A fact never sets an inverse slot. The compiler reads it from the forward slot's table. Reading the inverse in rules and checks, and refusing a fact that sets it, are a separate step after this lowering.

## Considered

- **Store both directions.** Two tables for one link can disagree, and nothing would say which is the source.
- **Drop the inverse when lowering.** The schema would then lose the name that rules, questions and views use, and the bundle would no longer say what the author wrote.
- **A derived value (`derived parties: Party* = ...`).** It needs an expression over all records of a kind, which is longer than the one word, and it hides that the two slots are one link.
