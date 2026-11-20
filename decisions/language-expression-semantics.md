---
decider: [language, core]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: in_force
subject: language-expression-semantics
---

# Shared expression semantics for questions and rules

Questions and rules use the same expressions, types, states and grounds. A question starts with a readable subject and classifies the expression's result. A rule can bind variables by matching rows and emits one tuple for each binding that satisfies its guard.

A closed relation can establish a missing tuple under the right coverage. A comparison that can be undecided may also omit its tuple. Those two facts are independent. For example, negating a comparison on an unknown value preserves the unknown, while an anti-join against its success rows would manufacture a true result.

## 1. Expressions and evidence

The linked expression records its logical type and cardinality, incoming and exported bindings, possible states, signed relation dependencies and required evidence. Evaluation supplies a value or truth state, reason, cause and witness. The authored form preserves syntax and source spans.

A positive binding comes from a row or member. A computed binding can feed the head and subsequent expressions. A negative key or correlated group key requires a constant or a positive binding. Full coverage means checked coverage for the inspected range in the pinned snapshot and role. The scope and its expected inventory must be established independently of the rows the read returned. Authorization to read the whole range remains a separate requirement. See [witnessed read completeness](witnessed-read-completeness.md).

The [normative tables in Appendix A](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) give five truth values, T, F, N, U and I. The last three are `n/a`, `unknown` and `invalid`. Strict operators compute on known inputs and otherwise propagate the highest state in N < U < I. For equal states, take the least reason by UTF-8 bytes, then the least cause by relation and canonical key. A constant with no cause sorts first among operands with the same reason.

