# Native relational rules in Rezono

## 1. Principles and choices

Write a relation as `rule name(columns) when expression`. A rule derives a set of tuples. A `derived` declaration computes a value for a subject. Both use the expression grammar that `ask` already uses. Datalog remains the semantics and Soufflé remains an independent oracle.

```rezono
rule within(part: Constituent, whole: Constituent) when part.part_of = whole
rule within(x, w) when within(x, v) and v.part_of = w
```

The first line declares two named, typed columns and supplies the base case. The second supplies another clause of the same relation. For a chain `a → b → c`, the recursive witness for `within(a, c)` binds `x=a`, `v=b`, `w=c` and cites `within(a, b)` and the `part_of` row for `b → c`.

Three choices govern the design.

- **A type annotation makes no factual claim.** `x: Constituent` lets the checker resolve `x.part_of`. Writing `x in Constituent` additionally reads the membership row. That distinction preserves proofs.
- **A relation call matches rows.** Repeated variables join columns, constants constrain columns, and variables absent from the head remain in the witness. A scalar path reads a value with its state. Both operations have a place, especially when a rule detects conflicting records.
- **Conversion preserves the proof of each clause.** Column names, variable names, clause order, individual premises and aggregate domains are observable. An equivalent answer obtained from different premises fails conversion acceptance.

Rejected alternatives, one sentence each:

- Keeping the `|` block would leave schema names, type checking and most author diagnostics on the Datalog side of the language boundary.
- Inferring every signature from clause bodies would lose public column names and leave recursive interfaces and empty extension relations without dependable types.
- Expressing every relation as a `derived` slot would require an artificial subject for n-ary relations and obscure multiple independent proofs.
- A built-in `best` or `first` would conceal which inventory, exclusions and tie policy justify a choice.
- A new comprehension or Boolean expression language would duplicate the precedence, path, filter and state rules already used by questions.

This decision supersedes the source spelling in [Relational rules](language-rules.md). It retains that decision’s evidence requirements and the comparison policy in [Comparing two source forms of a pack](language-semantic-publication.md).

## 2. Grammar additions

The following is the Ohm delta. Add `RuleLine` to `Line` and admit it at module scope in `module.ts`. Insert `QualifiedKind`, `quotedName` and `wild` in `Atom` after `Call` and before the ordinary name alternatives. In `Dotted_name`, accept `rName` after the dot. Existing `Expr`, `Filter`, `Agg`, `Call` argument lists, comparison precedence and physical-line continuation rules apply.

```ohm
RuleLine = kw<"rule"> RuleRef "(" RuleHead ")" RuleOption* Locals? Guard?
RuleRef = (rName ".")? rName
RuleHead = NonemptyListOf<Column, ",">  -- typed
         | NonemptyListOf<Expr, ",">    -- positional
Column = rName ":" RuleType
RuleType = (rName ".")? Type
Locals = kw<"with"> NonemptyListOf<Column, ",">
Guard = when Expr

RuleOption = kw<"extend">                                      -- extend
           | kw<"invariant">                                   -- invariant
           | kw<"absence">                                     -- absence
           | kw<"outcome"> RuleType                            -- outcome
           | kw<"closes"> RuleRef                              -- closes
           | kw<"explain"> ExplainMode                         -- explain
ExplainMode = kw<"materialize"> | kw<"on_demand"> | kw<"fold">

Call := CallName "(" ListOf<Expr, ","> ")"
CallName = (rName ".")? typeName "." CallMember  -- schema
         | rName "." CallMember                 -- imported
         | rName                                -- local
CallMember = ~(aggName "(") rName
QualifiedKind = rName "." typeName

rName = name | quotedName
quotedName = "\x60" az (az | d | "_")* "\x60"
wild = "_" ~wordChar

PackLine := kw<"pack"> packPart
UseLine := kw<"use"> NonemptyListOf<packPart, "."> (as rName)?
packPart = idTok | name
```

`CallMember` gives `.count()` and the other existing postfix aggregates their usual parse. A qualified relation coincidentally named `count` can be called as ``p.`count`(x)``. A quoted name denotes the exact identifier between backticks. This matters for existing names such as `` `known` ``, `` `replaces` `` and the column `` `at` ``. It introduces no renamed IR variable. `Type:` followed by a backticked row ID keeps its existing meaning. Pack components in headers must match the manifest’s pack-name syntax. In particular, `std-order` can be written literally.

A typed head declares the signature. With `when`, its column names are also the head variables of that clause. A positional head requires `when` and an existing signature. It accepts variables, typed constants, repeated terms and identifier projections. A wildcard in a head is an error. Options belong on the owning typed head. `with` gives types to clause-local variables when the body needs them to resolve a path. It emits no rows. The new option words are contextual.

A deeper line after `when`, or a deeper line beginning with `and` or `or`, continues the expression. A rule needs no body-line prefix. In particular, `(r where p).count()` uses the existing parentheses to end the greedy `where` expression before applying the aggregate.

## 3. Relations, names and publication

**Schema inputs.** Resolve a kind by its declared class name and a slot by its declaring or inherited schema identity. `x in Household` reads the membership table. `Application.household(a, h)` reads a row of the forward slot. An inverse reads that same row with the endpoints exchanged. Resolve the actual table through the compiled schema, including import mappings, inherited identifiers and subkinds. Concatenating lowercased source words is insufficient.

