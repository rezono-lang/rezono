# reckon

Reckon is the language of Rede's control plane ([docs/reckon](../docs/reckon/v0.md), decision O14). This directory is its implementation, one slice at a time. The first slice is the part that questions use, frozen in [docs/reckon/expressions.md](../docs/reckon/expressions.md) (P10.2a): expressions, `ask`, suppose lines and the JSON form. The first declarations are the check statements of [v0 §5](../docs/reckon/v0.md#checks-norms-and-requirements): `check`, `require` and `warn`, decided at publication (v0 §7b).

It is plain TypeScript that Node 24 runs as it is, like the gate and the REPL, because those two and the tools for agents are what read a question. Nothing here knows a domain: no kind, unit, currency or label is named in the code.

| File | What |
|---|---|
| `src/grammar.ts` | The grammar of §3 and §4, rule for rule, as an [Ohm](https://ohmjs.org) grammar. Ohm reads the grammar text at start; there is no generated parser and no `eval`. |
| `src/tree.ts` | The syntax tree. It is the JSON form of §4a itself: one plain object per node. |
| `src/parse.ts` | Text to tree, with the diagnostics the parse itself gives, each with its span in code points. |
| `src/print.ts` | Tree to the normal form of §9, and the fully parenthesised `grouping`; a module to its normal form (`printModule`). |
| `src/json.ts` | The JSON form (§4a): reading it, and its canonical JSON (RFC 8785, [`viewer/src/lib/canon.ts`](../viewer/src/lib/canon.ts)). |
| `src/normal.ts` | The normal form of a checked question and the question hash taken from it ([below](#the-question-hash), decision Q21). |
| `src/module.ts` | A file of Reckon read into its declarations ([below](#a-module-read)). |
| `src/module-json.ts`, `src/write-form.ts` | The JSON form of a module, which the compiler reads ([below](#the-json-form-of-a-module)), and the command that writes it to a file. |
| `src/schema.ts` | What a question is checked against: the schema of the role that asks, as a [Reckon Data](../docs/reckon-data/l0.md) schema document with the rules, parameters and money symbols a question can name, and the slots the role reads in part. |
| `src/check.ts` | Names (§5) and types (§6) of a question against that schema, with their diagnostics, and what the question shows. It reads no row: this is the check-only mode of §8b. |
| `src/table.ts` | The check of declarations on top of a schema, as far as it is built: an enum, and a derived value by a decision table, with the two proofs of its rows ([below](#a-decision-table)). |
| `src/answer-schema.ts` | The output schema of an `ask` (§8a): a Reckon Data schema document generated from the checked question. |
| `src/evaluate.ts` | The answer of a checked `ask` over the rows a role reads (§7, §7a, Appendix A): rows, undecided rows with state, reason and cause, and counts, as a dataset of the output schema; suppose lines; pages. What a check statement decides at publication (`publish`). And the value of a decision table for every element, with its witness (`tabulate`). |
| `messages/<language>.json` | The sentence of each diagnostic code and each hint, per language. The code holds no text for users: a diagnostic carries its code, its span and the values its sentence needs. |

```ts
import { check, outputSchema, parse, print, questionHash } from './src/index.ts';

const { tree } = parse('ask Host where memory_need>384 GiB');
print(tree); // ask Host where memory_need > 384 GiB
await questionHash(check('ask Host where memory_need>384 GiB', schema), schema); // the hash of the question's normal form
await questionHash(check('ask h: Host where 384 GiB < h.memory_need', schema), schema); // the same hash: one question

const checked = check('ask Host where memory_ned > 384 GiB', schema);
checked.diagnostics; // R001 at `memory_ned`, suggest `memory_need`
await outputSchema(tree, check(print(tree), schema), schema); // kinds Answer and Undecided

const data = load(schema, rows); // the role's rows, as Row JSON of Reckon Data
const a = await answer(check('ask Host where owner = team-platform', schema), schema, data);
a.rows; // [{$kind: 'Answer', $id: 'host-c', binder: …, c1: …}]
a.undecided; // [{$id: 'host-a', state: 'unknown', reason: 'not_assigned', cause_relation: 'host__owner', cause_key: '["host-a"]'}]
a.counts; // {rows: 1, undecided: 1, not_applicable: 2}
```

## What the parse reports

| Code | When |
|---|---|
| R000 | A plain syntax error, at the token where the text stops being Reckon. The code is a working choice: [v0 §14 point 17](../docs/reckon/v0.md#14-open-points-09-11) leaves it open. |
| R014 | `ask host where …`: `ask` needs a kind name. |
| R016 | `a < b < c`: comparisons do not chain. |
| R018 | A context axis is given twice. |
| R015 | A reserved construct, at its span: a second binder, `order by`, `group by`, `limit`, a question context, a time selection on a value. A time selection on a literal carries the hint of §4: the writer meant the question's context. |

Parse-level checks come first (§1): with an R000, R014, R016 or R018 there is no tree and no R015. A text with only R015s has a tree, so it prints; it is not evaluated.

## What the check reports

`check(text, schema)` parses and then resolves and types the question. Each diagnostic is at the smallest expression it is about (§13 point 11). A reserved construct is not looked into (§1).

| Code | When |
|---|---|
| R001 | An unknown name: a kind, a slot, a rule, a unit, a money symbol. `suggest` lists the names in scope one edit away (two for a word of six letters or more; a swap of two neighbours is one edit) and the slots one single-valued step away (`spec.nodes` for `nodes`). `it` outside an aggregate, a quantifier or a filter is R001 with the question's row as hint (§5 rule 6). |
| R002 | An id where no kind is expected: `host-b is known`, or an id at the head of a path whose slots several kinds have. |
| R003 | Two types that do not go together: dimensions that differ (`GiB + €`), and every other pair an operator cannot combine (a kind and a quantity, `<` between two elements, a call with the wrong arguments, `in` with one value on its right instead of a set or a range, a date beside anything but a number or a date). |
| R004 | `not`, `none(…)`, `all(…)`, the left side of `=>` or an aggregate (`count`, `sum`, `min`, `max`) over an open kind, an open multivalued slot or an open rule: a row that is missing there is unknown, not false, and a set that is not known complete cannot be counted (decision W6). An inverse slot is open when it says so itself, when its forward slot is open, or when the kind that carries the forward slot is open. |
| R005 | A set where one value is needed: an operand of a comparison or of arithmetic, an argument, a shown expression, the condition; a set as one branch of `when` and one value as the other. |
| R011 | A bare name that is found in two scopes: a slot of the element and a name outside it, or the question's row and a slot of its kind with the same name (§5 rules 2 and 7). |
| R012, R013 | A literal token that the type its context expects does not read (the type's `pattern`), and one where no such type is expected. |
| R017 | Something that is not a truth value where a condition stands. |
| R030 | A second argument of `round` that is not one of the four roundings (`half_even`, `half_up`, `down`, `up`) by its bare name ([v0 §5f](../docs/reckon/v0.md#5f-dates-periods-and-rounding)). |
| W105 | A shown expression that reads a value that can be unknown on a row of the answer; and a shown amount of money or quantity that divides, or multiplies by anything but a whole number, because its type may not hold it (it is then shown as `unknown not_exact`). `round` takes the second away. |

## What an answer is

`answer(checked, schema, data)` evaluates a question that checked without an error; one that did not is never evaluated. `data` is what `load` reads from the role's rows as Row JSON ([Reckon Data §3](../docs/reckon-data/l0.md#3-row-json)), with the rows of each rule and the value of each parameter beside them. Nothing else is read, so two publications with the same view for a role give the same bytes (§7a rule 5; E49, E50).

| Part | What |
|---|---|
| States | Every expression is known, or `n/a`, unknown or invalid with a reason and a cause. Strict operators take the highest state (A.3); `and`, `or`, `not`, `=>` and `when` follow A.1 and A.2; `is` is always true or false (A.3b). The tables are tested cell for cell against the data of seam S1 ([`value-cases.yaml`](../docs/semantics/value-cases.yaml), `tables`). |
| Reasons | Of several operands in the deciding state: the least reason code by its UTF-8 bytes, then a constant before any cause, then the cause whose row sorts first (A.4). The cause is a row: its relation (`host__owner`) and its key. |
| Numbers | Exact fractions of two integers in the storage unit of their dimension. `0.5 TiB = 512 GiB` holds; nothing is rounded but by `round`. No floating point. |
| The top | True: a row with its shown values. False: left out. `n/a`: left out and counted. Unknown or invalid: an undecided row (A.5). Rows come in the canonical order of their key. |
| The dataset | Rows of kind `Answer` and `Undecided` as Row JSON of the output schema, whose id is the answer's `$schema` (§8a). `page` cuts it into pages with the pair of last keys as cursor. |
| Suppose lines | `suppose(data, line, schema)` gives the rows with one line applied, and leaves the rows handed in as they were. |

A question that checks and that evaluation cannot compute yet is refused with `NotEvaluated`, never answered: arithmetic on dates and periods, an aggregate of a range, `round(x)` in a pack that names no rounding.

Two more refusals keep a part from standing for the whole. **A budget of steps:** `answer(checked, schema, data, { steps })` counts one step for each expression it evaluates on each row, for each slot it reads and for each member of a set it counts or searches, and stops with `OverBudget` when the count passes the limit. The count follows from the question and the rows handed in, so the same question over the same view is cut at the same point. Without a limit nothing is counted against. **What was loaded:** `load(schema, rows, { only })` says for which kinds and slots the rows were read; a read of another is refused with `NotLoaded`, because a slot that was never read would look like a value that is not there.

## What a check statement decides

`check memory_bound: host.memory_need <= 600 GiB` ranges over every element of the kind its condition names in lowercase (v0 §5), as an `ask` ranges over its kind, and `publish(checked, schema, data)` decides it over the rows the role reads (v0 §7b):

| Condition | `check` | `require` | `warn` |
|---|---|---|---|
| true, `n/a` | passes | passes | passes |
| false | a violation; blocks | a violation; blocks | a violation (a warning) |
| unknown | an undecided violation; publishes | an undecided violation; blocks | an undecided violation |
| invalid | an undecided violation; blocks | an undecided violation; blocks | an undecided violation |

The result names the violations, the undecided violations with state, reason and cause, and the elements that block, each in key order, and the outcome: `blocked` when one element blocks, `publishes` otherwise. P01 to P07 run it.

- **The JSON form of a check statement** is `{"check": "require", "name": "memory_bound", "cond": c}`, with `name` absent for an anonymous `warn …`. §4a has no row for a declaration; the tree is the JSON form, as for a question, so it reads back by the one test of `from_json`, and its hash is taken the same way.
- **One kind per statement.** A condition that names two kinds in lowercase has two binders, reserved as in an `ask` (R015 at the second, §1). A condition that names no kind (`check isolated(tenant-a, management)`) checks, and `publish` refuses it with `NotEvaluated`: what its violation row is keyed by is not written down yet.
- **Not read yet** (R000): a check with versions, `requires n sources`, `because`. `norm` parses and is R015 at the whole statement (v0 §5: reserved). A pack's schema reaches the check and the evaluation as a Reckon Data schema document.

## A module, read

`parseModule` (`src/module.ts`) reads a whole file of Reckon into its declarations (v0 §5, §11): the header (`reckon`, `pack`, `use`), `rounding`, `reason`, `unit`, `enum`, `param` with its versions, `kind` with `applies`, `sealed` and its slots, `extend` with `derived` values (`=`, `unless` clauses and blocks, versions, a decision table), the check statements above, and facts as a table or per row with `valid` and `known`. It is a parse only (RV-X29): no name is resolved, no type checked, nothing evaluated, and nothing here claims that a reserved construct works.

- **Layout.** A deeper line opens a block under the line before it, unless either line shows that the statement goes on (v0 §11, "Lines that go on"); then it is a continuation. Each logical line is read by the grammar's `Line` rule with the rest of the file blanked, so every span is a place in the file.
- **Diagnostics.** R000 for a syntax error and for a line where its block does not allow it, at its first word; R014 and R016 as in a question; R015 for a time selection on a value and `norm`; R001 for a name after `->` in the header of a table that is not the name of its derived value; W108 where every version of a declaration starts at a `valid` date (the time before the earliest one has no value). Only that first gap is reported; a gap between versions needs the order of their contexts. A statement that stops short is an R000 at the end of its line.
- **Nothing is dropped.** What the tree could only hold by leaving a part out is refused, so that a tree never says less than its text: a second `applies` or `sealed` in a kind (R000), `valid` or `known` twice on one version or fact row (R018), a fact table whose header is not a row of names, and a fact row that has not one value for each column, or `-` or `->` for one (R000 at the row). A line under a line that takes no block is an R000 at its first word, whatever it is: under a `when` line of an `unless` block, under an `unless` with its clause, a version, a slot, a row, an assignment or a check, so a clause one step too deep is never left out. A text literal and an id between backticks end on the line they start on (v0 §11): a line end inside one is an R000 from its opening mark to the end of that line, so no value holds a line end and the indent after it. Of a decision table: one without a header, a header whose last cell is not `->` and a name (R000 at the header), a row that has not one cell for each input and then its value, a second `table` under one derived value, a table beside `=`, `unless` or a version, and any line under a line of a table (R000 each).
- **A decision table** is read into the tree of [tables.md §2](../docs/reckon/tables.md#2-grammar): `{"table": policy, "inputs": […], "output": name, "rows": [{"tests": […], "value": {"lit": …}}]}`, a cell `"-"` or the list of its tests, a test a value or `{"between": {"from", "op", "to"}}` with an end left out when it is open. The lines under `table` are read by two rules of their own (`TableHead`, `TableRow`), so a value is a literal, an id or a bare word as it was written, never a name in scope and never a state. `total` before `derived` is read on a value with a table, and only there (v0 §5d; R000 elsewhere).
- **Places.** Every expression and every declaration has its place in the text (`spans`): a declaration, a slot, a derived value, a version, a `use` line and an assignment of a fact row at their name, a check statement at the whole statement, a decision table at `table <policy>`, a row of it at its whole line, a test and a value of it at their text.
- **Not read yet** (R000): `rule`, `decide`, `assume`, `theory`, `view`, `example`, `literal`, `exception`, `deprecated`, `private`, the totality and effect words (but `total` on a derived value with a table), a calculation definition (`calcdef`), a version with a block body, `replaces` lines, the `during` and `in` contexts of a version, a doc comment as the declaration's documentation (it is read as a comment).
- **Accepted on** `examples/zorgtoeslag`: both files are modules of the pack, and its case Z20, the diagnostics of the pack as written, runs in `test/examples.test.ts`: four W108 and one R015, the time selection; its two decision tables (`threshold_rate`, `grounds`) are read without a diagnostic. Its other cases but Z22 (below) are future evidence and show as todos with the case that blocks them. The pack is not published: it becomes a pack with RV-X46 and is published with RV-X47.

## The JSON form of a module

The compiler reads a pack written in Reckon through the JSON form of its modules, not through a second parser ([expressions.md §12](../docs/reckon/expressions.md#12-work-packages); RV-C32). `moduleForm(text)` gives that form, `moduleToJson` its bytes, and the command writes them to a file:

```bash
cd reckon && node src/write-form.ts ../examples/zorgtoeslag/facts.rezono facts.json
```

Its shape is the contract [`contracts/reckon-module.yaml`](../contracts/reckon-module.yaml) (`rede.reckon-module/1`), with three members:

| Member | What |
|---|---|
| `format` | `rede.reckon-module/1`. |
| `module` | The tree of the module as `parseModule` reads it: `reckon`, `pack`, `use` and the declarations in the order of the text. The tree is the JSON form, as for a question; an expression is the tree of §4a. |
| `spans` | The place of every node of `module` that has one: its JSON pointer into `module` (`/decls/3/derived/0/value`), its 1-based line and its 0-based offsets in code points, end exclusive. In the order of the canonical JSON of `module`. |

- **The same text gives the same bytes.** The file is canonical JSON (RFC 8785, as the question hash) and nothing after it, not a line end either: members by name, the declarations in the order of the text, every number as decimal text. No clock, no path and no version of this implementation is in it. A text with other line ends is another text: its offsets differ.
- **Print and JSON round-trip.** `printModule` writes a module in its normal form: one statement on a line, two spaces for each block (v0 §2), no blank line and no comment, expressions as in a question (§9). What the tree does not order is written in one order: in a kind `applies`, `sealed`, the slots, the derived values; under a derived value its `unless` lines, its versions, or its table alone; a table with one space inside each `|` and nothing aligned (`| ..<18 | - | none |`); `valid` before `known`; one `unless` clause on the `unless` line, more as `when` lines under it. `parseModule(printModule(m))` is `m`. `moduleFromJson` reads a form back by the one test of `fromJson`: `module` is the tree of its own printed text, and `spans` place the nodes of that tree, each once and in their order. `moduleForm` makes that test on every form before it hands it out, so a form that would not read back is refused, not written.
- **A form or a diagnostic, never a form with a gap.** A form exists only for a module without an error. A text the reader does not read yet is an R000 and a construct that v0 reserves is an R015 (a time selection on a value, `norm`), each at its span; the command prints them with their line, writes no file, removes a file an earlier run left there, and exits with 1. So the contract has no member for a reserved construct, and what the form carries is every declaration `parseModule` reads: `rounding`, `reason`, `unit`, `enum`, `param` with versions, `kind` with `applies`, `sealed` and slots, `extend`, `derived` with `=`, `unless` and versions or with a decision table (and `total` before it), the three check statements, and facts as a table and per row. Which of these the compiler lowers is the compiler's to say, at their span (RV-C33; a table with RV-C36); a warning (W108) is printed and does not stop the form.
- **A decision table is in the form as its tree** (`Table` in the contract; [above](#a-module-read)). The form says what the text wrote and nothing of what was proven: writing a form needs no schema, so the overlap of `unique` rows (R031) and a gap (W112, R024) are not looked for there. They are the check's ([below](#a-decision-table)), and whoever lowers a table proves them again over its own schema (RV-C36).
- **Unknown is never an absent member.** An absent member is something the text did not write (a slot without a cardinality, a module without a `reckon` line). A value in a state is the literal the text wrote, `{"lit": "n/a"}`, `{"lit": "unknown not_measured"}` or `{"lit": "invalid out_of_range"}`, beside `{"lit": "3 GiB"}` for a known one; a fact row has one cell for each column (above), and canonical JSON refuses `null`.
- **An id that is spelled like a name** is a path of one name in a fact cell too (`{"path": ["ann"]}` beside `{"lit": "h-ann"}`), as in a question ([below](#choices-this-slice-makes)): the type of its column decides, which is name resolution and not the parse.
- **Accepted on** `examples/zorgtoeslag`, case Z22: `facts.rezono` has a form (fact tables with `n/a` and `unknown no_cover_report`, fact versions with `valid` and `known`), the same bytes twice, and it reads back; `zorgtoeslag.rezono` has none, because of the R015 of Z20 (its time selection; its two tables no longer stand in the way). Both modules print and read back as the same module. The contract's check validates the form of [`test/module.rezono`](test/module.rezono), a module made up to hold every member, as the fixture [`every-member.yaml`](../contracts/fixtures/reckon-module/ModuleForm/valid/every-member.yaml); `test/module-json.test.ts` holds that file to the bytes this implementation writes.

## A decision table

A derived value by a decision table ([tables.md](../docs/reckon/tables.md), v0.1, decision O14) is read, checked and evaluated (RV-C31). The pack that will use it is `examples/zorgtoeslag` (`threshold_rate`, `grounds`); it is not published yet.

```ts
import { answer, check, declare, tabulate } from './src/index.ts';

const declared = declare('enum Size = small | large\n\nextend Host\n  derived size: Size\n    table unique\n      | memory_need | -> size |\n      | ..<300 GiB | small |\n      | 300 GiB.. | large |\n', schema);
declared.diagnostics; // none here; R031 for rows that overlap, W112 for a gap
declared.schema; // the schema with `Size` and `Host.size` in it
const { data: rows, why } = tabulate(declared, data); // the rows with `size` for every host, and the witness of each
await answer(check('ask Host where size = small', declared.schema), declared.schema, rows);
```

- **The check** (`declare(text, schema)`, `src/table.ts`) reads declarations on top of a schema: an `enum`, and an `extend` whose derived values have a table. Any other declaration is refused at its span (R000), because the check of a module is not built; so the two tables of `zorgtoeslag`, which test other derived values of their module, are read (above) and not checked yet. The header is typed in the scope of the element, each test against its input and each output against the derived value's type, with the codes of tables.md §2 (R001, R003, R005; R012 for a date that is none). A table reads the schema and what stands above it, never itself.
- **The proofs** (tables.md §4) read no row. `unique` rows that one input passes are R031 at the cell of the later row, with an example; rows that leave a gap are W112 at `table <policy>`, with an example, and R024 when the value is `total`. Overlap is shown by this check and never by the order of the rows: the same two rows the other way round overlap too. A proof uses of an input only what every row holds: a path (a slot, a parameter, a derived value above) is a value of its type, and a computed input (`n + 0.5`) is any number, so a proof refuses where it cannot prove and never passes on the name of a type. An output that is no value of the derived value's type is R003. The pieces the proofs range over, and where the text left a choice, are in [tables.md §7](../docs/reckon/tables.md#7-the-build-in-reckon).
- **The value** (`tabulate(declared, data)`, `src/evaluate.ts`) follows tables.md §3. A cell is a condition of Appendix A over its input, evaluated by the evaluator of a question, and a row is the `and` of its cells; `-` is not evaluated at all. So in the four states of an input:

  | The input a row tests is | The row | `unique`, `first`, `priority` | `collect` |
  |---|---|---|---|
  | known | applies or not | the output the policy picks; `unknown no_row_applies` when no row applies | the outputs of the rows that apply; the empty set when none does |
  | `n/a` | does not apply | as above: often no row applies | as above |
  | unknown, with its reason | is undecided | that state, reason and cause, wherever the row's applying would change the value | a member whose membership has that state, reason and cause |
  | invalid | is undecided | the same, as invalid | the same, as invalid |

  Two rows of a `unique` table that both apply give `invalid exception_conflict`; the check refuses such a table, so no declared table reaches it. `no_row_applies` and `exception_conflict` have the row that holds the derived value as cause (`host__size`, the element's key). No policy has a default.
- **The witness** (`why`) names, for each element, the rows that gave the value by their number in the order written, each with the facts its tests read.
- **Fixed order, counted steps.** Tables are decided in the order of the text and elements in the order of the rows handed in; rows of a table and members of a set in the order written. Every expression evaluated counts as a step, as in an answer, and all the tables of one call share `budget.steps`: past it there is no value at all (`OverBudget`). The rows handed in are not changed.
- **Against seam S1.** `test/table.test.ts` holds a row to the `and` table of seam S1 and a cell of several tests to its `or` table, cell for cell, over all 25 pairs of the five values ([`value-cases.yaml`](../docs/semantics/value-cases.yaml), `tables`), under `collect` and under `unique`; and it holds the proofs to the evaluation, with one element in each piece (tables.md §4: "their oracle is the evaluation itself").
- **Not built here:** the lowering of a table in the compiler (RV-C36), the check of a module with its own kinds, a table inside versions, parameter tables and rule tables (tables.md §5).

## The question hash

A question's hash is taken from its normal form (decision Q21), so two ways of writing one question give one hash, and a link to an answer does not depend on how the question was written.
`normalQuestion(checked, pack)` works on the checked question, because whether a bare name is a slot of the row, of an element, a parameter or an id is name resolution (§5), which the check records.
`pack` is the pack's whole schema, not the role's: the definition of a pack is the same for every role (decision O10), so one question asked by two roles that read differently has one hash.
At the gate the role's schema already names every kind and slot of the bundle (`roleSchema`), so it is passed as it is; `outputSchema` and `answer` take `pack` as a last argument, by default the role's schema.
`questionHash(checked, pack)` is the SHA-256 of the canonical JSON of `{"normal": "rede.normal-question/1", "question": <the normal form>}`; the version is part of what is hashed, so a later change of the normal form changes every hash and is never read as the old one.
What is shown stays the question as written: the answer's `expression.text` is `print` of the written tree.

The normal form makes four rewrites, each of which keeps the value and the reason of every row:

- **The binder has a canonical name**: the kind in snake case, the name `ask Host` gives it (§5 rule 1).
  Where that name would be another name at a place the binder is written (a parameter or a slot of a kind in scope there, both of the pack, an id, a value of an enum, a keyword), it is the first of `host_2`, `host_3`, … that is none of them: `ask x: Host where clusters.any(it.spec.memory_per_node >= x.memory_need)` has the binder `host_2`, because `HostCluster` has a slot `host` (§5 rule 7).
  A check statement keeps its binder: the language fixes it.
- **Every path is written in full**: a bare slot of the row from the binder (`memory_need` is `host.memory_need`), a bare slot of the innermost element from `it` (§5 rule 2).
  A slot of an element further out has no other spelling and stays bare, and so does a slot of a check statement's row where its binder's name is a slot in scope.
- **The operands of `and` and `or` are sorted** by the UTF-8 bytes of their canonical JSON.
  Both are commutative in value and in reason (§13 point 7, A.4), and every operand is evaluated, so the steps do not change either.
- **A comparison has one orientation**: `a > b` is `b < a`, `a >= b` is `b <= a`, and the operands of `=` and `!=` are sorted.
  A comparison is strict and orders two values antisymmetrically (A.3), and its result is a truth value, so nothing follows its operands' order.
  This one is beyond the three of Q21; it is in the first version because a later change of the normal form changes every hash.

Nothing else is rewritten: `show` keeps its order (the order of the columns), a literal stays as written (`0.5 TiB` and `512 GiB` hash apart), and `not`, `=>`, `in`, ranges and arithmetic keep their operands' places (the type of `a + b` takes the name of `a`'s type first).
So equal hashes mean one question; two questions that mean the same and differ in anything else hash apart.
A question with an error keeps its names as written, with its operands sorted; the gate hashes only a question that checks.

The normal form is itself a question: it checks, it is its own normal form, and its answer has the rows, undecided rows and counts of the question written.
Its columns need not be in the same order: without a `show`, the columns are the values the condition reads in the order written (§8).
So one hash has one answer's bytes only when the answer is computed from the normal form; until answers are cached by their hash (C07), the gate answers the question as written.

## Choices this slice makes

- **Ohm, not a parser of our own.** The grammar file reads like the EBNF of §4 and is the only place the syntax lives. What the EBNF leaves to the lexer is written out in its header: an id with a hyphen is one token, a number with its unit is one literal, a symbol before a number too, and anything else that starts with a digit is a literal token for the type the context expects.
- **The tree is the JSON form.** So `to_json` is canonical JSON of the tree and `from_json` is one test: a value is the JSON form of a question exactly when it is the tree of its own printed text. There is no second description of the tree to keep in step with the grammar.
- **Three members outside the table of §4a**: `dot` (a slot read from something that is not a name), and `more` and `tail` on an `ask` (the reserved second binders and `order by`, `group by`, `limit`). The last two are always reported as R015, so no hash or answer depends on them.
- **An id spelled like a name** (`cherry`) parses as a one-name path, because the parser cannot tell the two apart; `{"lit": "cherry"}` in the JSON form reads as the same tree. Name resolution decides: a name that is in scope is that name; otherwise it is an id when its context expects a kind (`provider = cherry`), a value of the enum when its context expects an enum (`tier = high`, as `Tier"high"`), and an unknown name (R001) when it does not; a word that is no value of the enum suggests the values it may have meant.
- **The schema is a Reckon Data schema document.** It already says what typing needs (a slot's type or kind, its cardinality, its states and its world; a type's dimension), it is what a pack publishes, and it is the form of the output schema, so a question is checked against the same kind of document that its answer names. Three members go beyond it, because a question can name them and a dataset cannot: `rules` (the binders of each rule and its world), `params` and `symbols` (the symbol a pack writes before an amount, and its currency). A further member, `in_part`, names per kind the slots over a relation the role reads in part or not at all (§7a rule 1): the document shows that only as `world: open` and the state `unknown`, which a slot can have for other reasons. None of them is part of the pack's schema id.
- **The role's view is what is handed in** (§5 rule 8, §7a rule 2). `check` gets the schema of the role that asks, with what the role does not read left out, so it cannot name or suggest it. Building that schema from a role's bundle belongs to the endpoint, which knows what the role reads.
- **A dimension is a vector of exponents** over the base dimensions the schema names (`data`, `time`, a currency), so `€/h * h` is an amount and `GiB + €` is R003, with no unit named in code. Units of one dimension go together; converting them exactly is evaluation's.
- **R003 is the code of every failed type check of an operator**, not only of two dimensions: v0 §10 has no other code for `owner = 3 GiB` or for a call with one argument too few.
- **`a => b` is `not a or b`** (§7), so its left side needs a closed relation as `not` does (R004).
- **W105 follows §13 point 9** (E51 is `open`): a shown expression warns when it reads a value whose slot can be unknown, unless the condition can only be true where that value is known. That is read off Appendix A backwards: a comparison, `in` and arithmetic are decided only over known operands, `x is known` says it outright, `and` adds what its operands guarantee and `or` keeps what all of them do.
- **The states of a shown expression** in the output schema are the states of the slots it reads (§8a), and `invalid` for an expression that divides: a division by zero is invalid (seam S1 §2), with no reason code and no cause, because no row caused it.
- **An inverse set is the relation of its forward slot.** `Host.clusters` is `HostCluster.host` read the other way (Reckon Data §3.4). It is open when it says so itself, when its forward slot is open, or when the kind that carries the forward slot is open, because an element nobody listed may point here; a `closed` written on either slot does not close that, and the world of the kind that owns the inverse slot says nothing (the arbiter on #691). Its members are computed from the forward slot; an inverse slot is never data of its own, so a suppose line that writes one is refused. An element whose forward value is unknown or invalid may name any element: it is a member of every such set, with that state, reason and cause on its membership, so the one relation gives one answer from either end. A forward value that is `n/a` names none; a required one that the row does not give is unknown by its cardinality.
- **Evaluation reads Reckon Data rows.** The schema a question is checked against is a Reckon Data schema document, so the rows are Row JSON of that schema: the role's own form of a publication. A slot a row does not give is read by its cardinality (§7a rule 1): a missing `T` is unknown and a missing `T?` is `n/a`, both without a reason and with the row that would hold the value as cause; a missing set is empty.
- **A relation the role reads in part is open for the role** (§7a rule 1, decision O8; the arbiter on #736, RV-C19). The schema names those slots in `in_part`; whoever hands the schema in knows them from the role's snapshot entries (`full`), so they follow from the read rules and never from a row. A single value missing there is `unknown not_read_in_full`, also for a `T?`, with the row that would hold it as cause: it may be a value the role does not read. That is what the role's Reckon Data form writes for the same absence (Reckon Data §3.3), so rows with those states written out and rows without them give the same bytes, and so do a value the role may not read and a value that is not there (E50). The check adds `unknown` to the states of such a slot and reads a set over it as open (R004), from either end of an inverse slot.
- **Over an open relation "no member found" is unknown, never false** (§7, "Sets and absence"; it was open point 13). `Team.any(true)` without a team, `owner in Team` for an owner that is not listed, and a call of an open rule that has no row are unknown with the reason `open_world`; the rule names the row that would hold it as cause, a set over an open kind has no row to name. So no spelling without `not` turns a missing row of an open relation into a known "not there". The same holds for an element of an open kind that has no row: every slot of it is unknown `open_world`, whatever its cardinality, with the row that would hold the value as cause, and the output schema lists `unknown` for every slot read through an open kind.
- **A filter decides as an `ask` does** (§7, "Sets and absence"; it was open point 14): true is in, false and `n/a` are out. A member whose condition is unknown or invalid stays, with that state on its membership: `count`, `sum`, `min` and `max` over the set then take that state, `any(p)` reads the member as "in and p" and `all(p)` as "in => p", so a member that is known not to match still decides. A count does not reason about bounds: with one membership undecided it is undecided, also where it could not be zero.
- **`count` is strict in its members**, as `sum`, `min` and `max` are (A.3): a member in a state gives the count that state. For a member that is `n/a` that makes the count `n/a` (A.3 as written); seam S1 leaves that case open (`agg-na-member`, §13 point 15).
- **A path through a set keeps every value**: `clusters.spec.nodes.sum()` adds the nodes of every cluster, also of two clusters with one spec. `a in set` is true when a member is `a`; when none is and a member is in a state, it takes that state.
- **`round(x)` rounds to the places of the type of `x`** (its own type, or the pack's first type of its dimension) by the rounding its second argument names, or the pack's one named rounding (`rounding.money` beside `rules` in the schema, v0 §5f). A pack that names none cannot round: `NotEvaluated`.
- **A shown number is written in the normal form of its type** (Reckon Data §3.2): a quantity as the shortest exact decimal in the type's unit, money with the places of its type. A value whose stored integer is not whole is no value of its type (money has exactly the places of its scale, a quantity is a whole number of its storage unit): it is shown as `unknown not_exact`, in that column of that row only, and the row stays (§8a, the arbiter on #696). So every shown amount but a stored value and a rounded one lists `unknown` in the output schema. A quantity that is whole in its storage unit and has no exact decimal in its own unit is written as a fraction of it (`7/3600 h`); a plain number is a ratio as it stands (`1/3`). A factor of a type that is no number above zero is a defect of the schema and is refused.

## Conformance

The cases are data in [docs/reckon/cases](../docs/reckon/cases) (E01 to E64, P01 to P07 and T01 to T07). `test/conformance.test.ts` runs every one of them against this implementation, with the fixture schema of §2 as [`test/fixture.schema.json`](test/fixture.schema.json), and asserts each key of `expect` that the implementation can produce. What it cannot produce yet is listed per case in [`test/not-yet.json`](test/not-yet.json), and that list is asserted too: a key that starts to be asserted must leave the list in the same change, and nothing can join it unnoticed. So the file says, case by case, how far the implementation is, and it can only shrink. A case that lists no diagnostics is a valid question, so the runner also asserts that the check finds no error in it.

| | Cases |
|---|---|
| Every key asserted | 77 |
| Pending in the specification itself (E53) | 1 |

The evaluation cases (E41 to E50, E56 to E62 and E64) and the publication cases (P01 to P07) run over the rows of Appendix B ([`test/appendix-b.json`](test/appendix-b.json)), each `given` line applied as a suppose line and what a case hides taken out of the role's view. The cases of a decision table (T01 to T07, [tables.md §6](../docs/reckon/tables.md#6-conformance-cases)) declare an enum and a table on top of the fixture: an evaluation case in `declare`, checked with `declare`, its table decided over the role's view with `tabulate` before its question is answered; a check-only case as its `source`. Their expected outcomes are the hand-written ones of the case files. A case that says which slots its role reads in part (`reads_in_part`, E50) is checked and answered against the fixture with those slots open and named in `in_part`. A two-world case compares the bytes of everything a client can get of the answer in each world: the dataset, the counts, and every page with its cursor (E49 pages by one).

An `open` case must give its `expect` or one of its `alternatives`; `not-yet.json` records which reading the implementation follows once what is asserted tells the readings apart (E36: two R015s, the reading of §1; E51: W105 at `owner`, the proposal of §13 point 9; P07: a `check` that Appendix A makes true for an element with an invalid operand publishes, so the check alone does not see that contradiction).

`test/parse.test.ts` covers what the cases do not show of the syntax: every operator's place in the precedence, where parentheses are needed, the tokens, spans after a character outside the basic plane, the JSON form refusing what is not a tree, and 400 generated trees with a fixed seed that print, parse and print again to the same text and tree. `test/check.test.ts` does the same for names and types: every code with its span, a role that reads less (R001 never names what it does not read), when W105 fires, the default `show`, and the output schema as a document. `test/evaluate.test.ts` does it for answers: the tables of Appendix A against seam S1's data, the reasons of A.4, exact units and `round`, aggregates, filters and `in`, open relations, inverse sets from either end, an element without a row, missing values, a value missing from a relation the role reads in part, suppose lines, the rows as Row JSON with the amounts a type cannot hold, and pages. `test/normal.test.ts` covers the question hash: the normal form, equal questions written differently, questions that hash apart, one hash for two roles that read differently, the version, the output schema's `base`, and 684 variants generated with a fixed seed from 50 questions (every `ask` and check statement of the cases that checks against the fixture, and a few more), each of which has the hash of its question and, over Appendix B, its rows, undecided rows and counts. `test/module.test.ts` covers the reader of a module, `test/module-json.test.ts` its normal form, its JSON form and the command, and `test/examples.test.ts` runs both over every example written in Reckon. `test/table.test.ts` covers the decision table: every code of its check with its span, the two proofs, the value in each of the four states of an input for each hit policy, the witness and the budget ([above](#a-decision-table)).

```bash
cd reckon && npm ci && npm test
```

## At the gate

[`edge/gate/src/expr.ts`](../edge/gate/src/expr.ts) answers an `ask` for one role (G7, part 1 of 3: no route yet). It has no store access of its own: the route hands it the pack's bundle, the role's snapshot entries and a reader of one relation by key range.

- **The role's schema** (`roleSchema`) follows the role's Reckon Data form, rule for rule ([`probes/reckon-data-thin/export.py`](../probes/reckon-data-thin/export.py), `schema_document`): a kind per kind of the bundle, a slot per attribute and arrow, a derived relation as a kind with its columns as text. The test pins the schema ids that the Python gives for the same bundle, so the pack schema an answer names (`imports.p.schema`) is the schema of that form. A relation the role does not read in full is open, and a single value missing from it is `unknown not_read_in_full`, whatever the slot's cardinality (O8): it may be a value the role does not read. `rowsOf` writes that state out, as the form does, and `roleSchema` names the slot in `in_part`, so the evaluation reads the absence the same way. A subkind and an attribute type that form does not map (a boolean) are refused with 501: no question is answered over a schema that leaves a part out. The bundle has no units, no parameters and no kinds on rule variables, so a question over a published pack has no quantities and calls no rule yet.
- **The rows** (`rowsOf`) are read whole, relation by relation, a page of the reader at a time, and only for the kinds and slots the question names (`wanted`: more than the evaluation reads, never less; a test compares with the answer over every row). Every row read counts against a budget; a question that passes it is cut and gives no row and no count.
- **The answer** (`ask`) is one page as `rede.answer/1`: `nodes` (the binder row of each answer row), `output_schema`, `counts`, `undecided` and `next` as [`contracts/explain.yaml`](../contracts/explain.yaml) has them, and beside them what the contract does not hold yet: `expression` (the hash of the question's normal form, [above](#the-question-hash), and its text as written, printed as §9 prints it), `diagnostics` (the warnings) and `dataset` (the page as Row JSON of the output schema, with the shown values). A text that does not check is refused with its diagnostics and reads no row. Every page is computed from the whole answer, so a page costs what the answer costs.
- **Two budgets, one cut** (the arbiter on #736, points 3, 4 and 8). Rows read bound the reading and steps bound the work: a set searched for every row costs rows times members without one row more read. `ask` takes both and answers `{cut: {budget: "rows" | "steps", limit}}` when one is passed: no row and no count. Both count only what the role's reader gave, so two publications whose role views are equal are cut alike. The evaluation is told which kinds and slots were read for it and refuses any other (500), so a slot that `wanted` misses can never read as absent. And the rows are those of the role's Reckon Data form, value for value: an integer with both bounds as a JSON number, a set without a member as `[]`, every missing value as its state; the test pins their hash, and the schema ids, against the Python ([`edge/gate/test/expr.form.py`](../edge/gate/test/expr.form.py)).

Not built here: the routes (the gate lane writes them after the arbiter's ruling on their shape), the witness of each row (`$why`), the dataset hash (the reference `reckon_data.hash` does not hash values of an imported type, and every answer has them), and `given` lines at the endpoint. No published pack uses it yet. The gate's own test job does not install the packages of `reckon/` and skips `edge/gate/test/expr.test.ts`; the workflow `reckon` runs it.

## Next

The routes of the endpoint, the witness of each row (`$why`) and the dataset hash; the other value tables of v0.1 (parameter tables and rule tables, decision O14), each with its text first; the declarations a module does not read yet, and the check of a module, as a pack written in Reckon needs them: with it the tables of a module are checked against its own kinds. The compiler reads the JSON form of a module with RV-C33, and lowers a decision table with RV-C36.

Not read yet, so refused with R000: an id between backticks without its kind in front (with the kind in front it is read), and a literal token that is one symbol. Not typed in full yet: date arithmetic and periods (v0 §5f): a date moved by a number is a date whatever the unit of the number, and what two dates give passes unexamined; evaluation refuses both (`NotEvaluated`). Not typed yet: the operands of the reserved contexts and time selections (R019 comes with their evaluation).
