---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: readable-rules
---

# Readable rules: properties, counting, the module header and the rule's sentence

The first goal of the [language reference](../docs/rezono/v0.md), section 1, is that a rule reads like the thought behind it. Schemas, facts, parameters and tables mostly do. Native rules and counts do not yet: the acceptance pack of [expression semantics](language-expression-semantics.md) writes a count as `n = (edge(_, _) where it.pred = x).count()`. No pack in `examples/`, `packs/` or `run/packs/` writes native rules yet, so a change of spelling costs little now and much after the packs are converted.

This decision takes four candidates and adopts or rejects each. Conversion of rules does not wait for it: a module that already uses a spelling this decision replaces gets a warning with the new spelling as its hint.

Three constraints hold for every adopted spelling.

- **Tokens stay tokens.** Following the decision of 2026-11-19, `?`, `*`, `+`, `..<`, `@`, `-` and `_` keep their form, and no candidate adds a word for any of them.
- **One core, one way.** Each adopted spelling desugars deterministically to the IR that an existing spelling already gives (v0 §1, goal 4), and each thing has one way to write it (goal 5). Where an existing spelling and an adopted one would both remain, the existing one is deprecated.
- **A valid text keeps its meaning** (goal 6, v0 §4b). No adopted spelling changes what an existing valid text means under `rezono 0`. A spelling that this decision replaces is *deprecated* in `rezono 0`: it keeps its meaning and gives W107 at every use, naming the replacement. It is *removed* in `rezono 1`, where it is R028, as the deprecation table of v0 §4b gives it. A change that would alter the meaning of existing text is assigned to `rezono 1` and named as such below.

| Candidate | Outcome | Reopens a settled choice |
|---|---|---|
| A property where there is a subject | adopted, with the boundary below | no; the rejection of "every relation as a `derived` slot" in [native rules](language-native-rules.md) stands |
| Simpler counting and summing | adopted within the method form; a second form is rejected | no; v0 §2 "method form only" stands |
| A shorter header | adopted | no; the default world stays `open` |
| The sentence and the source at the rule | adopted | no |

## 1. A property where there is a subject

**Adopted.** A value, or a set of values, that belongs to one element of a kind is written as a derived property of that kind, as v0 §5 already allows:

```rezono
kind Offer world closed

kind Product world closed
  offers: Offer*

kind Demand world closed
  product: Product

extend Demand
  derived offers: Offer* = product.offers
```

**The boundary.** A relation is a property when it has exactly two columns, the first is an element of a kind (the subject), and every clause gives the second column from the subject alone. Everything else stays a `rule`: a relation with three or more columns, a relation between two independent things, and a relation whose clauses join other rule variables. That keeps the rejection in [native rules](language-native-rules.md): an n-ary relation needs no artificial subject, and its independent proofs stay visible.

**Lowering.** The type of the property decides where it lowers.

- A property whose type is a kind (`T`, `T?`, `T*` or `T+`) lowers to a derived relation of the rule IR named as a slot row is named: `<kind>__<property>`, with the key columns `id` and `v`, exactly as the slot row `product__offers` has them; above that is `demand__offers`. Its clause reads the subject's membership first (`demand(?d)`), then the premises of the expression in binding order, as a native rule body lowers ([expression semantics](language-expression-semantics.md), section 1). For `product.offers` that is `demand__product(?d, ?p)` and `product__offers(?p, ?o)`. A single-valued property (`T`) that has two values for one subject is R008, as the reference says.
- Every other property is a calculation and lowers as [calculations](language-calculations.md) give it, to `rezono.calc/1`. Publishing those waits for that lowering (`test_lower_calculation`); a property that reads an inverse slot waits for [inverse references](language-inverse-references.md) to be read in rules.
- Rules and questions read the property as they read a slot: `Demand.offers(d, o)` in a rule, `demand.offers` in a question. It is no fact: a fact that sets it is refused as for an inverse slot.

**The old form.** A rule with the shape of a property, written today as

```rezono
rule offers(d: Demand, o: Offer) when o in d.product.offers
```

keeps its meaning and its relation `offers`, and gives W107 at its name with the replacement `extend Demand` / `derived offers: Offer* = product.offers`. The reader recognises the shape from the text alone: two typed columns, the first a kind, and a body that is exactly one `v in E` (for `T*`) or `v = E` (for `T`) where `v` is the second column and `E` is a path that starts at the first column. A rule with any further condition gets no warning. Following the hint renames the published relation, so it is a major change of the pack's surface (v0 §4c) and the author's choice; the language does not make it.

