# Rezono expressions and questions

This reference specifies the expression syntax and the forms used to ask questions. The [language reference](v0.md) covers declarations, types and shared semantics. The [implementation guide](../../rezono/README.md) describes current support.
## 1. What is frozen, and what is reserved

| Frozen in this slice | Reserved (parsed as a clear "not yet" error, R015) |
|---|---|
| expressions: literals, ids, paths, aggregates, quantifiers, filters, membership, ranges, comparisons, logic, arithmetic, `when … then … else`, `round`, rule calls | `order by`, `limit`, `group by` |
| `is known`, `is unknown`, `is n/a`, `is invalid` | several binders in one `ask` (`ask h: Host, p: Plan where …`) |
| `ask [binder:] Kind [context] where expr [show expr, …]` | evaluation of question contexts `at`, `as known`, `during` and `in` (§4 specifies their grammar) |
| `suppose` lines: `+ path = value`, `- path`, `- Kind id` | value time selection `x at d`, `x as known k` (grammar frozen, §4) |
| the JSON form of a question (§4a) | scratch rules in the REPL |
| the output schema of an answer (§8a) | reading an answer as a kind (§8a) |

Freezing means: a valid text keeps its meaning and its printed form. Additions later may not change the parse of any text that is valid today.

**How a reserved construct is reported.** It is parsed and printed like any other text. Parse-level checks come first (R016, R018). Then it is reported as R015 at its **span**: from its first keyword to the end of its operand (`at 2026-11-01`, `as known 2026-10-26`, `order by memory_need`). Its operands are not resolved or typed until its evaluation lands, so no further code is reported for that span.

## 2. Fixture schema

Examples use the public [conformance fixture schema](../../rezono/test/fixture.schema.json). Evaluation cases also use the data of Appendix B. This block describes the fixture in the v0 design notation:

```rezono
pack fixture
use std.units                       -- B, GiB
use std.money                       -- EUR, €

unit Count      = integer
unit EurPerHour = money EUR per hour

kind Provider  world closed
kind Host      world closed
  provider: Provider
  clusters: HostCluster* inverse host
  owner: Team?
kind HostCluster  world closed
  host: Host
  spec: ClusterSpec
  count: Count >= 1
kind ClusterSpec
  nodes: Count
  memory_per_node: GiB
kind Plan      world closed
  provider: Provider
  memory: GiB
  hourly_price: EurPerHour
  monthly_price: Money<EUR>
kind Team      world open

param host_reserve: GiB
extend Host
  derived memory_need: GiB = host_reserve + clusters.sum(count * spec.nodes * spec.memory_per_node)
rule fits(h: Host, p: Plan) when p.memory >= h.memory_need
```

## 3. Lexical additions

One: `true` and `false` are the two literals of `Bool`. v0 uses `Bool` but its literal table does not list them; this slice makes them explicit. Otherwise the v0 lexer applies as it is. Two clarifications:

- **Ids are literal tokens.** `host-b` is read by the expected kind. In `fits(host-b, plan)` the expected kind is `Host` from the rule's first binder. Where no kind is expected, write `` Host:`host-b` `` (R002).
- **A minus between names needs spaces.** `a-b` is one token (an id); `a - b` is subtraction.

Two words join the state tests and the question context: `invalid` after `is`, and `during` after the kind of an `ask`. Both are contextual (v0 §3), so a slot named `during` stays valid.

## 4. Grammar

