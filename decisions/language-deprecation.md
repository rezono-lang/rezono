# Deprecated declarations

A declaration can say that it is on its way out, with a note that names its replacement and the day until which it stays. The [language reference](../docs/rezono/v0.md#4b-language-version-and-deprecation), section 4b, already gives the spelling: one line directly above the declaration. This decision gives that line its place in the module form, so that the reader, the printer and the contract agree on it before W107 and R033 are built on it.

```rezono
deprecated "use ProviderZone" until 2027-07-01
kind Zone world closed
  name: Text
```

The corresponding JSON fragment is the declaration with one more member:

```json
{
  "kind": "Zone",
  "world": "closed",
  "slots": [{"slot": "name", "type": "Text"}],
  "derived": [],
  "deprecated": {"note": "use ProviderZone", "until": "2027-07-01"}
}
```

## Reading

- **One line above a declaration.** `deprecated "TEXT" until DATE` stands on its own line at the top level, directly above a kind or an enum, and belongs to that declaration. The note is a text on one line; the form holds it without quotes. The date is an ISO date.
- **Both parts are required.** A deprecation without its note gives no replacement to name, and one without a date gives no day after which removal is a minor change. A line without either is refused with R000.
- **Refusals.** A deprecated line with no declaration under it, a blank line between the two, and two deprecated lines above one declaration are refused with R000 at the second keyword or at the line that is not a declaration. A date that is no day of the calendar is refused with R012, as in a test.
- **Printing.** The printer writes the line directly above its declaration, with one space between the parts, as above.
- **Other declarations.** A deprecated slot, unit, parameter or rule follows in a later step; until then a deprecated line above anything but a kind or an enum is refused with R000 at `deprecated`.

## Format and meaning

A module that has a deprecated line uses at least `rezono.module/2`, the format of declaration metadata ([Schema identity and metadata](language-metadata.md)); `rezono.module/1` keeps its closed shape and bytes. The member changes nothing in the meaning of the declaration. W107 at a use from another pack, and R033 for a removal before the date, are checks on top of this member and follow in their own step.

## Lowering

A deprecated kind lowers to its LinkML class, and a deprecated enum to its LinkML enum, with two additions and nothing else changed: `deprecated` holds the note, and the annotation `deprecated_until` holds the date as written. LinkML has a `deprecated` text on every element but no field for a date, and an annotation is where a module already keeps what LinkML has no field for, as `layer` shows. A schema file of a pack writes the same two entries for the same deprecation.

```yaml
classes:
  Zone:
    deprecated: use ProviderZone
    annotations:
      deprecated_until: '2027-07-01'
```

## Considered

- **An indented `deprecated` line inside the declaration, like a description.** It would match the metadata block, but the language reference already writes the line above the declaration, and a reader sees the warning before the declaration it warns about.
- **The note as an expression node, as a text in a question is.** The note is no value that is computed or compared; it is shown as written, like a description.
