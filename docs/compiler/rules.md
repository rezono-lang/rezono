# Rules and explanation

The compiler turns schema tables and pack rules into a typed program. The SQL translators, explanation code and independent checker share its [rule IR](../../contracts/rules.yaml). The [native rule decision](../../decisions/language-native-rules.md) defines the authored Rezono rule surface. This page explains the execution semantics and shows the Datalog interchange already used in `rules/*.dl`. See the [language coverage](../rezono/language-coverage.md) for the status of the authored route.

## Rules

A base predicate reads a schema table, for example `item(id)` or `item__quantity(id, value)`. A declaration for a base predicate must agree with that table. Derived declarations give relation columns and their types. Body literals can be positive or negative. A positive anonymous variable stands for a fresh variable. Facts belong in fact inputs, and the rule reader rejects unsupported syntax such as disjunction or anonymous variables in negative literals.

```datalog
.decl available(i: symbol)
available(i) :- item(i), !reserved(i).

.decl joined(g: symbol, n: number)
joined(g, n) :- group(g), n = count : { member(g, _) }.
```

The compiler checks safety of bindings and strata before lowering. Aggregate groups use variables already bound by positive literals, while aggregate-local variables range over distinct contributing rows of the atom. A key column can contribute multiple equal values when those values belong to different contributing rows. An empty group gives zero for count and sum, and no result for minimum or maximum. The same distinction applies to a whole-relation aggregate without a grouping key. Several aggregates in one body retain separate positions and contributors in the evidence.

Numeric assignments bind a fresh variable. Integer division is truncated toward zero, and the divisor must satisfy the supported checks. Arithmetic in a recursive component normally fails. The bounded-counter profile admits an explicit positive increment with a fixed upper bound and constant starting points. The translator unrolls that profile and surfaces exhaustion as an error or integrity result at the relevant execution boundary. The checker's ordinary support and closure verification is separate from enforcing a compilation bound.

Rule IDs identify the relevant rule in its module, and the IR records its origin, stratum and witness. Derived and witness relation names must be distinct from the engine's existing names. The Soufflé tests compare supported rule results by reading both the normalized program and the source Datalog. [Reader tests](../../compiler/tests/test_rules_dl.py), [property tests](../../compiler/tests/test_rules_properties.py), [source oracle tests](../../compiler/tests/test_souffle_source.py).

### The semantic hash of a rule

The definition hash pins the exact pack bytes. A rule's stable identity names the authored rule in the bundle. The semantic hash is a canonical digest of the supported normal form. It abstracts from variable names, source location and body order where the normalized IR treats them as immaterial. It preserves distinctions such as relation names, argument order, polarity, group, aggregate operator and arithmetic. The hash is not a decision procedure for logical equivalence of arbitrary programs.

```bash
python -m rezono_compiler hash examples/library --rules
```

The definition pin is documented in [pack definitions](pack.md). The compiler's [normalization implementation](../../compiler/rezono_compiler/normalise.py) defines the semantic digest.

#### Questions

Question normalization would need to give the binder a canonical name, qualify paths from that binder and order operands where the typed operator is commutative. A cache would need the answer evaluated from the same normal form. A digest of the rule program alone does not establish equivalent answers to two question expressions. [Question expressions](../rezono/expressions.md), [explanation contract](../../contracts/explain.yaml).

### Calculation values in rules

A rule can read a numeric calculation selection from its pack or pinned import closure as `calc__<rule>(subject, value, "known", "")`. The selection is an open input. The supported read is positive and requires the known state with an empty reason. Unknown and invalid results are excluded. Negation and aggregation over a calculation selection or a relation downstream of one are refused. The access grant `may_read` cannot depend on a calculation selection.

The execution order is ordinary input tables, rules needed by the calculation, the calculation, then rules that read a selection. A calculation cannot depend on a downstream result of its own selections. The batch and publication paths use the same phase execution. The checker verifies the selection premise against the calculation evidence and applies the same access boundary as for other grounds. [Batch phases](../../compiler/rezono_compiler/batch.py), [calculation import tests](../../compiler/tests/test_calc_imports.py), [rule IR checker tests](../../checker/tests/test_rule_ir.py).

### Pipeline partition

The compiler can partition a program when the profile's build budget is exceeded. The usual default counts 64 rule views, including materialized witnesses. A deployment profile can set its budget, and the command supports `--max-views`. The compiler keeps recursive components intact and places them in dependency order. With `--previous`, a previous part can be retained when it still fits and the dependency order is valid. Oversized recursive components block compilation. Warnings and the plan report the cost and split at the chosen budget.

The integrity stage supplies the base checks and computes shared seal outputs once. A consuming part reads those outputs via the plan's imports and forwards, along with derived relations from earlier parts. The calculation stage imports the relations it needs. An epoch barrier must distinguish completion of one input round from the start of another. The view count is a partition metric. It gives no guarantee about compiler memory or total elapsed build time. [Partitioner](../../compiler/rezono_compiler/rules_split.py), [pipeline contract](../../contracts/pipelines.yaml), [protocol foundations](../formal.md#10-protocols-tla).

## Explanation

A witness relation records the rule bindings. To form the proof, the explainer resolves its positive premises, identifies the negative premises and counts and hashes the contributors of each aggregate group. Ranking selects a shortest grounded derivation with deterministic tie-breaking. Several derivations can remain valid, and a single chosen proof does not enumerate every row that could affect a scenario.

Materialized explain mode keeps witnesses in the exported relations. On-demand mode recomputes relevant witnesses for an explanation. A projection can create multiple witnesses for one conclusion. A checked `fold` mark on a helper affects display only. The compiler restricts marks to helpers whose form and uses allow them to be folded without hiding an independently named conclusion.