**Derived relations.** Declare a signature once in the owning pack, in the module that owns its rules. Its ordered columns are the complete tuple key. There are no derived payload columns in `rezono.rules/1`. A bare typed head is useful when public column names differ from witness variables or when a pack defines an extension point.

```rezono
rule listed(item: Alpha)
rule listed(x) when x in Alpha

rule stated_number(referent: Referent, slot: Text, value: Int) extend
```

`listed` has a public column `item` and a witness variable `?x`. `stated_number` is an empty set until a visible pack supplies a clause. An ordinary declaration with no defining clause is an error. A second owning signature, including one copied into a consumer, is an error.

**Types.** Check kind references nominally, with the schema’s subtype and declared view mappings. Check enums, scalar aliases, units, dimensions and cardinality before lowering. A kind-valued column carries the kind’s actual identifier representation. `Text` lowers to `string` and `Int` to signed `integer`. A supported enum or refined scalar lowers through its checked representation. A quoted text constant and an integer constant retain distinct source types. Reject a type or operation for which the rule backend lacks a faithful representation.

A declared identifier path exposes its scalar key. If `id` is the identifier, `s.id` uses the key already bound for `s` and adds no slot premise. A kind with identifier `code` uses `s.code`. This lets an author compare explicitly identified records across kinds without declaring the kinds interchangeable. An embedded record without identity cannot be a head column of nominal row references.

**Imports.** `use std-order as ordering` resolves the exact pack in the importing pack’s verified dependency closure. `ordering.before(a, b)` reads the owner’s relation. An unaliased `use` makes its unique visible names available unqualified. Ambiguity requires an alias. A pack cannot gain visibility through a sibling consumer. Resolve the owner before applying existing import remappings. A qualified clause head may add a rule only to an imported signature marked `extend`. It inherits that signature and the owner’s IR module. Detect collisions in the final engine namespace even when the source aliases differ. The current module lowerer refuses `use` lines, so linked name resolution is an implementation task.

**Publication.** `pack.yaml` names the `.rezono` modules and their forms and pins the imported packs. Compile every derived relation in that closure, including helpers and empty extension points. The existing `.output` only validates that its names are derived. It does not select which relations enter the rule program or bundle. A role receives conclusions for which it can read a complete proof. A negative premise or aggregate requires full read access to the relation it inspects. Channels, views and hero selections determine what the pack presents. They do not grant access or remove helper premises. A generated Soufflé oracle may select `.output` names for its test run.

**Annotations.** `invariant` requires the relation to be empty at publication. `absence` describes the contents of a register. `outcome K` retains the checked state-and-reason contract for each member of `K`. `closes r` retains the prefix-key exclusion invariant generated by the compiler. `explain materialize` and `explain on_demand` set witness storage. `explain fold` is a display property and can accompany a storage mode. Defaults follow the existing projection test. Delimited release remains reserved.

## 4. Constructs and evidence

| Construct | Rezono example | Meaning |
|---|---|---|
| Ordinary rule | `rule repeat_application(h, n) when application_count(h, n) and n >= 2` | Derive the tuple for each satisfying binding. |
| Join through a path | `rule household_size(a, n) when a.household.persons = n` | Read the application-to-household row and that household’s `persons` row. Each hop is a premise. |
| Named intermediate | `rule household_size(a, n) when a.household = h and h.persons = n` | Bind the intermediate as `?h`. Use this spelling to preserve an existing witness variable. |
| Recursion | `rule before(a, c) when before(a, b) and c in b.precedes` | Add a positive step to the least fixed point. `precedes` is multivalued. |
| Ground negation | `rule ready(r, s, w) when eligible(r, s, w) and not not_ready(r, s)` | The witness identifies the exact absent key in the lower stratum. |
| Existence | `rule has_quote(a) when line(a, _, _, _)` | A matching line proves existence. Each matching row can supply a witness. |
| Non-existence | `rule quote_missing(a) when a in Application and not has_quote(a)` | The projection gives an exact negative key, even though a quote line has four columns. |
| Count | `n = Application.household(_, h).count()` | Count slot rows pointing to `h`, including zero in a complete group. |
| Filter | `n = (line(a, _, _, _) where it.cents = 0).count()` | Count full line keys whose `cents` column is zero. |
| Sum | `t = ledger_line(a, _, _).sum(it.cents)` | Sum the named integer column once per matching payment row. Equal amounts in different payments both contribute. |
| Extremum | `d = stable_release(_, p, _).max(it.d)` | Return the greatest matching day. An empty group supplies no numeric conclusion. `min` is symmetric. |
| Compare or compute | `s >= q`, `examined = compared + unavailable`, `examined = inventory` | The first and last are tests. The middle binds a fresh integer result. |
| Choice | `compared = comparison(d, o, _, _, _).count()` in `selected` below | Retain evidence covering competitors, exclusions and the inventory. |
| Recorded absence | `rule income_not_received(a, h) when a.household = h and not has_income_statement(h)` | With `absence` on the signature, conclude that the register contains no statement for `h`. |
| Checked absence | `complete_sweep(run, scope, sweep, coverage)` in `current` below | An identified completeness row, matching interval and explicit absence event establish what was checked. |
| State | `assessment(a, "unknown", "income_statement_not_received")` | Read a positive outcome row with a reason. |
| State of a value | `p.income is unknown` | Read the state evidence for that value. An empty scan of known income values cannot establish this test. |