```ebnf
question   = ask | suppose_line ;
ask        = "ask" [ binder ":" ] Type { "," binder ":" Type } { context } "where" expr
             [ "show" expr { "," expr } ] { tail } ;   (* a second binder is reserved *)
tail       = "order" "by" expr { "," expr } | "group" "by" expr { "," expr } | "limit" int ;   (* reserved *)
context    = "at" atom | "as" "known" atom | "during" atom | "in" atom ;   (* each axis once: R018 *)
suppose_line = ( "+" path "=" value ) | ( "-" path ) | ( "-" Type id ) ;

expr       = cond | imply ;
cond       = "when" expr "then" expr "else" expr ;
imply      = or_e [ "=>" imply ] ;                     (* right-associative *)
or_e       = and_e { "or" and_e } ;
and_e      = not_e { "and" not_e } ;
not_e      = "not" not_e | test ;
test       = range_e [ cmp range_e | "in" range_e | "is" state ] ;   (* non-associative *)
cmp        = "=" | "!=" | "<" | "<=" | ">" | ">=" ;
state      = "known" | "unknown" | "n/a" | "invalid" ;
range_e    = add_e [ ( ".." | "..<" ) add_e ] ;
add_e      = mul_e { ( "+" | "-" ) mul_e } ;
mul_e      = unary { ( "*" | "/" ) unary } ;
unary      = "-" unary | post ;
post       = atom { "." ( name | agg ) } [ timesel ] [ "where" expr ] ;
timesel    = "at" atom [ "as" "known" atom ] | "as" "known" atom ;   (* reserved *)
agg        = ( "sum" | "count" | "min" | "max" | "any" | "all" | "none" ) "(" [ expr ] ")" ;
atom       = literal | literal_tok | name | call | "(" expr ")" | Type ;
call       = name "(" [ expr { "," expr } ] ")" ;      (* a rule, or round(…) *)
```

**Precedence, lowest first:** `when … then … else`, `=>`, `or`, `and`, `not`, comparison / `in` / `is`, range, `+ -`, `* /`, unary `-`, postfix `.`, time selection and `where`. Comparisons do not chain: `a < b < c` is R016. A filter's condition extends as far as it can, to a closing parenthesis, a comma or the end of the enclosing condition: `Plan where a or b` filters on `a or b`; write `(Plan where a) …` to end it earlier. The reserved forms span from `,` (second binder) or `order`, `group`, `limit` to the end of their operand.

**Two places for time, one form each:**

- **The question context** stands between the kind and `where`: `ask Host at 2026-11-01 as known 2026-10-26 where …`. It sets the date, knowledge cut, stage and setup of the whole question for every subject that does not declare its own (v0 §5a). It is delimited by the kind and `where`, so it never touches the condition's parse. Each axis appears at most once (R018).
- **Value time selection** is a postfix of one path: `hourly_price as known 2026-10-26 <= € 0.20/h`. It selects one value along the validity or knowledge axis (v0 §6). Its operand is an `atom`.

Both forms are reserved for evaluation (R015 at their span, §1). [E30](cases/E30.yaml) shows why the question context needs its own place: in `ask Host where memory_need > 384 GiB at 2026-11-01`, `at 2026-11-01` is a postfix of `384 GiB`. The diagnostic points to `at 2026-11-01` and suggests `ask Host at 2026-11-01 where …` to set the question’s date.

## 4a. The JSON form of a question

A client can write a question as JSON. The JSON form is the same syntax tree, one object per node:

| Text | JSON |
|---|---|
| `ask h: Host at d where c show e1, e2` | `{"ask": "Host", "binder": "h", "context": {"at": d}, "where": c, "show": [e1, e2]}` |
| context axes | members `at`, `as_known`, `during`, `in` of `context` |
| literal, literal token, id | `{"lit": "384 GiB"}`, the source text |
| name or path | `{"path": ["h", "memory_need"]}` |
| aggregate, quantifier | `{"agg": ["sum", base, e]}`; `e` absent for `count()` |
| filter | `{"filter": [set, cond]}` |
| comparison, `in`, `is` | `{"cmp": [">", a, b]}`, `{"in": [a, b]}`, `{"is": [a, "unknown"]}` |
| range | `{"range": [a, "..<", b]}` |
| logic | `{"and": [a, b, …]}`, `{"or": [a, b, …]}`, `{"not": a}`, `{"imply": [a, b]}` |
| arithmetic | `{"arith": ["+", a, b]}`, `{"neg": a}` |
| condition, call | `{"when": [c, a, b]}`, `{"call": ["fits", [a, b]]}` |
| kind as a set | `{"kind": "Plan"}` |
| time selection | `{"timesel": [x, {"at": d, "as_known": k}]}` |
| suppose lines | `{"set": [path, value]}`, `{"retract": path}`, `{"retract_row": ["Plan", "plan-b"]}` |

