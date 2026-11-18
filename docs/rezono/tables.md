# Rezono v0.1 decision tables

This page specifies a decision table on a derived value. The four hit policies are defined in [§3](#3-meaning). The compiler's publication subset is described in [lowering a unique table](publication.md#91-a-decision-table-under-unique).

## 1. What a decision table is

A decision table gives a derived value of an element by rows: each row tests some inputs and names one output. It is the declarative form of a `when … then … else` chain whose overlaps and gaps the compiler can see.

```rezono
enum Size = small | medium | large

extend Host
  derived size: Size
    table unique
      | memory_need       | -> size |
      | ..<300 GiB        | small   |
      | 300 GiB..<500 GiB | medium  |
      | 500 GiB..         | large   |
```

## 2. Grammar

The core grammar is v0 §11 (`derived … NEWLINE INDENT dtable DEDENT`). This text fixes what that leaves open:

```ebnf
dtable  = "table" policy NEWLINE INDENT header { trow } DEDENT ;
policy  = "unique" | "first" | "priority" | "collect" ;
header  = "|" expr { "|" expr } "|" "->" name "|" NEWLINE ;
trow    = "|" cell { "|" cell } "|" value "|" NEWLINE ;
cell    = "-" | test { "," test } ;
test    = value | value ( ".." | "..<" ) [ value ] | ( ".." | "..<" ) value ;
value   = literal | literal_tok | name ;       (* a literal, an id or an enum value as a bare word *)
```

- **The header.** Each input is an expression in the scope of the element, as the derived value's own `= expr` would be: `memory_need` is the element's slot, `spec.memory` a path from it. The name after `->` is the derived value's own name; another name is R001. Every row has exactly as many cells as the header has inputs (R000 otherwise).
- **A cell** is `-` (no test) or one or more tests separated by commas (alternatives).
- **A test** is a value (equality), or a range: `a..b` (both ends in), `a..<b` (upper end out), `a..`, `..b`, `..<b`. A value is read by the type of its input, as the right side of `=` is (expressions.md §3, §6): `300`, `€ 50.00`, `host-a`, an enum value as a bare word.
- **The output** of a row is one value of the derived value's type, read the same way. A state is not an output: a row that should give no value is left out, and the policy says what no applying row means.
- **Typing.** A test's value must go with its input's type (R003). A range needs an ordered type: a number with or without a dimension, a date (R003 otherwise). `priority` needs an enum as output type (R003). `collect` needs a set (`T*`); the other three a single value (R005).

**The JSON form**, as the tree is the JSON form ([expressions.md §4a](expressions.md#4a-the-json-form-of-a-question); `rezono/README.md`, check statements): a table is `{"table": "unique", "inputs": [e, …], "output": "size", "rows": [row, …]}`; a row is `{"tests": [cell, …], "value": v}`; a cell is `"-"` or a non-empty list of tests; a test is a value `{"lit": "18"}` or `{"between": {"from": a, "op": "..", "to": b}}` with `from` or `to` absent for an open end. The printed form puts one space inside each `|` and aligns nothing: `| ..<300 GiB | small |`.

## 3. Meaning

For one element, each cell is a condition, and each row is the `and` of its cells, by Appendix A (expressions.md):

| Cell | Its condition |
|---|---|
| `-` | `true`, whatever the input and its state |
| `v` | `input = v` |
| `a..b`, `a..<b`, `a..`, `..b`, `..<b` | `input in a..b` and so on |
| `t1, t2` | `t1 or t2` |

So a test on an input that is `n/a` is `n/a`, and one on an input that is unknown or invalid takes that state, with its reason and cause (A.3, A.4). A row **applies** when its condition is true; it **does not apply** when it is false or `n/a` (the decision point of v0 §7b: "table row"); it is **undecided** when it is unknown or invalid. An undecided row could apply: wherever its applying would change the value, the value takes its state.

| Policy | The value |
|---|---|
| `unique` | One row applies: its output. None applies and none is undecided: `unknown no_row_applies`. None applies and some are undecided: the highest state among those rows, with the reason and cause A.4 gives. Two rows apply: `invalid exception_conflict` (the compiler proves this cannot happen, §4). |
| `first` | Let `r` be the first row that applies. The undecided rows before `r` whose output differs from `r`'s output change the value if they apply: if there are any, the highest state among them; else `r`'s output. No row applies: the highest state among the undecided rows, else `unknown no_row_applies`. |
| `priority` | Let `o` be the output that comes first in the output enum's order among the rows that apply. The undecided rows whose output comes before `o` change the value: if there are any, the highest state among them; else `o`. No row applies: as for `first`. |
| `collect` | A set: the output of each row that applies, as a known member, and the output of each undecided row that no applying row already gives, as a member whose membership is undecided, with that row's state, reason and cause (expressions.md §7, "Sets": as a member of a filter whose condition is undecided). No row applies and none is undecided: the empty set, known. |

- **Reasons and causes.** `no_row_applies` and `exception_conflict` have as cause the row that holds the derived value (`<kind>__<slot>`, the element's key). A state taken from undecided rows keeps the reason and cause A.4 gives among them.
- **The witness** of a value names the row of the table that gave it, and the facts its tests read; for `collect`, each member names its row.
- **Order.** Rows are in the order written; `first` reads them in that order, and so does the printer. The other policies do not depend on it.

## 4. What the compiler proves

Column by column over the input types, without data:

- **`unique` rows are disjoint.** Two rows are disjoint when there is a column in which both have a test and no value passes both. A pair that is not disjoint is **R031**, at the cell of the later row in the first column where the two overlap, with an example input that both rows take (T06).
- **The rows cover the inputs** (all policies but `collect`). The values of each column split into the pieces the tests mark: the values of an enum, the intervals between the range ends of an ordered type, each listed value and "any other" for another type. A combination of pieces that no row takes is a gap: **W112** at `table <policy>`, with an example input (T07); **R024** if the value is `total` (v0 §5d).
- **No other proof.** A cell over an input that can be unknown leaves the row undecided at run time (§3); that is not a gap.

These proofs are a finite check over the pieces, not a heuristic. A proof uses of an input only what every row holds: the type of a value that is stored (a slot, a parameter, a derived value above) and the states the input can take. Over stored values the proofs are exact. A computed input (`n + 0.5`, `price * rate`) is any number of its dimension, whatever type it is named after: over it a proof may name an overlap or a gap that the arithmetic never gives, and it never misses one. Their oracle is the evaluation itself, over a fixed grid of elements: each end a table tests, a value on each side of it, a value between two neighbouring ends where the input has one, and each state. No element has two rows of a table that passed R031; none is without a row where W112 named no gap; a `total` value is known for every one (a test per table form; for this one `rezono/test/table.test.ts`).

## 5. What is not in this form

This declaration computes a derived value. Tables per parameter key and validity period, and fact tables that a fixed rule reads, are separate forms. A table inside a version also needs version-aware reading. See [the language reference](v0.md) for validity and applicability and the [native rule design](../../decisions/language-native-rules.md) for authored rules.

## 6. Conformance cases

T01 to T07 in [`cases/`](cases/) are `settled` and run with the other cases (`rezono/test/conformance.test.ts`). Each evaluation case declares an enum and a table on `Host` of the fixture schema (expressions.md §2) and asks over the data of Appendix B; the two check-only cases give the diagnostics of §4. The table of all cases, with these, is in [expressions.md §11](expressions.md#11-conformance-cases).

| Case | Shows |
|---|---|
| T01 | `unique`: one row per known input; an unknown input leaves every row undecided, so the value takes its state |
| T02 | no row applies: `unknown no_row_applies` |
| T03 | `first`: a test on an `n/a` input does not apply; `-` takes any value in any state; an undecided earlier row with another output makes the value undecided |
| T04 | `priority`: the enum's order; an undecided row whose output comes later cannot change the value |
| T05 | `collect`: members from applying rows, undecided members from undecided rows, the empty set when none applies |
| T06 | R031: two `unique` rows overlap |
| T07 | W112: the rows leave a gap |

## 7. The build in `rezono/`

The [reader and evaluator](../../rezono/README.md#a-decision-table) put a table in the tree of §2, check it against a schema with the proofs of §4, and compute its value and witness by §3. The reader, checker and evaluator use these conventions:

1. **A value is `{"lit": …}`, also a bare word,** and it is never a name in scope: `| n |` under an input is the word `n`, not the slot. A state is no value in a test either (R000): `input = n/a` is never true (Appendix A), so the row would never apply. A keyword is a bare word in a value too: an enum of the schema may have the value `valid` or `open`, which v0 §3 makes no name, and a cell is where it is written. `true` and `false` stay the literals of Bool, and a keyword that is no value of the input's type is R001 as another word is.
2. **`a..<` without an upper end** is allowed by the EBNF and not listed in the prose. It reads as `a..`; the tree keeps the operator written.
3. **`total`** (v0 §5d) is read before `derived` on a value with a table, as `"totality": "total"`, so that R024 can be given; on any other value it stays R000, because nothing proves it there. A `total` table gets R024 for a gap (in place of W112) and R024 at each input its rows test that can be `n/a`, unknown or invalid: the value is then not known in every case. An input that reads an open relation (`any`, `in`, a rule) can be unknown whatever states its slots list: "none found" is unknown there (expressions.md §6).
4. **The pieces of a column.** A Bool has two values, as a closed enum has its values. A type that holds whole numbers of a step (an integer, a quantity in its storage unit, money at its scale, a date in days) has no value between two neighbours, so `..17` and `18..` leave no gap. That holds for an input that is a path only: a slot or a parameter is stored as a value of its type, and so is a derived value above. That is the premise of both proofs, for every type: a row outside the admitted type (`1.5` in an integer slot, a word outside a closed enum) is outside them, and `load` does not refuse it. Every other input computes and is held to no step, whatever type it is named after: `n + 0.5`, `n / 2` and `n * 2` alike are any number, and `..17` and `18..` leave the gap `> 17 and < 18` there. So that a derived value is a value of its type (§2), an output of the type's dimension that is none of its values is R003 (`1.5` for an integer, `€ 1.005` at scale 2), and a date that is no day of the calendar R012, as in a test. A number that has no value (`1/0`) is R012, in a test and as an output. A slot's `min` and `max` are not read: the proof is over the type. A range over a moment (`DateTime`) or a text is R003, as §2 names a number and a date only; a date in a test that is no day of the calendar is R012.
5. **Where R031 stands.** In a pair that overlaps, the two rows share a value in every column, so "the first column where the two overlap" is read as the first column in which both rows test; without one (each row tests where the other has `-`) it is the later row. A cell that no value passes (`5..3`) overlaps nothing.
6. **An example is a condition over the pieces,** not one invented value: `memory_need < 300 GiB`, `n > 16 and n < 18`, `label != "blue"`; `true` when no column is tested.
7. **What `declare` takes.** A schema, and declarations on top of it: an `enum`, and an `extend` whose derived values have a table. Every other declaration is refused at its span (R000) until the check of a module lands. A table reads the schema and the derived values above it; itself or a value below it is an unknown name (R001), so no table reads its own value.
8. **`it` in a header** is the element, as inside a filter: the header is written in the scope of the element (§2).
9. **The states of the value** in the schema follow from §3: `unknown` when the rows leave a gap or an input they test can be `n/a` or unknown (point 3), `invalid` when one can be invalid; for `collect` the same without the gap, since the empty set is a value.
10. **`collect`.** The set has one member for each output; its members stand in the order of the rows that give them. An output that only undecided rows give is one member, whose membership has the highest state among those rows (Appendix A.4).
11. **The witness** names rows by their number in the order written, from 1, each with the facts its tests read (a slot of an element, a parameter, a row of a rule; `-` reads nothing). For a known value that is the row whose output it is (under `priority` the first such row); for `collect` every row that gives a member; for a state taken from undecided rows those rows; for `exception_conflict` the rows that apply; for `no_row_applies` none.
12. **Evaluation fills the rows.** `tabulate` decides every table for every element of its kind, in the order of the text, over the rows a role reads, and hands the rows back with the values in them: a question then reads a derived value as it would any other slot. Every expression evaluated counts as a step against one budget, as in an answer.