### Unknown, absence and zero

A set of proven tuples and a scalar value answer different questions. Only a true body derives an ordinary tuple. False and `n/a` supply no tuple. Unknown and invalid supply no positive assertion about the value. A relation whose predicate can be undecided cannot be used as a total Boolean by negating its success rows. The source checker must carry that partiality through calls, including where it is stricter than the two physical IR column types. Use a named outcome when consumers need to distinguish undecided from false. The original language reference called for undecided outcome rows. Unconditionally adding them to every migrated relation would change its arity and proofs.

| Input state | Rule behavior |
|---|---|
| `known(v)` | A strict comparison or arithmetic operation can use `v` after type checking. |
| `unknown(reason)` | A strict operation remains unknown. `not` preserves that state. A positive state test can cite its cause. |
| `n/a` | A strict scalar operation remains inapplicable. `is n/a` tests it explicitly. |
| `invalid(reason)` | A strict operation remains invalid. Integrity checks can block the epoch. An invalid amount cannot enter an ordinary numeric conclusion. |

Use the existing truth tables for logical expressions. For example, `false and unknown` is false and `true or unknown` is true. `not (p.income = 0)` needs a known income before it can establish inequality. Lowering it to the absence of an income row containing zero would be unsound.

An omitted required scalar is unknown. A missing optional scalar of a fully read, closed subject and slot can be `n/a` under the schema’s value rules. An unread or open source cannot establish that absence. An explicit unknown with a reason retains its reason. An empty string, a string `"unknown"` and a Value in state `unknown` are three different inputs.

A closed relation supports negation and whole-group aggregation. An open relation can supply positive evidence. The existing IR permits negation or aggregation over an open register inside an `absence` relation, subject to its existing checks. That result concerns **what was recorded**. For a conclusion about the observed world, the pack must provide a positive completeness or explicit absence row for the same scope. The `current` clause below joins run, collector scope, sweep, coverage reference and half-open time window. Removing that join changes the claim. For a genuinely open input, first derive recorded absence under `absence`, then join it to the scoped certificate. A certificate never changes a relation’s global `world`.

Counting complete relation rows gives zero for an empty group. Summing a complete relation of known integer amounts also gives zero for an empty group. Missing amounts or undecided membership do not establish an empty group. The subsidy scheme illustrates the distinction with `has_quote(a)` before summing: without a quote there is no total. For a stateful collection expression, require evidence for membership and values before emitting a numeric result. The checker’s existing value-column fold skips `not_applicable`, while the expression table of the language reference makes aggregates strict in member states. Direct lowering is valid where contributors are known or both semantics provably agree. Section 12 gives the recommendation for the remaining case.

### Choice over all candidates

`selected` ranges over the pack’s offer inventory. `comparison` records a self-comparison and every eligible contender beaten on total, then on a strictly lower tie rank. `excluded` accounts for inventory offers without a proven eligible row. For inventory `{a, b, c}`, suppose `a` and `b` both cost 80, their ranks are 1 and 2, and `c` is excluded. The witness for selecting `a` has three groups:

| Group | Members identified by the snapshot and group evidence |
|---|---|
| Inventory | Offer keys `a`, `b`, `c` |
| Compared for `a` | The self-comparison for `a` and the comparison against `b` |
| Excluded | The exclusion of `c` for this demand |

The checker verifies `2 + 1 = 3` **and** recomputes each group from its full relation. The definitions of `comparison` and `excluded` establish which candidates those rows cover. An unresolved tie for best leaves no winner. The claim is the best *proven eligible* offer in this inventory. A pack that promises the best actual offer also needs evidence that the inventory and eligibility assessments are complete.

## 5. Lowering to `rezono.rules/1`

Lower a checked module form to the same typed statement inputs that feed `rules_dl.to_rule`. Factor the common program assembly out of the Datalog reader. Python consumes the form directly. Preserve `rules_sql.py`, the batch and incremental backends, and independent witness evaluation.

