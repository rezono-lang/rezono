# Exact-quote pack written in Rezono

The first pack under `run/packs/` that moves to the language is `exact-quote`. It has no imports and
no importers, so its conversion touches no `sha256` pin.

## What was chosen

- **The converter makes the module.** `scripts/convert_pack.py` writes `rezono/quote.rezono` and its
  form. The schema becomes Rezono declarations; the Datalog stays a `|` block in the same module. Native
  rules are a later step and are not part of this conversion.
- **Two edits to the legacy source first, both without meaning.**
  - The four members of `QuoteOperand` are written as `name: {}` instead of `name:`. LinkML reads both
    as a permissible value without metadata, and the compiler gives the same enum. The converter does not
    yet accept a member with no value at all.
  - `rules/amount.dl` is renamed to `rules/quote.dl`. The converter names a module after its file, so a
    rule file whose name differs from the schema module becomes a second module and changes the module
    identity. Under one name, the schema and its rules are one module, as before. A rule file name is a
    source position: its change does not change any fact, conclusion or ground.
- **The old form is kept as the oracle.** `run/fixtures/exact-quote-linkml/` holds the replaced
  `schema/quote.yaml` and `rules/amount.dl` byte for byte. The folder has no `pack.yaml`, so it is not a
  pack and no inventory counts it. `run/tests/test_exact_quote_language.py` rebuilds the legacy pack from
  it beside the unchanged presentation files and compares it with the converted pack on every pull
  request:
  - the typed schema, labels and channels, as the converter compares them;
  - every derived relation of the production quote evaluation, for a priced quote, repeated identical
    lines, an empty quote and a line without price digits;
  - for recorded quotes, the publication comparison of the converter: facts, conclusions and typed
    columns, the union of checked grounds per conclusion, and what each role sees;
  - a counter-case: a rule that ignores one digit value fails that comparison.

## What was considered

- **Wait for the converter to accept the pack as it was.** That postpones the first conversion of a run
  pack for a change that alters no meaning. The edits are visible in the oracle and covered by the
  same comparison.
- **Convert by hand.** The converter exists and accepts the pack after the two edits, so a hand
  conversion would only add a second, unchecked route.
- **Drop the old form after conversion.** Then nothing could show later that the converted pack still
  means the same. The two retained files cost little and keep the comparison running.

## Consequences

- `run/exact_quote.py` reads the pack as before; the compiler reads the module through the Node 24
  reader that the Python checks already install.
- When the converter accepts a member with no value and a rule file under another name, the retained
  oracle still needs no change.