| Expression | Binding and type | Value state | World and coverage | Checked grounds |
| --- | --- | --- | --- | --- |
| Literal, variable, identifier | A literal binds nothing. A name in value position needs a binding. Typed heads and `with` declare types. Identifier projection returns the key of a bound subject. | Retain the type and state of the literal or binding. | A key projection requires the subject's existing evidence. | Replay the typed value or substitution. Project the key without adding an identifier or membership premise. |
| Path | Resolve hops through the linked schema, with inheritance, views and inverses. A repeated hop yields a collection. An equivalent positive slot-row equality can bind its endpoints. | Strict per hop. A missing required scalar is U. A missing optional scalar is N with closed, fully read omission evidence. Conflicting scalar rows give I. An unknown forward value can leave inverse membership undecided. | A partially read scalar miss is U with `not_read_in_full`. For an inverse, take the world of the forward slot and its population into account. | Verify the forward rows in traversal order, or the Value and origin, conflicting rows or checked omission. |
| Call `r(terms)` | Positive patterns bind fresh names from columns, join repeated names and match constants. Each `_` ranges separately. Value calls take bound arguments. A collection of matches exposes the complete named row. | Strict in arguments. A readable match proves T. A covered miss of a total closed predicate gives F. An open miss can give U with `open_world`. For a partial predicate, recover its keyed outcome to distinguish F, N, U and I. | Positive matching can use an open relation. A definitive negative answer needs coverage. A scan of recorded tuples may have a defined result even when the predicate computed by those tuples is partial. | Verify the resolved relation and full key, including each matched wildcard and any intermediate derivations. Verify an absent key in its exact scope. |
| Membership and range | Positive membership can bind an element. `x in K` reads a kind row. A ground test checks compatible types and the written range bounds. | Fold membership and equality by `or`. A known equal member decides T. Literal ranges compare strictly with the written endpoint inclusion. | One readable match suffices. A collection miss needs complete closed coverage to decide F. | Replay the matched row, the inspected range and failed matches, or the checked literal bounds. |
| Comparison | Require compatible scalar types, dimensions and ordering. Equality between free names supplies no domain. A positive scalar path equality can bind the known slot value. | Strict, including N = N giving N. A row pattern can match one of several conflicting rows. A scalar comparison must check the slot's cardinality. | Inherit the operand reads and worlds. To prove a known inequality, use the values that differ. | Check both operands and the operation. Replaying a failed search for equality alone cannot prove inequality. |
| Arithmetic and result assignment | Check scalar operands, dimensions and representation. `n = k + 1` introduces a fresh computed value. | Strict and exact. `/` preserves exact division. In rule IR, `quotient` truncates toward zero with a nonzero constant divisor. | Inherit operand reads. Arithmetic itself needs no closure. | Replay values, conversions and the operation, including signed 64-bit bounds where the IR requires them. Refuse an unrepresentable lowering or return its defined invalid state. |
| `a and b` | Check in binding order and export compatible successful bindings. | Any F determines F, all T gives T, and otherwise propagate the highest state. | A true conjunction needs both branches. A false branch can decide F from its own grounds. | Check the two true premises or evidence sufficient for the actual decision and cause. |
| `a or b` | Start with the same incoming bindings in both branches. Export a binding only if all statically possible successful branches bind it compatibly. | Any T determines T, all F gives F, and otherwise propagate the highest state. | One complete readable true alternative suffices. To prove both branches false, check both reads. | Preserve founded alternatives. A cycle supplies evidence only through a founded instance. |
| `not p` | Exports no binding. Scalar operands must be evaluable. An anti-join needs a bound exact key without a wildcard. | Swap T and F. Preserve N, U and I with their reasons and causes. | Scalar negation inherits the operand grounds. An absent-key test needs a permitted world, full coverage, a lower stratum and a decided predicate. | Replay the truth-table step or the checked absent key. |
| `S.any(p)` | `it` is local. This is the existing existential form. A positive rule pattern with locals can also supply a witness. | Fold membership and predicate by `or` from F. A true match decides the fold. | An open domain can yield a readable match. A definitive false result needs coverage and every member's contribution to the fold must give F. | Verify a matching predicate and row, or all relevant memberships and predicate outcomes for a definitive miss. |
| `S.none(p)`, `S.all(p)` | Use the same local element scope as `any`. | `none` negates `any`. `all` folds membership implication by `and` from T. A known empty complete domain makes both true. | Both require a closed domain. Reduction to absence of a counterexample also needs full coverage and a total counterexample test. | Check a decisive counterexample where sufficient. Otherwise replay the whole fold with the undecided members. |
| `S where p` | Bind `it` locally and resolve named fields and outer variables by the existing scope rules. An ambiguous bare name gives `R011`. Retain full element keys. | T includes, F and N exclude, U and I keep an uncertain membership with its cause. | The filter inherits its source world. Include the predicate reads that can affect membership. | Check each included, excluded or uncertain member when required by the result, or reconstruct the fixed-key range from the scoped snapshot. |
| `count`, `sum`, `min`, `max` | Local element names and wildcards stay local. Group parameters come from positive outer bindings. Counts are integers and value folds retain the checked measure type. | Strict in the collection, membership and consumed values. Empty count and sum give zero. Empty min and max yield N with `empty` and produce no numeric tuple. A sum of known 7 and N gives N. | A whole-group result needs a closed, fully read domain. A partial predicate's success rows alone do not establish its collection of decided members. | Verify occurrence, relation, fixed terms and grouping key, full contributor keys, measure, count, digest and result. Equal amounts from distinct keys both contribute. |
| Filtered aggregate | Apply the filter and fold in order. The single-relation IR can replace a wildcard by a typed constant or positive binding in `it.column = term` or its reverse. A conjunction may fix different columns. | An undecided membership can make the count undecided. `S.count(p)` is identically equal to `S.where(p).count()` ([aggregate spelling](language-rezono-1-aggregate-spelling.md), [refinements](language-rezono-1-refinements.md#31-countpred-equals-wherepredcount-everywhere)): `p = true` counts, `p = false` and `p = n/a` are excluded, and `p = unknown` or `p = invalid` leave the count undecided. Zero-argument `S.count()` remains strict in member states. | Require coverage for the source range and the predicate and measure reads, including for an empty result. | Keep the full contributor identities and restrictions. The current `over` names an integer key or value column admitted by the IR. A wider lowering must preserve keys and states. |
| `x is known`, `x is unknown`, `x is n/a`, `x is invalid` | Test the operand's state with no new binding. For a collection, test its own state. | A known Boolean for the tested state. Member states still feed folds. | A known-only selection can prove the positive known case. Any other claim needs its own state evidence. | Verify the authenticated Value, subject, reason and origin or checked omission. Reconstruct the full projection from its sources and refuse removed rows as well as injected rows. |

`a => b` uses `not a or b` with the antecedent's existing world restriction. `when c then x else y` selects on T and F and propagates N, U or I from the condition. Keep the existing grammar and diagnostics for typed literals, ranges, rounding and reserved forms. The shared aggregate semantics follow the [settled inapplicable-member case](conformance-value-agg-na-member.md). An integer fold may skip a member only when the lowering proves the results equivalent, including state and cause.

Use one hand-authored expectation per case in the existing [conformance corpus](../tests/conformance), with its `input`, `expect` and `unsupported` fields. The input identifies the expression and context, typed schema, incoming bindings, snapshots and coverage. Its expectation includes the exported bindings, type, state or diagnostic with span, and expected grounds. Run the same case through the TypeScript checker or evaluator, Python checker or lowering, and independent witness replay at the relevant boundaries. Include a valid witness and a targeted mutation in replay cases. Register the cases in the corpus and check that each intended runner selects them. Record unsupported boundaries explicitly. They provide no passing evidence for a required acceptance check.

## 2. Linking partial predicates

For each resolved relation, link its owner, ordered logical and physical columns, world, strata and signed dependencies, required reads, possible result states and the authored cause of each possible undecided state. Expose the keyed outcome when the program can recover it. Combine information from every owning clause and authorized extension in the pinned dependency closure. Iterate through positive recursive components to a fixed point and apply Appendix A when combining guards. Infer totality from the checked definition. An epoch containing only known values supplies no such proof.

- Scalar `not (x.value = 0)` takes its evidence from the comparison. It proves true for a readable known nonzero value and stays undecided for an unknown value.
- A relational anti-join requires an exact grounded key (`R042`), an admissible world (`R004`), an admissible stratum (`R043`), and proof of two-valuedness. If a closed `zero(x)` can be undecided because its scalar comparison is partial, report `R047` at `not zero(x)` in both TypeScript and Python. The callee comparison and partial slot are related locations. Check throughout aliases, wrappers, recursion and extensions. Reject an unchecked lowering before it emits SQL or a negative IR literal.
- A decided-value use of a partial call requires an actual state-bearing evaluation or a checked outcome at the full invocation key. A positive rule pattern may match recorded successes. Report `R047` when a negation or group would need the missing predicate states. For an otherwise sound filter or group outside the supported IR, report `R044` at the unsupported expression. A representability refusal must leave no partially lowered rule.
- A linked predicate summary names the relation and the owner it was linked for, and the signature of a derived relation names its owner. Both checkers require all three. A negation or group of a relation whose summary names another relation or owner, or leaves out its relation or its owner, or whose signature leaves out its owner, is refused with `R047` at the call. It carries no related locations, because such a summary explains nothing about the callee. An absent member is not a wildcard: accepting it would let any summary, linked for anything, prove a relation two-valued. Python lowering already compares both members exactly, so an absent one never matches there.
- An `absence` declaration may use existing IR rules to inspect an open register with full coverage. It describes the register at that scope and cut. A statement about the observed world additionally requires a matching completeness or explicit absence ground, and the role needs read authority in either case.

For an `ask`, T returns an Answer row, F omits it, N increments `not_applicable`, and U or I returns an Undecided row with its permitted reason and cause. For an ordinary rule, only T yields a tuple. A consumer needing a decision per key uses a checked named outcome with state, reason and evidence. This settles the distinction recorded in [the deferred rule outcome case](conformance-value-rule-body-unknown.md).

Publish a conclusion to a role only when a complete, founded and readable alternative supports it. Group and absence premises additionally require full read authority over their scope. A question about a visible subject can report the generic `not_read_in_full` for a partially read scalar. Hidden reasons, counts, proof identifiers and cursors must satisfy the [two-world rule](../docs/rezono/expressions.md#7a-visibility-and-the-two-world-rule).

## 3. Ordinary compilation and publication

1. Use the ordinary `python -m rezono_compiler compile PACK OUT` path through `pack.read` and `emit.compile_pack`. Check import pins and declared module/form pairs in the closure. Reread authored native source with the packaged reader and validate its closed `rezono.module/3` form and spans. Keep the accepted `/1` and `/2` boundaries and historical form-only cases.
2. Route schema declarations to the normal schema lowerer and each rule declaration to its owning rule interface once. Preserve schema features admitted in `/2` when a mixed module requires `/3`. Link `use` and aliases against the declaring pack's pinned closure before lowering any bodies. Resolve inherited keys, schema identities and imported aliases. Refuse duplicate ownership with `R040`, invisible or unauthorized definitions and extensions with `R046`, and collisions after remapping. A foreign clause may extend only an authorized extensible signature.
3. Assemble the checked native rules, legacy Datalog and pipe blocks, and generated rules through the ordinary rule builder. Pass checked filter terms, measures and groups through the same typed statement boundary. Preserve each authored origin and deterministic assembly. Validate `rezono.rules/1` safety, types, worlds and strata, with least fixed points for positive recursion and strictly descending negative and aggregate dependencies. Include each pack relation and declared empty extension point.
4. Keep physical column types in the IR and carry each ordered logical column type into the compiled bundle when it is richer. Construct derived publication slots from the checked column types, including integer bounds, nominal references or identifier representations, enums, refinements, units and currencies. A legacy column with only a physical type uses its physical scalar semantics. Refuse unsupported mappings. Validate encoded keys separately from the typed cell payload and check their agreement.
5. The ordinary publisher, publication reader and snapshot reconstruction must agree on the typed values. A published count supports numeric comparison. An integer slot with `"zero"` fails validation even when its tuple key is changed to match. Validate manifests, definitions and witnesses against the bytes of the publication that owns them. Rebuilding the same inputs reproduces the same artifacts.

### Logical types in the bundle

Add an optional `semantic` member to each derived relation's `RuleColumn` using the existing [`SemanticType` shape](../contracts/bundle.yaml). Project it from the linked signature's resolved schema and physical column types. Keep `type` as the checked rule IR's physical type. Use the physical scalar semantics for a historical column without `semantic`.

A reference uses `case: ref`, the target identifier's `base` and a `target` equal to the resolved kind identifier in the same pinned bundle. The kind's declaring schema and pack establish its owner. An enum likewise identifies the resolved bundle enum. A named scalar range keeps its resolved owner-qualified schema name. Resolve refinements, units and currencies through their pinned definitions. Reject an ambiguous target, an incompatible physical type or a declared logical mapping that the publication cannot validate.

For the supplied-bundle fixture, the ordered columns are `stage`, `count` and `label`. The `stage` column has physical `string` and `semantic: {case: ref, base: string, target: stage}` and resolves to the pinned `Stage` kind with a text identifier. The other two columns have physical `integer` and `string`, respectively. The publication schema uses a reference, an integer and text in that order.

### Ordered derived tuple keys

For each derived relation it exports as a kind, the publisher writes a `tuple_key` array on that kind in the role's schema document. The array lists the distinct column names in their checked bundle order. Its names must equal the kind's slot names, with every slot marked `derived: true`, card `1` and states `["known"]`. The kind keeps a `Text` identifier. The array is part of the pinned schema hash and supplies the order to a reader of the schema and row collection alone. JSON object member order has no authority.

The reader validates each cell under its declared slot type. It reconstructs the snapshot key parts in `tuple_key` order, using the canonical identifier of a reference's checked target, canonical integer text and the original text for a text slot. Use the checked type's exact snapshot representation for other supported scalars. The row's `$id` must equal the canonical JSON of those parts byte for byte. The snapshot reconstruction uses the same validated parts. An independently supplied schema with `tuple_key: ["stage", "count", "label"]` yields the key `["stage-a","9007199254740993","001"]` for a reference to `stage-a`, that exact integer and the text `001`.

Before accepting a newly produced form, compare its ordered key and slot types with the schema projected for that role from the independently pinned bundle. Reject a missing expected array even when the submitted schema and rows are rehashed consistently. A historical form without `tuple_key` retains its original pinned schema and validation rules. Evidence claiming the typed tuple guarantee requires the explicit array.

The array follows the existing visibility of the derived kind and its columns. For a role that sees the same definition in two worlds, the checked order remains `["stage", "count", "label"]` even when the role receives no result row in either world. Add a hidden contributor in the second world. The role still receives the same schema metadata and no additional row, proof or source.

See [native rule forms](language-native-rules.md#7-json-form-of-a-rule), [native pack linking](../docs/rezono/native-rule-pack-link.md), the [rule IR](../contracts/rules.yaml) and [publication schema and row validation](../publication/rezono_publication/l0.py).

## 4. Migration equivalence

For the same pinned inputs, contexts, scenarios and roles, compare typed facts and conclusions and all role-visible data and presentation. Check empty relations and independently inventory expected relations and subjects. Include keys, values, states, reasons, meaningful multiplicity and order, columns, messages, arguments and rendered text by language.

Validate every witness in its own publication, including on-demand alternatives. For each conclusion, compare the union of grounds from every founded witness. Include positive base and intermediate row keys, exact negative keys, group scopes and contributor keys, and all selection candidates, exclusions and tie-break inputs. Repeated reads of a row contribute a single ground. Distinct contributor keys remain distinct. In recursion, visit each reachable founded instance once. Check role visibility and source provenance independently in both publications.

Cross-source equality permits different rule and witness IDs, bindings' names, ordinals, source locations and hashes. Within one publication every such reference must still resolve, and the visible association of a message to its conclusion must remain correct. The existing [publication comparator](../scripts/convert_pack.py) is the common integration entry point. Renaming and renumbering with identical grounds passes. Substituting a relation with the same keys and leaving every result and message unchanged still fails the grounds comparison.

| Existing requirement | Apply this scope when updating it |
| --- | --- |
| [Native rules](language-native-rules.md) §§1, 5, 10–12 on shared clause IDs, witness identity, conversion steps and the listed-rule check | Keep ownership, rule computation and ground meaning. Ordinals, names and hashes remain deterministic within an input and cease to be a cross-source acceptance criterion. |
| [Semantic publication](language-semantic-publication.md), the Proof row | Use local validity and the ground union above in place of pairwise equality of rule shape, bindings, stratum, multiplicity and witness order. Preserve the facts, presentation, independent inventory and source checks. |
| [Relational rule blocks](language-rules.md#clause-evidence-and-source-locations) and [library migration](language-library-acceptance.md) | Keep exact binders and identities for replay of local proofs. Use semantic projections and separate provenance checks for migration instead of equal stable IDs or entire bundles. |
| [Listed rule](../compiler/tests/rezono/test_native_rule_ir_listed.py), [pack link](../compiler/tests/rezono/test_native_rule_pack_link.py), [converter](../compiler/tests/rezono/test_native_rule_dl_converter.py) and [pack link description](../docs/rezono/native-rule-pack-link.md) | Keep typed rows, ownership, pin and extension controls, deterministic same-source outputs and valid local origins. Replace equality of IDs, fixed cross-source ordinals and raw program dictionaries. |
| [Native publication parity](../compiler/tests/rezono/test_native_rule_publication_parity.py) | Keep batch, incremental, scenario and role assertions. Accumulate all checked alternatives before comparing grounds. Replace fixed comparison of variable names, IDs and raw evidence or rule bundles. |
| Local wire, reader, origin and checker mutation cases | Keep exact same-source syntax, spans, substitution and replay expectations. Continue to reject forged bindings, changed contributor sets and unjustified absence. |

## 5. Acceptance with `order-check`

Pin the real [`std-order` pack](../packs/std-order/pack.yaml) in a neutral consumer. Declare a concrete `Stage` extending `Ordered` so it inherits the root kind's closed world, as in the [standard order example](../examples/platform/schema/standard-order.yaml). The consumer supplies the data, role grants, reason definitions and messages. Declare this source and its form in `pack.yaml`.

```rezono
rezono 0
pack order-check
use std-order as ord

rule edge(pred: ord.Ordered, succ: ord.Ordered) when ord.Ordered.precedes(pred, succ)
rule zero(x: Stage) when x in Stage and x.rank = 0
rule nonzero(x: Stage) when x in Stage and not (x.rank = 0)
rule successors(x: Stage, n: Int) when x in Stage
  and n = (edge(_, _) where it.pred = x).count()
```

Use stages `a`, `b` and `c`. The archived rank Value of `a` carries `unknown not_measured` and its recorded origin. The ranks of `b` and `c` are 0 and 2. There are exactly two edges, `a → b` and `a → c`. The complete role reads all stages and the full edge relation. The limited role reads stages `a` and `c`, their rank evidence and `a → c`, without full edge coverage.

| Control | Expected observation |
| --- | --- |
| Scalar negation | The complete role reads `zero = {(b)}` and `nonzero = {(c)}`. `ask x: Stage where not (x.rank = 0)` returns `c` with `a` undecided at its rank Value for `not_measured`. There is one answer, one undecided and zero not applicable. |
| Filtered count | The complete role reads `successors = {(a,2),(b,0),(c,0)}`, in columns `x,n` with a Stage reference and integer. The group for `a` fixes `pred=a` and reaches both edge keys and their forward `precedes` rows. Each zero group needs full scope evidence and has no contributors. An unfiltered count would incorrectly return 2 for `b` and `c`. |
| Restricted view | Retain the readable `a → c` and `nonzero(c)`. Withhold all `successors` rows and proofs, including the zero for `c`. In a second epoch, remove only the hidden edge `a → b`. The complete role's count for `a` becomes 1. Compare the projected data and answer bytes for the limited role across both worlds, and check each epoch's pins separately. |
| Rejected source | In a separate invocation replace `nonzero`'s guard with `x in Stage and not zero(x)`. Both checkers give `R047` at the whole negation and identify the rank comparison and partial slot. |
| Typed read and mutation | Read `n` through the ordinary publication reader and ask for `n > 1`. Only `a` qualifies for the complete role in the first epoch. Replace the numeric payload with `"zero"` and require a validation failure, including a case with a correspondingly altered tuple key. |

Execute the accepted source through the ordinary compiler, batch and incremental paths, checker, publisher, publication reader and question evaluator. Compare to an independently authored legacy pack and the explicit observations above. Supply the same archived Value and evidence in both representations. Isolated form and group tests remain useful prerequisites. This acceptance exercises the entire path.

## 6. Work and test dependencies

Each independent test uses its own claim and a frozen expectation. Reuse existing green coverage for native form, reading, signatures, body safety, group assembly, state evidence, converter inventory and proof mutations. Existing implementations of only part of a case should run as positive controls. Apply the migration scope in section 4 before assigning work on old identity assertions.

| Independent test | Evidence to freeze |
| --- | --- |
| `expression-path-bindings` | Typed declarations versus actual membership or path bindings, identifier projection and forward evidence for an inverse. |
| `expression-branch-bindings` | Positive, computed and branch-local names and `R042` for an unsafe negative key. |
| `expression-truth-causes` | All five values, decisive outcomes including F and I and T or U, tied reasons and a cause-free constant. |
| `expression-quantified-membership` | Empty complete, open empty and undecided membership cases, plus a decisive readable match. |
| `expression-filter-states` | F and N exclude a member, U and I retain its uncertain membership, and the count retains its cause. |
| `expression-aggregate-members` | Empty identities, equal measures on distinct keys and propagation of an inapplicable member. |
| `expression-ts-filtered-count` | Supplied signatures, both orientations of fixed-column equality, and type and binding refusals with spans. |
| `expression-python-filtered-count` | The same tree, exact fixed terms and contributor keys, and `R044` for a well-typed but unrepresentable filter. |
| `expression-link-partiality` | Possible states through a wrapper, positive recursion and extension, including a total control. |
| `expression-ts-negated-call` | Linked summaries giving `R047` on partial, `R004` on open and legal covered negation on total predicates. |
| `expression-python-negated-call` | The same summaries and exact `R047`, including rejection of lowering with absent or forged totality evidence. |
| `expression-ask-partial-call` | A keyed outcome yields the expected undecided row and a success-only interface gives `R047` where a decided result is requested. |
| `expression-state-projection-coverage` | Archived Values give an independently derived full projection. Omit a genuine row or inject an unreadable reason and require refusal. |
| `expression-group-proof` | Existing rule IR and a snapshot give a valid group. Change its filter key, omit a contributor or forge an empty group and require refusal. |
| `native-module-dispatch` | Authored mixed `/3` declarations reach their owners once, and a real `/2` pipe module retains its behavior. |
| `native-module-use` | Verified closure and alias resolution, with wrong pin, sibling leakage and unauthorized extension controls. |
| `publication-derived-column-types` | A supplied bundle produces ordered reference, integer and text publication columns. |
| `publication-derived-column-read` | An independently typed dataset round-trips keys and rejects `"zero"` in an integer slot. |
| `migration-ground-union` | Renamed and renumbered checked proofs agree, repeated reads collapse and intermediate rows remain grounds. |
| `migration-changed-ground` | Independently valid publications with the same results and a substituted premise differ. |
| `role-missing-group-ground` | A two-world fixture withholds an incomplete group, keeps a readable positive alternative and reveals no hidden reason. |

The language tests own the authored and compiler paths. Publication and checker tests own typed readback and independent witness claims. Use the same acceptance test for an equivalent regression, including the three partial-call checks, the projection omission check, and the typed publication checks.

| Integration | Prerequisites |
| --- | --- |
| Listed rule through the ordinary compiler | Native declaration dispatch and normal single-clause lowering. |
| Mixed native pack link | The ordinary native IR entry, verified `use` and mixed assembly. |
| `order-check-publication` | Linked pack compilation, checked filtered groups, scalar state evidence, partial-call refusal, typed readback, role coverage and semantic grounds comparison. The legacy fixture is authored independently of bulk conversion. |

Completion requires the ordinary `order-check` result, the `R047` refusal and the typed mutation failure. A pack migration waits for the expression features that pack uses.