| Source construct | Lowering |
|---|---|
| Typed head | One `Relation` with `role: derived`, owner module, ordered `key`, existing flags and explain mode. The guard, if present, also supplies a clause. |
| Positional head | `head.relation` is the resolved owner name. Terms are `?variable` or canonical typed constants. A repeated head variable stays repeated. |
| `x in K` | A positive membership literal `k(?x)`. `v in K.id` reads the same row, binding the scalar identifier. An explicit identifier uses its schema name. |
| `K.slot(x, t)` | One positive slot-row literal with the resolved table and its two terms. This form can inspect two conflicting rows of a nominally single-valued slot. |
| Scalar path, membership, inverse | Emit one forward slot literal per hop. Reverse terms for an inverse. A positive equality with a single-valued path can put the other term directly in its value position. A multivalued path requires `in`, a filter, or an aggregate. Reading a reference’s identifier at the end of a hop adds no literal. |
| Intermediate path bindings | A named intermediate keeps its source variable. For an unnamed hop, allocate fresh `path_1`, `path_2`, … left to right, skipping user and generated names. Do not merge separately written reads. |
| Relation call, `_` | Emit an atom with positional terms. Each positive `_` gets the next fresh `anon_n` by the existing allocator. An aggregate `_` stays `_` and adds no witness variable. A negative `_` is unsafe. |
| `and`, `or` | Preserve the written order of conjunctions. An outer `or` supplies one clause per alternative, from left to right. Each branch must be safe. Multiple authored clauses already express the union and preserve their identities. |
| `not r(…)` | Emit a negative literal only for an exact, positively grounded key and a permitted world. Scalar negation instead operates on the known truth value. |
| `.any(p)`, `.none(p)`, `.all(p)` | Existence can use a positive matching row satisfying `p`. For `.none(true)` over a closed row range, use a zero count, or negate an explicitly named existence relation by its full key. For `.all(p)`, absence of a counterexample suffices only when `p` is total on the complete range. Otherwise preserve undecided state or refuse the lowering. |
| Row range and `where` | `r(d, _, _)` fixes its first column and ranges over complete matching tuples. A named relation under `where` has its declared columns in `it`. Equality filters fixing columns become fixed terms. A join or more complex filter that cannot fit one IR aggregate atom needs a named relation retaining the contributor key. |
| `.count()`, `.sum(it.c)`, `.min(it.c)`, `.max(it.c)` | Emit `aggregates[]` with `relation`, `terms`, `function`, fresh `as` and, except for count, `over`. A group variable must occur in a positive literal. `over` names the integer value column or a ranged integer key column. The whole group can have no fixed keys. |
| `= != < <= > >=` | Emit `conditions[]` with `eq ne lt le gt ge` on already bound terms. Ordering in this backend requires whole numbers. Equality between two scalar variables never introduces a free variable. |
| Arithmetic | A fresh left-hand variable with an arithmetic right-hand side gives an ordered `assignments[]` entry. Check operands, exact units and signed 64-bit range. Preserve intermediates and overflow checks. Exact Rezono `/` cannot silently truncate. Use `quotient(n, 3)` for the legacy integer `div` operation, truncated toward zero with a nonzero constant divisor. |
| Positive recursion | Use the existing least fixed point. Positive dependencies may share a stratum. Negative and aggregate edges require a strictly lower input stratum. Retain the existing bounded-counter checks for recursive arithmetic, including constant starts, positive increment, constant upper bound and unrolling limit. |
| Calculated value | A supported whole-number calculation read, for example `a.award = w`, emits the existing positive selection `calc__award(?a, ?w, "known", "")`. Resolve the named calculation, subject and output through pack metadata. |
| State test | Use positive evidence from an existing state-bearing source. A known-only selection can prove `is known` when it supplies a row. For general scalar states, expose a compiler-owned state projection keyed by subject, state and reason, authenticated against the underlying Value and its origin. The checker must independently validate that projection, including any evidence for an omitted value. Until such evidence is available, reject the test at its span. |
| Seal | A schema-generated input such as `LedgerPayment.accepted(p)` resolves through the named seal to `ledger_payment__accepted(?p)`. Retain the seal document and its independent recomputation. Reserve generated names against collisions. |
| Options | Carry `extend`, `invariant`, `absence`, `outcome` and `closes` through the existing program builder. `closes` still generates the conflict invariant. Keep fold metadata outside the IR. |

A bare variable in a positive row-pattern position can bind there. An ordinary value expression must resolve its names. Type inference uses the entire clause, but safety still distinguishes a positive binding, an aggregate result and a fresh arithmetic result. Head annotations and `with` declarations supply types only. Do not use query-normalization passes that rename variables, sort conditions or discard duplicate-looking premises on the proof path.

**Witness identity.** Use the same import closure, module stem, per-head clause order and extension ownership as `rules_dl.read`. A single clause has ID `r`. Several have IDs `r_1`, `r_2`, … in the existing assembly order. Keep the four ordered IR lists and the separate interleaving of body-element kinds used by the bundle. The latter affects the published stable ID `relation~hash`. `with_strata` and `ir.load` still compute and validate strata, worlds, safety and the sorted variable columns of `id__witness`. The source origin and span point to the authored Rezono head.

**Independent checking.** The checker substitutes every binding, checks the conclusion and every positive or negative premise key and stratum, then reevaluates conditions and assignments. An aggregate witness identifies its relation, group key and, where necessary, aggregate position. It carries `count`, `contributors_sha256` and `result`. For count, the digest covers sorted encoded contributor keys. For a value aggregate, it covers keys paired with the values read. The snapshot and fixed positions recover the individual rows, including two different rows with equal amounts. A completeness row is an ordinary positive premise with a key and proof of its own. [Rule IR](../contracts/rules.yaml) · [Witness and group verification](../checker/rezono_checker/check.py)

## 6. Diagnostics

Reuse `R000` for syntax, `R001` for unknown schema names, `R003` for incompatible types, `R004` for open-world operations, `R005` for scalar/set confusion, `R011` for ambiguous element scope, `R012` for bad typed literals, `R015` for reserved constructs, `R016` for chained comparisons and `R017` for non-Boolean guards.

New diagnostics have structured arguments and a source span. Their English and Dutch templates belong in `rezono/messages/en.json` and `rezono/messages/nl.json`. A compiler rejection of an independently supplied form maps to the same diagnostic and its JSON-pointer span.

