---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: readable-rules
---

# Readable rules: the module header and the rule's sentence

The first goal of the [language reference](../docs/rezono/v0.md), section 1, is that a rule reads like the thought behind it. Schemas, facts, parameters and tables mostly do. A module still opens with header lines that only repeat defaults, and a rule's sentence for readers and its article live in other files. No pack in `examples/`, `packs/` or `run/packs/` writes native rules yet, so a change of spelling costs little now and much after the packs are converted.

This decision adopts two changes: a shorter header, and the sentence and source next to the rule. Two further candidates, a derived property where a relation has one subject and a simpler spelling for counting and summing, stay open for a proposal on one form of derivation in a following language version; this decision neither adopts nor rejects them. Conversion of rules does not wait for it: a module that already uses a spelling this decision replaces gets a warning with the new spelling as its hint.

Three constraints hold for every adopted spelling.

- **Tokens stay tokens.** Following the decision of 2026-11-19, `?`, `*`, `+`, `..<`, `@`, `-` and `_` keep their form, and no candidate adds a word for any of them.
- **One core, one way.** Each adopted spelling desugars deterministically to the IR that an existing spelling already gives (v0 §1, goal 4), and each thing has one way to write it (goal 5). Where an existing spelling and an adopted one would both remain, the existing one is deprecated.
- **A valid text keeps its meaning** (goal 6, v0 §4b). No adopted spelling changes what an existing valid text means under `rezono 0`. A spelling that this decision replaces is *deprecated* in `rezono 0`: it keeps its meaning and gives W107 at every use, naming the replacement. It is *removed* in `rezono 1`, where it is R028, as the deprecation table of v0 §4b gives it. A change that would alter the meaning of existing text is assigned to `rezono 1` and named as such below.

| Candidate | Outcome | Reopens a settled choice |
|---|---|---|
| A shorter header | adopted | no; the default world stays `open` |
| The sentence and the source at the rule | adopted | no |

## 1. A shorter header

**Adopted.** Four header lines become defaults that a module names only to deviate from them. The compiler already fills them in when a module leaves them out; this decision makes that the rule and makes the lowering independent of whether the `schema` line is written.

| Line | Default |
|---|---|
| `iri "…"` | `https://rezono.org/rezono/<pack>/<module>` |
| `import "linkml:types"` | `linkml:types` is imported |
| `default range Text` | `Text` (LinkML `string`) |
| `annotation layer = "facts"` | the layer of the module's registration in `pack.yaml` |

```rezono
rezono 0
pack exact-quote

schema exact_quote
  language en
```

- **The form and the pack hash stay the same.** The reader never writes a default into the module form: a header that leaves a line out has no member for it, and a header that writes it keeps its member as written. So an existing file keeps its bytes, its form and the definition hash that covers both ([definition hash coverage](pack-hash-coverage.md)). Defaults are applied once, when the compiler lowers the form.
- **One lowering.** A module without a `schema` line, a module with `schema <module>`, and a module that writes all four defaults explicitly lower to the same LinkML schema, byte for byte. The schema name defaults to the module's name. The `layer` annotation lowers as `layer: <layer>` in each case, as a module without a header lowers it today.
- **Writing a default is deprecated.** `import "linkml:types"` as the only import, `default range Text` and `annotation layer = "<layer>"` give W107 at the line, with "leave it out" as the hint. A `layer` annotation that disagrees with the registration is refused, as today, so a written layer annotation is never needed. An `iri` gives no warning: the reader does not know the module's name, and an `iri` that deviates is the usual case.
- **Imports.** In `rezono 0`, a written `import` list replaces the default, as it does today, so a header that imports anything else still writes `import "linkml:types"` and gets no warning for it. From `rezono 1`, `linkml:types` is always imported and written imports add to it; that changes the meaning of a header that leaves it out, so it waits for that version.
- **Worlds.** The default world stays `open`, as v0 §5 and [the default world for a LinkML kind](conformance-value-world-default.md) give it. The header has no world line.

## 2. The sentence and the source at the rule

**Adopted.** A rule clause can carry its sentence for readers and its source next to it, as a parameter and an exception line already carry their source with `@`:

```rezono
rule offers(d: Demand, o: Offer) when d in Demand and Demand.product(d, p) and Product.offers(p, o)
  means "{$d} can buy {$o}." @ policy#art-3
```

- **Reading.** A deeper line that starts with the contextual word `means` and a text ends the clause's expression and gives its sentence. It may end with `@ <source>#<locator>`. A clause without a sentence carries its source with `@` at the end of its last line: `rule listed(item: Item) when item in Item  @ policy#art-3`. Neither form is valid today: a name or a text cannot follow a complete expression, and `@` is no expression operator. The rule declaration in `rezono.module/3` gets the members `means` (the text, without quotes) and `source` (the text after `@`, as an exception line stores it). Refused with R000: a `means` without a text, a second `means` line in one clause, and a second `@` in one clause.
- **One sentence in the default language.** Following [reason declarations](language-reasons.md), the sentence lowers to the clause's message, the key that the compiled bundle already gives the clause in `message`, in the messages of the pack's `default_language`. It is written in the language of the pack's names. The placeholders `{$name}` name the clause's variables, as in a message file. `\`, `{` and `}` that are not placeholders are escaped with a backslash.
- **One source per sentence.** A clause with `means` whose message key the message file of the default language also gives is refused at the `means` line. Sentences in other languages stay in `messages/<lang>.mf2`.
- **The source.** The rule entry of the compiled bundle gets the member `source` with the text after `@` as written, as an exception line's source travels with its value. The explanation of a conclusion can then name its article.

## Old forms and warnings

| Old form | Warning | Hint |
|---|---|---|
| `import "linkml:types"` as the only import | W107 at the line | leave it out |
| `default range Text` | W107 at the line | leave it out |
| `annotation layer = "<layer>"` | W107 at the line | leave it out |

Each keeps its meaning in `rezono 0` and becomes R028 in `rezono 1`.

## Considered

- **A word for `_` or `*`.** Excluded by the decision of 2026-11-19.
- **Defaults written into the form by the reader.** Every existing form, and so every pack hash, would change without a change of meaning.
- **The sentence as a doc comment (`---`).** A doc comment describes a declaration in the viewer; the sentence explains one conclusion, with placeholders, per clause.