```bash
python -m rezono_compiler explain examples/library "$OUT"
```

The batch command computes explanations for the fact states it loads. Tracing follows ordered premises and contributor edges. A `grounds` answer reaches base rows and their permitted sources. An impact query follows dependencies from a change. A supposition recomputes the consequences of an assumed input. The checker independently interprets the rule IR, including bindings, conditions, assignments and contributions. [Explainer](../../compiler/rezono_compiler/explain.py), [trace](../../compiler/rezono_compiler/trace.py), [proof tests](../../checker/tests/test_proof.py), [source leaves](import.md#provenance-per-fact).

## Open world and named outcomes

A missing row can mean unknown. A closed relation gives a meaning to absence in a complete snapshot. Open-world conclusions require evidence for any claim about completeness.

### World per relation

A base relation defaults to closed. In the LinkML schema, `world: open` can declare the root kind's tables open or change the world of a slot table. A subkind uses its root's tables. Positive reads of an open relation propagate that world through derived rules. Except within a checked `@absence` relation, a rule cannot negate an open relation or use it as an aggregate source.

An `@absence` rule makes a statement about registration, such as the lack of a row in the available register. It does not certify that the real-world event never happened. A filter on an outcome's known row also supplies no global completeness guarantee. The world and relevant annotations travel in the IR and bundle. [Rule contract](../../contracts/rules.yaml).

### Named outcomes

`// @outcome <kind>` declares a relation of the element's identifier, state and reason. It names known, unknown and not-applicable states explicitly. Known has an empty reason. Unknown and not-applicable use stable reason keys, with messages in the pack's default language. A state can have multiple reasons where the contract permits them.

The compiler generates checks that every element has an outcome, every outcome names an element of the kind, and each element has one consistent state. The publisher and independent checker require those checks and the declared invariants to pass. A conclusion can carry the ordinary proof of a reason. A role without complete read access for a negative premise can lack the entire outcome row, whatever its state. An invalid input is reported by integrity checks. The state of a calculation value has its own [value contract](../../contracts/value.yaml).

### Staged acceptance

Declaring the world establishes what a negative rule can mean. Adding outcome rules then establishes which elements get an explicit state and proof. Publication tests must cover totality, conflicting states and blocked reads. A reading of the result can show the named state and reason already supplied by the pack. A missing result at the reader boundary grants no additional certainty.

### A relation that closes another

A `// @closes <relation>` marker declares that a proved closing tuple excludes all rows of the other derived relation sharing its key. The columns of the closer form a typed prefix of the target's columns. The compiler generates an invariant detecting overlap, and the checker requires the expected obligation in the rule IR. A close supplies an explanation through its own proof. A key with neither a matching row nor a matching close remains unknown when the target is open. The marker leaves the target's global world unchanged.

```datalog
// @closes permitted
.decl excluded(i: symbol)
excluded(i) :- item(i), active_exclusion(i).
```

The rule must cite the actual applicable grounds. Validating the marker or checking that the two relations are disjoint cannot supply those grounds by itself. [Rule IR](../../contracts/rules.yaml).

## Seal

A period close is an explicit fact, with an exclusive upper date bound and a set of element references with canonical row hashes. A root kind's `seal` annotation identifies its required single date slot. Each applicable close must cover a current row with its current hash. A close applies when the row falls before its boundary or the close already names that row. A row that was inserted late, changed or removed cannot silently change the closed result. A removed covered row also breaks the typed reference.

The compiler produces the row-hash relation and `<kind>__accepted` and `<kind>__refused`. A rule reading a sealed element's tables must bind the same element's acceptance. A refusal stays a named input known to the roles allowed to observe it. The checker recomputes the seal from the relevant rows. To propose a close, produce a delta and pass it to the canonical writer.

```bash
python -m rezono_compiler close "$WORK/pack" --close month_end --until 2026-02-01 --file facts/period-close.yaml
```

The dates and row hashes are data. The close needs no elapsed clock to take effect. The current scope is one sealed kind per pack. Calculations that need sealed kinds or their parts face additional compile-time restrictions. [Seal implementation](../../compiler/rezono_compiler/seal.py), [compiler tests](../../compiler/tests/test_seal.py), [checker access tests](../../checker/tests/test_seal_access.py).

### Parts

A related kind can name a required scalar owner arrow with `sealed_with`. Each part reaches one sealed element, possibly through another part. Cycles and unsupported ownership paths fail the compiler. The element hash covers the rows of the parts and their subkinds, so moving or editing a part can change the seal of each affected owner. A part gets an acceptance relation inherited from its owner's acceptance. A refusal affecting a whole element remains one refusal with evidence.

Reading acceptance, refusal or a row hash can disclose facts about any of the parts. A role needs the relevant full access before seeing those results. Across partitions the integrity stage is the single producer of each seal relation. Consumers for the same epoch receive that result through the normal part imports. [Partition and epoch boundary](#pipeline-partition).

## Sweep v1: `explore` and `sweeps.yaml`

The `explore` annotation declares a positive integer step for a single whole-number slot. In LinkML, a mapping-valued annotation uses the `value` wrapper, for example `explore: {value: {step: 10}}`. The optional minimum and maximum may narrow the slot's declared range. The compiler checks that the grid has at most 64 values, stopping at or before the maximum.

A top-level `sweeps.yaml` has one entry in the supported version. It selects a named fact cell by `kind`, `key` and `slot`. The record must occur in exactly one fact file. The compiler emits a checked grid, and the publish job evaluates the variants relative to the pinned base. Each value yields a kept result or diagnosis under the normal publication checks. A role's access to the cell and results governs what it can learn about the sweep. [Sweep compiler tests](../../compiler/tests/test_sweeps.py), [publisher tests](../../edge/publisher/tests/test_sweep.py).