| Code | When | Example English sentence |
|---|---|---|
| R040 | Missing, competing or incompatible owning signature | “Declare the columns of `within` before supplying positional clauses.” |
| R041 | Wrong arity in a head or relation pattern | “`within` takes 2 columns. This call supplies 3.” |
| R042 | Unsafe head, negative key, wildcard or group variable | “Bind `h` in a positive premise before counting lines for `h`.” |
| R043 | Cycle through negation or aggregation | “`available` depends on its own absence through `blocked`.” |
| R044 | Aggregate domain or measure cannot be represented faithfully | “`sum` needs one ranged integer column. Declare a relation for these joined lines.” |
| R045 | Illegal assignment, divisor, bound or statically out-of-range integer | “`quotient` needs a nonzero constant divisor here.” |
| R046 | Unpinned, ambiguous or inaccessible import, or unauthorized extension | “`ordering.before` belongs to `std-order`. Its signature does not permit additional clauses.” |
| R047 | Expression needs state, completeness or totality evidence the available input cannot supply | “The selection for `award` exposes known amounts only. It cannot prove `award is unknown`.” |
| R048 | Invalid relation option, option combination or clause-free ordinary signature | “`outcome Application` needs columns for the application, state and reason.” |
| R049 | No faithful rule-IR representation for a type, literal or expression | “This division can produce a fraction. An integer rule column cannot hold it.” |

Suggest visible schema names at the offending segment. For a dependency cycle or duplicate owner, include the other relevant span. A correctness diagnostic blocks compilation. Explain-storage cost remains a warning.

## 7. JSON form of a rule

Use `rezono.module/3` for native rule nodes. `/1` already has a closed declaration shape and `/2` identifies the recorded `rules`/`lines` block. Keep their existing bytes and readers. The fixture `contracts/fixtures/rezono-module/ModuleForm/invalid/other-format.yaml` uses `/3` as an unknown format; give it an unused number. A reader that cannot process `/3` rejects the complete form. The envelope remains `format`, `module`, `spans`, with RFC 8785 serialization and decimal-text positions.

For this complete source, with a final LF:

```rezono
rezono 0
pack minimal
rule listed(item: Alpha)
rule listed(x) when x in Alpha
```

the form is shown below, expanded for reading.

```json
{
  "format": "rezono.module/3",
  "module": {
    "rezono": "0",
    "pack": "minimal",
    "use": [],
    "decls": [
      {"rule": "listed", "columns": [{"name": "item", "type": "Alpha"}]},
      {
        "rule": "listed",
        "args": [{"path": ["x"]}],
        "when": {"in": [{"path": ["x"]}, {"kind": "Alpha"}]}
      }
    ]
  },
  "spans": [
    {"at": "/decls/0", "line": "3", "start": "27", "end": "33"},
    {"at": "/decls/0/columns/0", "line": "3", "start": "34", "end": "38"},
    {"at": "/decls/1", "line": "4", "start": "52", "end": "58"},
    {"at": "/decls/1/args/0", "line": "4", "start": "59", "end": "60"},
    {"at": "/decls/1/when", "line": "4", "start": "67", "end": "77"},
    {"at": "/decls/1/when/in/0", "line": "4", "start": "67", "end": "68"},
    {"at": "/decls/1/when/in/1", "line": "4", "start": "72", "end": "77"}
  ]
}
```

A native declaration has exactly one of `columns` and `args`. `when` holds the existing `Expr` tree. `locals`, when present, is an ordered list of column-shaped objects. `options` is an ordered list such as `[{"absence":true}]`, `[{"outcome":"Application"}]` or `[{"explain":"on_demand"},{"explain":"fold"}]`. Reject duplicate or incompatible options. Each local and option has a span. Declaration spans identify the relation name. Clause provenance uses that head occurrence, including for repeated clauses.

Add `{"wildcard":true}` as a pattern expression. A qualified call keeps the existing call shape, for example `{"call":["Application.household",[{"wildcard":true},{"path":["h"]}]]}`. Names store their decoded spelling. The printer escapes them where the grammar requires it. The existing `agg`, `filter`, `cmp`, `arith`, `is`, `in`, `and` and `not` nodes remain the source tree. Store neither inferred types nor generated atoms in this form. Unknown members, `null`, invalid spans and forms that fail the print/read tree check are errors. [Module contract](../contracts/rezono-module.yaml)

## 8. Coverage of the real rules

The census at `0b9e8ff` used `git ls-files '*.dl'` and `rules_dl.parse_file`. There are **70 tracked files**. The requested **67 production and example files contain 590 clauses and 1,755 body elements**. They comprise 31 platform files, eight subsidy files, 22 standard-pack files and six run-pack files. The other three are two compiler fixtures and one connector fixture.

Counts below are occurrences unless marked as clauses, files or names. Structural counts overlap.