- `and` and `or` are n-ary in the tree, so `a and (b and c)` and `a and b and c` are one question; both print as `a and b and c`.
- `print(from_json(j))` is the normal form of §9. `to_json(parse(t))` is canonical JSON (RFC 8785). The **question hash** in `GET …/ask/q/<hash>` is the SHA-256 of the canonical JSON of the question’s [normal form](../../rezono/README.md#the-question-hash): the binder by its canonical name, every path in full, the operands of `and` and `or` sorted, and a consistent orientation of a comparison.
  So text and JSON give the same hash (E52), and so do two ways of writing one question.
- **JSON Schema per role.** The gate generates a schema of this form from each role bundle: the role’s offered kinds as the values of `ask`, each kind’s offered slots as path names, and literals as strings with their type’s pattern. An agent decoding against the schema can name only what the role can read. In MCP, the schema describes the ask tool’s input; the tool’s `outputSchema` is the answer’s schema (§8a). A large answer is a `resource_link` to `GET …/ask/q/<hash>`. An ambiguous id (R002) is an elicitation.

## 5. Name resolution

1. **The binder.** `ask Host where …` binds an implicit binder named after the kind in snake case: `host`. `ask h: Host where …` names it `h`. The binder name is in scope in the whole question. Inside the condition a bare slot name resolves on the binder first: `memory_need` means `host.memory_need`.
2. **Aggregates, quantifiers and filters.** Inside `clusters.sum(…)`, `clusters.any(…)` and `Plan where …` names resolve on the element first (`it` is the element), then outside. A name found in both places is R011.
3. **Rules.** `fits(…)` is a call of the rule `fits`; arguments are checked against its binders. A rule and a slot with the same name is R001 with both candidates listed.
4. **Kinds.** A bare `Type` in expression position is the set of its rows: `Plan.count()`, `Plan where memory >= 512 GiB`.
5. **Ids.** Resolved by the expected kind (§3).
6. **`it` outside an element scope.** `it` exists only inside an aggregate, quantifier or filter. Elsewhere it is R001. Use the binder for the question’s row: `fits(host-b, plan)` is [E03](cases/E03.yaml), and `fits(host-b, it)` is [E33](cases/E33.yaml).
7. **Shadowing.** If the binder's kind has a slot with the binder's name (a kind `Host` with a slot `host`), a bare `host` is R011; name the binder (`ask h: Host where …`). Inside an element scope the same rule holds for element slots and outer names, as in rule 2. Nothing shadows silently.
8. **Visibility.** Names resolve against the role bundle (§7a). A kind, slot or rule the role does not read is not offered: R001 never suggests it.

## 6. Typing

- **Cardinality.** A path through a multivalued slot is a set. A set meets a single value only through an aggregate, a quantifier or `in` (R005).
- **Units.** Arithmetic and comparison check dimensions (R003). Literal quantities are converted exactly: `0.5 TiB = 512 GiB` holds.
- **Worlds.** `not`, `none(…)` and `all(…)` over a relation require it to be closed (R004). So do the aggregates `count`, `sum`, `min` and `max`: an open set is never known complete, so `Team.count() = 0` would claim what `Team.none(true)` claims. Over an open relation, use `is unknown` or a quantifier that does not need absence. An inverse slot is its forward slot read the other way. It is open when it says so itself, when its forward slot is open, or when the kind that carries the forward slot is open, because an element nobody listed may point here. A `closed` written on either slot does not close that.
- **Literal tokens.** Read by the expected type's literal grammar (R012, R013).
- **`show`.** Each shown expression must be single-valued per binder row (R005), or an aggregate.
- **`is`.** `x is known | unknown | n/a | invalid` takes any value or set and gives `Bool`.
- **Contexts**, once evaluation lands: `at` and `as known` need a `Date` or `DateTime` constant or parameter; `during` a stage of a kind with a `std.Order` view; `in` a setup id (R019; v0 §5a).

## 7. Truth and value states

Every value is `known`, `unknown(reason)`, `n/a` or `invalid`. A condition takes one of five values: `true`, `false`, `n/a`, `unknown` or `invalid`. Operators combine them by the normative tables of Appendix A:

- Strict operators (comparison, `in`, arithmetic, paths): with a non-known operand the result takes the highest state, in the order `n/a` < `unknown` < `invalid`.
- `and` is false if any operand is false, `or` true if any is true; otherwise they take the highest state among the undecided operands. `not` keeps a state. `a => b` is `not a or b`.
- `x is unknown`, `x is known`, `x is n/a`, `x is invalid` are always true or false.

**At the top of an `ask`** (a decision point, v0 §7b):

| Condition | Row |
|---|---|
| true | in the answer |
| false | left out |
| `n/a` | left out, and counted as `not_applicable`: it is a known fact that the condition does not apply |
| unknown, invalid | returned as an `undecided` row with its state, reason and cause |

Inside the condition `n/a` is not false. For a host without an owner, `not owner = team-platform` is `n/a`, so that host is in neither answer (E43). To include such rows, test the state: `owner is n/a or not owner = team-platform` (E47).

**An answer never drops an undecided row silently.** Rows where the condition is true are the answer. Rows where it is unknown or invalid are counted and returned separately as `undecided`, each with the reason that made it so, filtered for the role like every other row (§7a). The REPL prints them under the table: `2 rows · 1 undecided: host-a (owner unknown "not yet assigned") · 1 not applicable`.

**Sets and absence:**

- **Over an open relation "no member found" is unknown, never false.** `Team.any(true)` without a team, `owner in Team` for an owner that is not listed, and a call of an open rule that has no row are `unknown` with the reason code `open_world`. The rule's unknown names the row that would hold it as cause; a set over an open kind has no row to name. So `Team.any(true) = false` and `when Team.any(true) then false else true` are valid and never true by absence (E56, E57). R004 (§6) refuses the forms that need absence.
- **A filter is a decision point.** A member whose condition is true is in; false and `n/a` are out, and counted nowhere; with an unknown or invalid condition the member stays, with that state, reason and cause on its membership. `count`, `sum`, `min` and `max` are strict in the memberships as they are in the members (A.3): a count stays undecided where a membership is, because evaluation does not reason about bounds (E58). `any(p)` folds `or` over "in and p", `all(p)` folds `and` over "in => p", `none(p)` is `not any(p)` and `x in S` is `any(it = x)`. So a member that is known to match, or known not to, still decides (E59, E60).
- **An element whose forward value is unknown or invalid** is a member, with that state on its membership, of every set that the inverse slot gives: asked from either end, the one relation gives one answer (E64). A forward value that is `n/a` names no element. A required forward value that a row does not give is unknown by its cardinality (§7a rule 1).
- **An element of an open kind that has no row.** Every slot of it is `unknown` with reason `open_world`, whatever the slot's cardinality: nothing is known of that element, also not that an optional value is absent (E62). In a closed kind such a reference is a defect of the dataset, not a state.
- **`count` is strict in its members**, as `sum`, `min` and `max` are: `Host.memory_need.count()` with an unknown value is unknown (E61).

## 7a. Visibility and the two-world rule

Answers expose only the role’s readable data. The following rules apply to rows, witnesses, reasons, counts and cursors.

1. **One view.** An answer is a function of the role’s view of the pinned manifest: the scoped relations and witnesses the gate serves to that role. A row the role cannot read does not exist for the question. Its absence is read by the world the relation has **for that role**: a relation is closed for a role only if it is closed and the role reads it in full. Whether it does follows from the shape of the role’s read rules, so it is the same in both worlds of rule 5.
   - Over a relation the role reads in full: a missing `T` is unknown, a missing `T?` is `n/a`, an absent member of a closed relation is absent.
   - Over a relation the role reads in part, or not at all: a single value that is missing is `unknown` with the reason code `not_read_in_full`, also for a `T?`. The role's files cannot tell "no value" from a value the role does not read, and `n/a` would claim the first. The cause is the row that would hold the value. It has no absence proof: here an absence proves nothing. A set over such a relation is open for the role (§6, R004; §7, "Sets and absence").
2. **Names** resolve against the role bundle (§5 rule 8). Typing uses the same bundle.
3. **Undecided rows** have a binder row and a cause the role reads; the reason is the reason code of that readable value row.
4. **Counts** (`rows`, `undecided`, `not_applicable`) and **cursors** are computed after rule 1, over readable rows only.
5. **Two-world rule.** Two manifests whose role views are equal give byte-identical answers for that role: rows, witnesses, undecided rows, reasons, counts, cursors and dataset hash. Rows the role cannot read and that no readable row depends on change nothing ([E49](cases/E49.yaml)). A hidden value row and its reason look exactly like an absent one ([E50](cases/E50.yaml)).

## 8. Meaning: what an `ask` compiles to

An `ask` is a rule without storage. `ask h: Host where c show e1, e2` lowers to anonymous rules over Rule IR:

```text
q(h, e1, e2)                          :- Host(h), c = true.     -- c, e1, e2 lowered like a rule body
q_undecided(h, state, reason, cause)  :- Host(h), c in {unknown, invalid},
                                         (state, reason, cause) = decisive(c).
q_not_applicable(h)                   :- Host(h), c = n/a.
```

`decisive(c)` follows Appendix A down to the operand that gives `c` its state and returns that state, reason and **cause**: a typed RowRef (relation and canonical key, defined by the [proof contract](../../contracts/proof.yaml)) of the input value, typed by the kind and slot of its relation in the bundle. Ties follow A.4. The witness of an undecided row is the cause’s witness plus the table steps, which the checker recomputes. A “why not” is a failed proof.

Aggregates lower to aggregate subqueries, quantifiers to existence and, for `all` and `none`, to negation over a closed relation. The result has witnesses like any derived row, so `:grounds` works on every answer row. Default `show`: the binder and every single-valued value the condition reads, in source order; an aggregate or quantifier is shown as itself (`clusters.count()`), never its input set.

**Contexts.** `ask K at d`, `as known k`, `during s` and `in x` set the [question context](v0.md#5a-validity-and-applicability-contexts) for subjects that do not declare their own: date, knowledge cut, stage and setup. `x at d` selects the version of `x` valid at `d`, and `x as known k` its value as known at `k`. The design carries the context to each versioned premise (`calc__as_of(valid_at, known_at)`, extended to stage and setup). A version gap gives `unknown no_version_applies` and an overlap gives `invalid versions_overlap`. A client can choose an older knowledge state by pinning an older manifest.

**`suppose` lines** are deltas against the pinned manifest, for the session or question only: `+ x2.count = 3` sets a value, `- x2.owner` retracts one, and `- Plan plan-b` retracts a row. They use the same delta format as `propose`.

**Execution.** An engine such as DuckDB or Feldera runs questions over published manifests with a cost budget and handles storage, optimization and transactions.

## 8a. The answer is a typed dataset

A query is a migration, so an answer is a typed dataset (v0 §8b). The **output schema** of an `ask` is a publication schema document generated from the question:

- Kind `Answer`, keyed by the binder row's id. Slot `binder`, a `ref` to the binder's kind in the pack schema (through `imports`), with the binder's name (`host`, `h`) in `expr`. One slot per shown expression, named `c1`, `c2`, … in show order, with the expression's type, every state it can take by typing (§6; `invalid` included wherever an input or calculation can be invalid), and the printed expression in `expr`. Slot names are fixed, so no binder name can collide with them.
- Kind `Undecided`, keyed by the binder row's id. Slots: `binder`; `state` (enum `unknown`, `invalid`); `reason` (a reason code); `cause_relation` and `cause_key` (the typed RowRef of the cause: the relation id and the canonical JSON of its key). For a missing value the cause is the row that would hold it, with an absence proof, except over a relation the role reads in part, where an absence proves nothing (§7a rule 1); for a state written as a constant both are `""`.
- The answer’s `$schema` is the id of its schema, so a client can read its declared types. `$why` gives each `Answer` row’s witness and each `Undecided` row’s failed proof.
- **A shown amount that its type cannot hold.** `Money` has exactly the decimals of its `scale`, and a `Quantity` is a whole number of its storage unit at its scale. An amount that cannot be represented is `unknown not_exact` in that column; the answer keeps the row. Inside a condition fractions stay exact, a plain number is a `Ratio` (`1/3`), and a quantity whose stored integer is whole keeps a fraction of its unit where no decimal is exact (`7/3600 h`). The check warns beforehand (W105) for a shown amount that divides or multiplies by anything but a whole number; `round` removes the warning ([E63](cases/E63.yaml)).
- **Reason codes of evaluation.** `open_world` (§7), `not_read_in_full` (§7a rule 1) and `not_exact` label `unknown`. The output schema has no `reasons` member, so a reader accepts them.
- **Counts.** The [answer contract](../../contracts/explain.yaml) defines the envelope (`rezono.answer/1`). It carries `counts`: `rows`, `undecided` and `not_applicable`. They follow §7a rule 4.
- **Pages.** `Answer` and `Undecided` rows are each in canonical key order (the UTF-8 bytes of the canonical JSON of the key). A page holds at most `limit` of each and its cursor is the pair of last keys. Every page is a slice of one immutable answer whose dataset hash is the ETag.
- **Access epoch.** The answer URL or cache key carries the role’s access epoch and rejects a stale epoch. A rights change makes old answers unreachable.
- **Composition.** Reading an answer as a kind is reserved. When it lands, asking q2 over the answer of q1 must give the same rows and witnesses as the composed question (E53).

Example: E51's output schema has `Answer` slots `binder` (`ref` `Host`, `expr` `h`), `c1` (`GiB`, `expr` `h.memory_need`) and `c2` (`ref` `Team`, `expr` `owner`), each with the states typing gives.

## 8b. Effect classes

Every form has an effect class (v0 §5d), and every implementation (compiler, REPL, endpoint, MCP) reports it with the command:

| Form | Class | Note |
|---|---|---|
| `ask` | `reads` | reads the pinned manifest; changes nothing |
| `suppose` line | `transacts` | applies a delta for the session or question, then discards it |
| `propose` | `writes` | through review; not in this slice |
| check-only (parse, resolve, type, output schema; no rows) | `computes` | the MCP check-only tool, REPL `:check`, and language validation |

The check-only mode returns diagnostics and, for an `ask`, the output schema (§8a). It never evaluates and never reads rows (E54).

## 9. Printing

The printer gives every valid text one normal form, so `print(parse(t))` is stable and `parse(print(ir)) = ir`:

- keywords lowercase; one space around binary operators and after commas; none inside parentheses;
- parentheses only where precedence needs them; `and` and `or` chains print flat (§4a);
- a literal keeps the scale it was written with (`€ 0.20/h` stays `€ 0.20/h`); a computed value prints with the scale of its type (`€ 0.1250/h`, `400 GiB`); a plain exact number prints as the shortest exact decimal, else as a fraction (`1/3`);
- an implicit binder stays implicit; `it` is printed only where it was written or where R011 required it, and only inside an element scope;
- the question context prints after the kind in the order `at`, `during`, `in`, `as known`.

## 10. Diagnostics added by this slice

| Code | Kind | Example |
|---|---|---|
| R014 | error | `ask host where …`: `ask` needs a kind name, `Host` |
| R015 | error | `order by` is reserved for a later version of Rezono |
| R016 | error | `a < b < c`: comparisons do not chain; write `a < b and b < c` |
| R017 | error | `ask Host where memory_need`: the condition is a `GiB`, not a truth value |
| W105 | warning | `show owner`: `owner` may be unknown; unknown values print with their reason |

All earlier codes (R001–R013, W101–W104) apply unchanged. The v0 revision adds R018–R034 and W106–W112 (v0 §10). This slice uses two of them:

| Code | Kind | Example |
|---|---|---|
| R018 | error | `ask Host at 2026-11-01 at 2026-12-01 where …`: a context axis is given twice |
| R019 | error | `ask Host at memory_need where …`: `at` needs a date (reported once evaluation lands; until then R015) |

## 11. Conformance cases

Each case links the exact source to its expected normal form, diagnostics or evaluation result. Evaluation cases use the data of Appendix B. The publication cases P01–P07 exercise `check`, `require` and `warn` at their decision point ([v0 §7b](v0.md#7b-truth-and-value-states)). The decision-table cases T01–T07 use the [decision-table design](../../decisions/language-tables.md). Evaluation cases can `declare` an enum and table on `Host` before the question; check-only cases use `source` for those declarations.

There is one YAML file per case in [cases](cases). The [conformance runner](../../rezono/test/conformance.test.ts) asserts every expected field it can produce. [The remaining fields](../../rezono/test/not-yet.json) record the limits of the current runner.

A `settled` case is a conformance outcome. An `open` case records more than one reading; implementations run it and can follow the main expectation or an alternative. A `pending` case becomes runnable once the construct is implemented.

- A key absent from `expect` is not asserted; a key present is exact. `diagnostics` is the full list in source order, and `[]` means none.
- A span is the text and its 0-based code-point offsets into `source`, end exclusive. This text fixes the spans of R015 (§1), R018 and R001 at `it`; for the other codes the case gives the smallest expression the diagnostic is about (§13 point 11).
- `status` is `settled`, `open` (the case gives its `expect` and `alternatives`), or `pending` when its construct is reserved.
- `given` changes the case data with suppose lines (§4). In two-world cases, `worlds` lists each world's changes and `hidden` the rows (`host-e`) or values (`host-a.owner`) the role cannot read. `reads_in_part` lists the slots (`Host.owner`) whose relation the role reads in part (§7a rule 1); it is the case's, the same in every world.
For example, [E02](cases/E02.yaml) checks printing with an explicit binder, [E49](cases/E49.yaml) and [E50](cases/E50.yaml) check role visibility in two worlds, [P02](cases/P02.yaml) checks when `require` blocks publication, and [T01](cases/T01.yaml) evaluates a decision table.
<a id="12-work-packages"></a>

## 12. Implementation

The [language implementation](../../rezono/README.md#the-json-form-of-a-module) reads pack modules and emits their JSON form for the compiler. Its [conformance runner](../../rezono/test/conformance.test.ts) exercises question parsing, typing and evaluation.

## 13. Design boundaries and open points

These points give the design choices and the remaining alternatives used by the conformance cases.

1. **`undecided` in the answer contract.** The [answer contract](../../contracts/explain.yaml) gives `Undecided` rows a state, reason and typed cause, records `counts.not_applicable` and names the output schema.
2. **`n/a` in conditions.** `n/a` propagates by Appendix A. At the top of an `ask` the row is left out and counted as `not_applicable` (§7).
3. **Default `show`.** The answer dataset carries every value the condition reads (§8). Column folding is a display choice for the reader.
4. **Question date versus subject date.** Evaluation of question contexts is reserved (§1, R015). The [language design](v0.md#5a-validity-and-applicability-contexts) gives precedence to a subject’s `applies at`.
5. **Stale access epoch.** The status code and how a client learns the new epoch depend on the endpoint. No syntax or conformance case here depends on those choices.
6. **Cursor.** A page has one cursor, the pair of last keys of `Answer` and `Undecided` (§8a, E49). Separate paging for `Undecided` would be additive.
7. **Reason ties.** Take the least reason code, then the cause whose RowRef sorts first (A.4). This makes `and` and `or` commutative in both state and reason.
8. **E36: R015 on one axis or both.** [E36](cases/E36.yaml) lists both spans in source order, following §1, and records the alternative that reports only `at 2026-11-01`.
9. **When W105 fires.** E27 gives W105 for `show owner`; E54 (E02 in check-only mode) gives no diagnostics, although `h.memory_need` can be unknown (host-d in Appendix B). Proposal: W105 fires for a shown expression that can be unknown on a row where the condition is true. In E02 the condition `h.memory_need > 384 GiB` is true only where `memory_need` is known, so no W105; in E27 and E51 nothing constrains `owner`, so W105 at `owner`. E51 records this (`status: open`).
10. **E50 and the effective world.** A relation is closed for a role only if it is closed and the role reads it in full. A single missing value in a relation that the role reads in part is `unknown not_read_in_full`, including for an optional slot. In [E50](cases/E50.yaml) both worlds give the same bytes: row host-c, undecided host-a, two not-applicable rows and no `not_assigned` reason.
11. **Spans that the grammar leaves open.** For R001 (other than `it`), R003–R005, R014, R016, R017 and W105, the cases use the smallest expression the diagnostic is about, for example `clusters > 2` for R005.
12. **Plain syntax errors.** The [implementation](../../rezono/README.md#what-the-parse-reports) reports R000 at the point where the text stops matching the grammar.
13. **An open relation read without `not`.** `Team.any(true) = false`, `when Team.any(true) then false else true` and `owner in Team` are valid. “No member found” over an open relation is `unknown open_world` (§7, E56 and E57).
14. **A filter’s condition in a state.** A filter is a decision point. A member whose condition is unknown or invalid keeps that state on its membership. The same applies to an element of an inverse set whose forward value is in a state (§7, E58–E60 and E64).
15. **An `n/a` member of an aggregate.** In `Host.owner.count()` with a host that has no owner, A.3 makes the count `n/a`, the highest state among its members. The [value cases](../semantics/value-cases.yaml) record the open aggregate case.
## Appendix A. Truth tables (normative)

The [value cases](../semantics/value-cases.yaml) also record the operator tables as data. Here `false and invalid` is false and `true or invalid` is true. Publication still handles invalid inputs at the corresponding decision point (v0 §7b).

Values: T true, F false, N `n/a`, U `unknown`, I `invalid`. Rows give `a`, columns give `b`. The tables of `and` and `or` are commutative; the table of `=>` is not (`T => F` is F, `F => T` is T), so an implementation never swaps its operands.

**A.1 `and`, `or`**

| `a and b` | T | F | N | U | I |
|---|---|---|---|---|---|
| **T** | T | F | N | U | I |
| **F** | F | F | F | F | F |
| **N** | N | F | N | U | I |
| **U** | U | F | U | U | I |
| **I** | I | F | I | I | I |

| `a or b` | T | F | N | U | I |
|---|---|---|---|---|---|
| **T** | T | T | T | T | T |
| **F** | T | F | N | U | I |
| **N** | T | N | N | U | I |
| **U** | T | U | U | U | I |
| **I** | T | I | I | I | I |

**A.2 `not`, `=>`, `when`**

| `a` | T | F | N | U | I |
|---|---|---|---|---|---|
| `not a` | F | T | N | U | I |
| `when a then x else y` | x | y | N | U | I |

| `a => b` | T | F | N | U | I |
|---|---|---|---|---|---|
| **T** | T | F | N | U | I |
| **F** | T | T | T | T | T |
| **N** | T | N | N | U | I |
| **U** | T | U | U | U | I |
| **I** | T | I | I | I | I |

**A.3 Strict operators.** For comparisons `= != < <= > >=`, `in`, arithmetic, paths, `round` and date arithmetic: if every operand is known, the result is computed (T or F for a comparison). Otherwise it is the highest state among the operands, N < U < I. So `n/a = n/a` is N, not T; test states with `is`. Aggregates (`count`, `sum`, `min`, `max`) over a known set are strict in their members, and in whether each one is a member (§7, "Sets and absence"); `min` and `max` of an empty set are `n/a empty`; `any` folds `or` from F, `all` folds `and` from T, `none(p)` is `not any(p)`. An aggregate over a set in a state takes that state.

**A.3b `is`**

| `x` is | known | `n/a` | unknown | invalid |
|---|---|---|---|---|
| `is known` | T | F | F | F |
| `is n/a` | F | T | F | F |
| `is unknown` | F | F | T | F |
| `is invalid` | F | F | F | T |

**A.4 Reasons.** A result in state N, U or I carries the reason and cause of an operand in that state. If several operands qualify, it takes the least reason code (UTF-8 byte order), then the cause whose RowRef sorts first (relation, then canonical key). A constant state without a cause (`unknown no_rate` written in the text) sorts before any cause. This keeps the `and` and `or` tables commutative in reason as well as in state.

**A.5 Decision points** are listed in v0 §7b. For `ask`: T row, F left out, N left out and counted, U and I undecided.

## Appendix B. Data for the evaluation cases

The fixture schema of §2, with `Team` element `team-platform` and these hosts (role `viewer` reads all of them, except where E49 and E50 say otherwise):

| Host | `owner` | `memory_need` |
|---|---|---|
| host-a | `unknown not_assigned` | 400 GiB |
| host-b | `n/a` (no owner) | 200 GiB |
| host-c | team-platform | 512 GiB |
| host-d | `n/a` (no owner) | `unknown no_spec` |