## 2. Simpler counting and summing

**Adopted within the method form.** A count or a sum over a relation fixes columns in the call and names the measured column bare:

```rezono
rule order_line(order: Order, item: Line, cents: Int) when Line.order(item, order) and Line.cents(item, cents)

rule line_count(o: Order, n: Int) when o in Order
  and n = order_line(o, _, _).count()

rule order_total(o: Order, total: Int) when o in Order
  and total = order_line(o, _, _).sum(cents)
```

- **Fixed columns go in the call.** A relation call already matches rows, with constants and bound names fixing columns and `_` leaving them open ([native rules](language-native-rules.md), section 1). Inside a rule, an aggregate filter can only fix key columns by equality (native rules, section 5), so `(order_line(_, _, _) where it.order = o).count()` says nothing that `order_line(o, _, _).count()` does not. Both lower to one aggregate with the terms `[?o, _, _]`. The filter form is deprecated: W107 at the whole aggregate expression, from its opening parenthesis to the closing parenthesis of `count()`, naming the call form. Filters keep every other use: in a question, and in a derived value.
- **Element names resolve bare.** Inside the parentheses of an aggregate in a rule, the columns of the aggregated relation resolve first, as they already do in a question ([expressions](../docs/rezono/expressions.md), section 5, rule 2). So `sum(cents)` measures the column `cents`; `sum(it.cents)` stays valid and means the same. A name that is both a column of the aggregated relation and a name bound outside is R011, at the bare name, as in a question; `it.cents` names the column. Today a bare name there is refused, so no valid text changes meaning. This replaces the measure form `it.c` in the lowering table of native rules, section 5.

**Whole rows and empty groups.** Both points follow from [native rules](language-native-rules.md), sections 4 and 5. They are stated here because a reader who does not know the language can doubt them.

- **A count or a sum ranges over whole rows.** `_` leaves a column open in the match; it does not take the column out of the row. `order_line(o, _, _)` matches every line of `o`, and each of those lines is one member, also when two lines have the same amount. Two lines of 250 cents give `count()` = 2 and `sum(cents)` = 500, never 250. To count distinct amounts, write a rule whose columns are the amounts, and count its rows.
- **An empty group gives zero.** In `rule order_total(o: Order, total: Int) when o in Order and total = order_line(o, _, _).sum(cents)`, an order without lines gives `total` = 0, and `line_count` gives `n` = 0. It is not left out. The group is bound by a positive premise (`o in Order`), and the aggregated relation is complete, so "no rows" is known. A rule that should give no result for an order without lines says so with its own premise, such as `has_line(o)`, as the subsidy scheme does with `has_quote(a)` before it sums. An aggregate over an open relation is refused (R004, [expressions](../docs/rezono/expressions.md), section 6), so a 0 never comes from rows that are merely absent.

**A second form is rejected.** `count edge where pred = x`, or any comprehension next to the method form, would reopen v0 §2 ("method form only") and the rejected "new comprehension" of native rules. It buys nothing the call form does not already give, and it would give every count two spellings.

## 3. A shorter header

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

## 4. The sentence and the source at the rule

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
| a rule with the shape of a property | W107 at the rule's name | `extend K` / `derived name: T* = E` |
| `(r(_, …) where it.c = x).count()` in a rule | W107 at the aggregate | `r(…, x, …).count()` |
| `import "linkml:types"` as the only import | W107 at the line | leave it out |
| `default range Text` | W107 at the line | leave it out |
| `annotation layer = "<layer>"` | W107 at the line | leave it out |

Each keeps its meaning in `rezono 0` and becomes R028 in `rezono 1`.

## Considered

- **Reject the property and keep every relation a rule.** Readers then see `rule offers(d, o) when o in d.product.offers` where the domain expert thinks "the offers of a demand"; the reference already has `derived x: T*` for that.
- **Lower a property to a relation named after the property alone.** Two kinds with a property of the same name would collide, and a rule could not tell a stored slot row from a derived one by the way it reads it.
- **Named arguments in a call (`edge(pred = x)`).** `pred = x` is already an expression, so the call would parse two ways.
- **A word for `_` or `*`.** Excluded by the decision of 2026-11-19.
- **Defaults written into the form by the reader.** Every existing form, and so every pack hash, would change without a change of meaning.
- **The sentence as a doc comment (`---`).** A doc comment describes a declaration in the viewer; the sentence explains one conclusion, with placeholders, per clause.