| Datalog construct | Count in 67 files | Native spelling or treatment |
|---|---:|---|
| `.decl` | 337, with 806 `symbol` and 95 `number` columns | Owning typed heads. Recover kind, enum, alias or unit from the schema where justified. |
| `.output` | 70 directives naming 128 outputs | Validate old names during conversion. Pack compilation and role policy determine publication. |
| `.input` | 0 | Resolve each schema input from its use. |
| `head :- body.` | 590 | `rule head(…) when …` |
| Several clauses for one head | 80 of 336 distinct heads grouped by authoring pack | Repeat the positional head in source order. |
| Positive literals | 1,419 | 470 derived calls, 810 slot rows, 136 schema memberships, two calculation selections, one seal input. |
| Joins and projections | 366 clauses have multiple positive atoms, 338 share a named variable across them, 114 read a positive predicate more than once, 392 project a positive variable or wildcard | Named path joins and independent row patterns. Preserve Cartesian products where written. |
| `!atom` | 112 | `not` on a grounded row. 107 target derived relations and five target slot rows. |
| Direct positive recursion | 7 clauses | Recursive calls in `unavailable_service`, `replaces`, `ground_chain`, `equivalent`, `before`, `within`, `reached_page`. |
| Aggregate calls | 24 in 18 clauses, three clauses with multiple aggregates | 16 `count`, four `sum`, four `max`, zero `min`. Preserve each occurrence and position. |
| Aggregate domains | 22 correlated, two global | 18 range over derived relations, four over slot rows and two over membership rows. |
| Variables and `_` | 1,336 variable occurrences in heads, 229 positive wildcards, 39 aggregate wildcards, eight aggregate-local named variables | Ordinary variables, positive `_`, ranged `_`, and `it.column` for the aggregate measure. |
| Equality by repeated position | 13 clauses repeat a head variable, six body atom occurrences repeat a variable | Repeat the name, including self-comparisons and equality of two counts in a single tuple. |
| Constants | 240 text occurrences in heads across 157 clauses, 145 other text occurrences, 24 integer occurrences, one negative integer | Text, enum or typed ID literals, whole numbers and unary minus. Preserve `""`, numeric-looking text and the real `-1` sentinel. |
| Comparisons | `=` 14, `!=` 102, `<` 41, `<=` 18, `>` 8, `>=` 10 | Existing Rezono operators. These counts exclude arithmetic and aggregate result bindings. |
| Arithmetic assignments | `+` 5, `*` 2, `-` 0, `/` 0 | Bind a fresh variable with `=`. Preserve intermediate results. |
| `@invariant`, `@absence`, `@outcome`, `@extend` | 17, 9, 3, 3 | Typed-head options. All three extension signatures have no local defining clause in their owner file. |
| `@explain` | Two `on_demand`, one `fold`, zero explicit `materialize` | `explain` option. Fold remains display-only. |
| Comments | 384 `//` comment lines including annotations, zero block comments | Ordinary comments become `--`. Recognized semantic annotations become options. Two `https://` literals remain strings. |

There are no production occurrences of `@closes`, `@release`, disjunction in a clause, negative wildcards or recursive arithmetic. `@closes` already has an IR expansion. `@release` is reserved. The three fixtures add 16 clauses and 33 body elements, including one truncated integer division. That fixture is a reason to specify `quotient` even though the 67 files have no division.

Every observed Datalog operator has a spelling. The two calculation selections, seal input, empty extension signatures, reserved-word identifiers and legacy joins across distinct identifier types need explicit handling. Inferring them from a name or an engine `string` alone is insufficient.

## 9. Six real clauses side by side

The right column uses positional heads against the owner signatures. Relevant signatures include `selected(demand: Demand, offer: Offer)`, `conflicting_input(candidate: Candidate)`, `application_count(household: Household, n: Int)` and ``begun_at(interval: Interval, `at`: ReferencePoint)``. In the loop clause, `observed.event` identifies a `LoopObservation`. Each comparison below preserves the old variable names.

| Source | Datalog now | Native Rezono |
|---|---|---|
| `packs/std-loop/rules/comparison.dl` · `current_2` | `current(run, token, "absent", value, reason) :-`<br>`known_latest(run, token, time),`<br>`observed(run, token, time, event, "absent", value, reason),`<br>`loop_observation__scope(event, scope), loop_observation__sweep(event, sweep),`<br>`complete_sweep(run, scope, sweep, coverage),`<br>`sweep_window(run, scope, sweep, start, stop, coverage), start <= time, time < stop,`<br>`!non_absence(run, token, time).` | `rule current(run, token, "absent", value, reason) when`<br>`  known_latest(run, token, time)`<br>`  and observed(run, token, time, event, "absent", value, reason)`<br>`  and event.scope = scope and event.sweep = sweep`<br>`  and complete_sweep(run, scope, sweep, coverage)`<br>`  and sweep_window(run, scope, sweep, start, stop, coverage)`<br>`  and start <= time and time < stop`<br>`  and not non_absence(run, token, time)` |
| `run/packs/offer-selection/rules/selection.dl` · `selected` | `selected(d, o) :- eligible(d, o, _, _),`<br>`inventory = count : { offer(_) },`<br>`compared = count : { comparison(d, o, _, _, _) },`<br>`unavailable = count : { excluded(d, _) },`<br>`examined = compared + unavailable, examined = inventory.` | `rule selected(d, o) when eligible(d, o, _, _)`<br>`  and inventory = Offer.count()`<br>`  and compared = comparison(d, o, _, _, _).count()`<br>`  and unavailable = excluded(d, _).count()`<br>`  and examined = compared + unavailable`<br>`  and examined = inventory` |
| `run/packs/dispatch/rules/authorization.dl` · `conflicting_input_15` | `conflicting_input(c) :- approval__candidate(s, c),`<br>`approval__cap_micros(s, a), approval__cap_micros(s, b), a != b.` | `rule conflicting_input(c) when Approval.candidate(s, c)`<br>`  and Approval.cap_micros(s, a)`<br>`  and Approval.cap_micros(s, b) and a != b` |
| `examples/platform/rules/outage.dl` · `unavailable_service_2` | `unavailable_service(cause, consumer) :-`<br>`unavailable_service(cause, provider),`<br>`service_need__consumer(need, consumer), service_need__provider(need, provider),`<br>`service_need__mode(need, "run").` | `rule unavailable_service(cause, consumer) with need: ServiceNeed when`<br>`  unavailable_service(cause, provider)`<br>`  and need.consumer.id = consumer and need.provider.id = provider`<br>`  and need.mode = ServiceNeedMode"run"` |
| `examples/subsidy-scheme/rules/findings.dl` · `application_count` | `application_count(h, n) :- household(h),`<br>`n = count : { application__household(_, h) }.` | `rule application_count(h, n) when h in Household`<br>`  and n = Application.household(_, h).count()` |
| `packs/std-time/rules/time.dl` · `begun_at_1` | `begun_at(i, r) :- interval__on_axis(i, l), reference_point__on_axis(r, l),`<br>`reference_point__position(r, p), interval__start(i, s), s <= p.` | `rule begun_at(i, r) when i.on_axis = l and r.on_axis = l`<br>`  and r.position = p and i.start = s and s <= p` |

The outage seed explains the explicit `.id` in its recursive clause. The schema declares `FailureObservation` as a kind with its own identifier. Its description identifies the failed service by that key. There is no declared subtype edge to `Service`. A faithful interface is `unavailable_service(cause: Text, service: Text)` with seed `rule unavailable_service(cause, cause) when cause in FailureObservation.id`. Adding `cause in Service` would introduce a premise the original proof never read.

### Nine further conversion trials

| Source | Native clause | What the trial exposed |
|---|---|---|
| `packs/std-part/rules/part.dl` | `rule within(x, w) when within(x, v) and v.part_of = w` | `v` is an existential intermediate that remains visible in a witness. |
| `packs/std-order/rules/order.dl` | `rule before(a, c) when before(a, b) and c in b.precedes` | A multivalued forward slot uses membership. |
| `examples/subsidy/rules/ledger.dl` | `rule ledger_paid(a, t) when paid(a) and t = ledger_line(a, _, _).sum(it.cents)` | The payment key must survive into the contributor set. |
| `examples/subsidy-scheme/rules/assessment.dl` | `rule income_not_received(a, h) when a.household = h and not has_income_statement(h)` | The owner signature needs `absence`. A missing statement supplies no income amount. |
| `packs/std-loop/rules/complete_sweep.dl` | `rule complete_sweep(run, collector, window, ref) when sweep_node_counts(run, collector, window, ref, total, total) and total > 0` | The repeated `total` binds equal counts. The positivity test excludes a vacuous sweep. |
| `examples/subsidy-scheme/rules/scheme.dl` | `rule decided_parameter(p, d, r) when p.decision = d and decisions.in_force_on(d, r)` | `use std-decision as decisions` changes source lookup only. |
| `run/packs/cleanup/rules/pages.dl` | `rule reached_page(s, r) when reached_page(s, previous) and recorded_page(s, previous, _, t) and recorded_page(s, r, t, _)` | The two wildcards bind independently. Both page rows belong in the witness. |
| `examples/subsidy/rules/home.dl` | `rule scheme_evaluation_day(d) when d in EvaluationDay` | A real kind-membership premise must survive a projection. |
| `examples/subsidy-scheme/rules/costs.dl` | `rule quoted_costs(a, t) when has_quote(a) and t = line(a, _, _, _).sum(it.cents)` | The positive guard distinguishes unavailable totals from zero. |

**Extent of verification.** For these fifteen clauses from fifteen files, an in-memory expansion of the displayed spellings matched `rules_dl.to_rule` on head, ordered literals, conditions, assignments and aggregates, including aggregate measure position. The interleaving of body-element kinds matched too. This was a structural comparison with the checked-out parser. The proposed Ohm reader, linked type checker and end-to-end publication comparison remain implementation tests.

## 10. Mechanical conversion

1. **Read the old program in context.** Use `rules_dl.tokens`, `parse_file`, the resolved schema, seals, calculation selections, imports and remappings. Record statement order, clause positions and recognized annotations. Check `.decl`, `.input` and `.output` before dropping directives. Do not search-and-replace `__` or strip comments from strings.
2. **Preserve ownership.** Give the native module the old rule-module stem. During mixed-format migration, assemble clauses in the same logical module order across both formats. Preserve extension ownership and ordinal IDs. Two active definitions for the same module are an error. A legacy block named differently from its containing file needs a native module with the block’s identity.
3. **Recover interfaces.** Retain each ordered column name. Propagate constraints from schema slots, constants, calls and all defining clauses, including recursive components. Use an owning typed head with a body when the column and variable names coincide. Otherwise emit the signature and positional clauses. Retain bodyless extension points.
4. **Translate terms.** Preserve variables exactly, escaping reserved words. Preserve positive wildcards individually. Decode then re-encode text, signed integers, empty strings, enum literals and typed identifiers through the destination type. Reject unrepresentable IR constants. Never infer an alias, kind or currency from an example value.
5. **Translate atoms.** Use kind membership, schema slot-row patterns, owner-resolved relation calls, named calculation outputs and seal inputs. A scalar path is a valid shortening only when it expands to the same sequence of literal terms and known-value semantics. Keep named intermediates and independent repeated reads.
6. **Translate the body in place.** Commas become `and`, `!` becomes grounded `not`, and comparisons retain their orientation. Convert each aggregate atom into a row range, its local measure into `it.column`, and its result into the original variable. Preserve every aggregate position and arithmetic intermediate. Legacy integer division becomes `quotient`.
7. **Compare before accepting.** Compile both representations in isolated packs. Compare relations, column order, rule IDs, stable IDs, witnesses, worlds, annotations, SQL semantics, messages and role-visible results. Validate each source span, origin and definition pin against that representation’s own inputs. Source-byte hashes legitimately change.

The converter cannot deduce a missing nominal identity contract, completeness scope, currency, state cause or tie policy from `symbol`, `number` or `.output`. It cannot collapse two slot reads into a scalar if the rule is looking for contradictory values. It can report the precise columns or clauses needing a decision, preserve legacy scalar identifiers through explicit key paths where justified, and leave the original source active until parity passes.

## 11. Red tests and dependencies

Each row is one planner-owned red test and one branch claim. Freeze expected trees and evidence from the authored examples, old IR, checker fixtures or independent oracle before assigning the work. Tests that consume a form can use a hand-authored form. They need no working native parser.

| Red test | Green when | Actual prerequisite |
|---|---|---|
| `native-rule-form-contract` | The closed `/3` fixture, pointer order and offsets validate. Malformed alternatives fail. `/1` and `/2` retain their bytes. | None |
| `native-rule-reader-roundtrip` | The reader and printer reproduce hand-authored trees for both heads, multiline guards, escaped names, imports, paths and ranges. | None, use the frozen tree fixture |
| `native-rule-signatures` | A two-pass linker resolves forward and recursive signatures, typed local paths, inherited keys, pinned imports and extension ownership. | None, use hand-built trees and schema |
| `native-rule-safe-body` | Range restriction, scalar/set typing, fresh results, comparisons, world checks and stratification give the specified codes and spans. | None for the checker against a supplied signature environment |
| `native-rule-ir-listed` | The hand-authored `/3` form gives exactly `listed(?x)`, one `alpha(?x)` premise, the old stable ID and the new head span. | Form contract for the normal compiler entry point |
| `native-rule-ir-groups` | Fixed keys, distinct contributor keys, empty groups, ties and multiple aggregate positions lower to the frozen IR and pass independent group checks. | None for expression-to-statement lowering against a supplied environment |
| `native-rule-state-evidence` | Known, unknown, `n/a`, invalid, missing required values and withheld values have independently checked evidence or the specified refusal. A forged state row fails. | None, use authored state snapshots and projection metadata |
| `native-rule-dl-converter` | All 67 inputs are inventoried. The converter preserves annotations, terms, group identities and ownership, or reports a specific unresolved type or evidence requirement. | None, use the existing parser and frozen target forms |
| `native-rule-pack-link` | Ordinary pack compilation joins native and legacy modules in deterministic order, checks imports and rejects duplicate ownership. | Signatures and the native IR entry point |
| `native-rule-proof-mutations` | The checker rejects a missing completeness premise, changed binding, hidden aggregate domain, swapped group and a missing tied contender. | None, use independent IR and witness fixtures |
| `native-rule-publication-parity` | Both source paths publish the expected facts, conclusions, proofs, messages, role views and scenarios. Verify batch and incremental results and each publication’s local provenance. | Reader, linked checking, pack linker, group lowering and converter for the converted corpus. State projection only for cases that actually read it. |

A single non-recursive `listed` witness is the first integration gate. The scoped sweep and tied-offer cases are the acceptance gates for absence and choice. Agreement of row counts alone cannot make either gate green.

## 12. Compatibility and deferred state support

| Case | Decision |
|---|---|
| `n/a` in a stateful aggregate has conflicting specifications. | Keep relation-row counts and known-integer aggregates as specified. Refuse a direct stateful lowering where the two folds disagree. Settle the case `[known 7, n/a]` once for questions, rules and the checker before enabling it. [Existing value cases](../docs/semantics/value-cases.yaml) |
| Ordinary rule IR has no general operation to inspect a scalar’s state or cause. | Ship reads backed by a declared outcome or known selection first. Add authenticated state projections and independent checks before accepting general `is unknown`, `is n/a` and `is invalid` on stored values. |
| A typed source signature can express distinctions that the published IR erases. | Retain nominal column types in the linked source interface used by imports and questions. Continue to give the engines the existing `string` and `integer` columns. |
| Some legacy joins identify objects of different kinds by an external key. | Preserve them through explicit identifier paths where the pack supports that interpretation. Require an owner decision for stronger nominal claims. The outage seed is the regression case. |
| Clause ordinal IDs can change when an author inserts another clause. | Keep ordinal and stable IDs during conversion. Any change to message identity or historical proof lookup deserves its own compatibility decision. |
| The decision for `/2` predates native rules, and implementation support for the recorded block varies by component. | Read legacy blocks through their existing Datalog semantics during migration. Write native nodes as `/3` and retire the block spelling only after the corpus passes publication parity. |