---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: language-contextual-keywords
---

# Contextual keywords and unrestricted member names after `.`

`rezono/src/rule-names.ts` currently reserves 56 words globally as hard keywords, and `rezono/src/grammar.ts` restricts member access (`Dotted_name = Dotted "." name`) to non-keyword names. As a result, ordinary domain slot names such as `shelf.open`, `item.version`, `entry.known`, and `claim.valid` fail to parse without backticks — including `require active: shelf.open is known` in [checks and conditional requirements](language-checks.md). At the same time, `rezono/src/syntax-grammar.ts` sweeps every `kw<"...">` terminal from the Ohm module grammar into a global `keyword.control.rezono` rule, highlighting ordinary slot and identifier names such as `x.value`, `x.type`, `x.range`, `shelf.open`, and `item.version` as control keywords.

This decision narrows hard keywords to the true expression keywords, makes declaration and clause keywords contextual, allows any identifier word after `.`, and aligns the generated TextMate syntax grammar with those rules.

## 1. Unrestricted member names after `.`

Introduce a lexical token rule for any lowercase identifier word without keyword exclusion:

```ohm
identWord (a member name) = az (az | d | "_")* ~wordChar ~("-" wordChar)
```

In `rezono/src/grammar.ts`:

- `Dotted` becomes:
  ```ohm
  Dotted = Dotted "." where "(" Expr ")"  -- where
         | Dotted "." Agg                 -- agg
         | Dotted "." identWord           -- name
         | Atom
  ```
  Because `Dotted_where` (requiring `(` after `where`) and `Dotted_agg` (requiring `(` after an aggregate name) precede `Dotted_name`, method filters (`.where(pred)`) and aggregate calls (`.count()`, `.sum(...)`, `.min(...)`, `.max(...)`, `.any(...)`, `.all(...)`, `.none(...)`, `.one()`) keep their meaning while every bare member segment after `.` — including contextual keywords (`shelf.open`, `item.version`, `entry.known`, `claim.valid`, `x.value`, `x.type`, `x.range`) and hard expression keywords (`x.where`, `x.at`, `x.and`, `x.in`) — parses cleanly without backticks.
- `SupposePath` uses `rowId ("." identWord)+` and `SupposeSlot` uses `identWord "=" Expr`, so suppose statements (`+ shelf-1.open = true`, `- shelf-1.open`, `+ Shelf shelf-1 { open = true }`) and example `given` lines follow the same rule.
- `NativeRules` extends `Dotted_name` to `Dotted "." (identWord | quotedName)` so existing backticked member names remain readable while unquoted member names are preferred.
- In `rezono/src/print-expression.ts`, path segments after the leading segment (`path[1..]`) and `dot[1]` print bare without backticks (`shelf.open`, `item.version`, `entry.known`, `claim.valid`, `x.where`, `x.at`). Round-tripping through `print`, `parse`, `toJson`, and `fromJson` stays lossless and idempotent.
- `check` in `rezono/src/check.ts` resolves dotted member names directly against the target kind's declared slots, so `require active: shelf.open is known` parses and typechecks cleanly with no diagnostics when `Shelf` declares slot `open`.

## 2. Hard expression keywords vs. contextual keywords

### Hard expression keywords (15)

`keywords` in `rezono/src/rule-names.ts` is restricted to the exact **15** expression keywords that participate directly in expression syntax or delimit expressions in questions and conditional clauses:

| Group | Hard keywords | Role |
|---|---|---|
| Boolean literals (2) | `true`, `false` | `Bool` literals in `Atom` |
| Conditional & exception control flow (4) | `when`, `then`, `else`, `unless` | `when Expr then Expr else Expr`, `unless Expr then Expr`, `version N replaces M unless Expr` |
| Logical operators (3) | `not`, `and`, `or` | Prefix and infix boolean connectives |
| Relational & state operators (2) | `in`, `is` | Membership/range test (`Range in Range`), state test (`Range is state`), and `in` context |
| Filter, time selection & `ask` delimiters (4) | `where`, `show`, `at`, `as` | Postfix `where Expr`, `at Atom`, `as known Atom`, `ask ... where Expr show ...`, `use ... as ...` |

These 15 words remain reserved as bare identifiers in primary expression position and in bare declaration/schema names (`ask Shelf where where > 1`, `ask Shelf where and = true`, `schema where` fail with `R000`). Where a grammar rule accepts `rName` (such as a schema name, slot declaration, or rule name), a hard keyword may still be written in backticks (for example `` schema `where` `` or `` `at`: Date ``), and `spellName` in `rezono/src/rule-names.ts` quotes only these 15 hard keywords (plus aggregate names in call-member position).

### Contextual state words

As in [expressions and questions](../docs/rezono/expressions.md#3-tokens), `unknown` and `invalid` remain contextual state words (recognized after `is` and as state-literal prefixes before a reason code or text, never in `keywords`), and `n/a` contains `/` so it is never an identifier word. `known` leaves `keywords` and joins `unknown` and `invalid` as a contextual state and clause word (`is known`, `as known`, `known <date>`).

### Contextual declaration and clause keywords (41)

The remaining **41** words previously listed in `rezono/src/rule-names.ts` become contextual:

- **Module and declaration headers:** `rezono`, `pack`, `use`, `private`, `unit`, `enum`, `param`, `kind`, `extend`, `derived`, `rule`, `check`, `warn`, `require`, `norm`, `fact`, `decide`, `assume`, `theory`, `view`, `example`, `exception`, `deprecated`
- **Question and command starters:** `ask`, `suppose`, `propose`
- **Declaration and clause modifiers:** `version`, `valid`, `known`, `world`, `open`, `closed`, `inverse`, `applies`, `replaces`, `requires`, `sources`, `because`, `until`, `by`, `on`

Together with the existing contextual words of [the v0 reference](../docs/rezono/v0.md#3-tokens) (`during`, `order`, `group`, `limit`, `overrides`, `means`, `table`, `unique`, `first`, `priority`, `collect`, `total`, `value`, `type`, `range`, `default`, `schema`, `over`, `step`, `effect`, etc.), these words:

1. remain recognized in their declaration-header and clause positions via `kw<"word">` (for example `kind Shelf world closed`, `enum Status = open | closed`, `param version: Int = 1`, `version 1, valid 2026-01-01.., known 2025-12-01 = 1`, `require active: shelf.open is known`);
2. parse cleanly as ordinary `name` identifiers without backticks outside those positions — as slot names (`open: Bool`, `closed: Bool`, `version: Int`, `valid: Date`, `known: Bool`, `world: Text`, `view: Text`, `sources: Text*`, `param: Text`, `unit: Text`, `enum: Text`, `kind: Text`), bare slot references inside expressions (`ask Shelf where open and not closed and version >= 1 and valid is known`), parameter names (`param version: Int = 1`), fact slot assignments (`open = true`), and schema names (`schema example`).

To keep literals unambiguous before trailing clause keywords, `unitWord` and `reasonCode` in `rezono/src/grammar.ts` continue to exclude both the 15 hard keywords and the clause-following contextual words (`during`, `order`, `group`, `limit`, `overrides`, `means`, `because`, `until`, `on`, `within`, `by`, `replaces`, `unknown`, `invalid`). Thus `ask Shelf where version > 3 limit 5` continues to read `3` as a number followed by `limit 5`, not as a quantity `3 limit`.

### Compatibility across language versions

This relaxation applies to both `rezono 0` and `rezono 1`. It is strictly permissive on valid programs: every previously valid module, question, and check statement retains the same parse tree and semantics, while previously rejected bare contextual names and unquoted dotted member names now parse cleanly.

This revises the fixed-56-keyword assumption in [schema identity and metadata](language-metadata.md#a-keyword-as-a-schema-name): `example` is now a contextual declaration keyword, so `schema example` parses without backticks, while backticked schema names continue to work for the 15 hard keywords (such as `` schema `where` ``).

## 3. Context-aware TextMate syntax highlighting

`rezono/src/syntax-grammar.ts` must reflect the split between member names, hard expression keywords, and contextual declaration keywords:

1. **Member access after `.` takes precedence over keywords and constants.** Add a member-access pattern before `#constants`, `#aggregates`, `#keywords`, and `#operators`, and guard global keyword/constant patterns against a preceding `.` (`(?<!\.)`). Method filters (`.where(`) and aggregate calls (`.count(`, `.sum(`, `.min(`, `.max(`, `.any(`, `.all(`, `.none(`, `.one(`) keep their method/aggregate scopes; every other `.identWord` (including `shelf.open`, `item.version`, `entry.known`, `claim.valid`, `x.value`, `x.type`, `x.range`, `x.where`, `x.and`) highlights `.` as `punctuation.separator.rezono` and the slot name as `variable.other.member.rezono` — never as `keyword.control*`, `keyword.operator.*`, or `constant.language.*`.
2. **Global `#keywords` contains only the 15 hard expression keywords.** Stop collecting every `kw<"...">` terminal from module rules into global `keyword.control.rezono`. Globally:
   - `keyword.operator.logical.rezono`: `not`, `and`, `or`
   - `keyword.operator.word.rezono`: `in`, `is`, `at`, `as`
   - `keyword.control.rezono`: `when`, `then`, `else`, `unless`, `where`, `show`
   - `constant.language.boolean.rezono`: `true`, `false`
3. **Contextual declaration and clause words are highlighted only in declaration/clause positions.** Declaration-header keywords (such as `rezono`, `pack`, `use`, `schema`, `unit`, `enum`, `param`, `kind`, `extend`, `derived`, `rule`, `step`, `effect`, `check`, `warn`, `require`, `norm`, `fact`, `dataset`, `source`, `example`, `version`, `table`, `reason`, `rounding`, `deprecated`, `private`, `total`, `abstract`, `embedded`, `relationship`, `type`, `ask`, `suppose`, `propose`, `decide`, `assume`, `theory`, `view`, `exception`, `definition`, `applies`, `sealed`, `unique`, `equal`, `given`, `expect`, `violation`, `confirm`, `forbid`, `over`, `means`, `output`) match only at declaration-header positions (anchored to line start `^[ \t]*` and followed by header syntax rather than `:` or `=` or `.`). Contextual state words (`known`, `unknown`, `invalid`, `n/a`) match as `constant.language.state.rezono` only in state-test or state-literal contexts (after `is` or `as`, or as a state literal) and never after `.` or as bare identifiers. In particular, contextual words such as `open`, `closed`, `world`, `version`, `valid`, `known`, `value`, `type`, `range`, `view`, `sources`, `kind`, `enum`, `unit`, and `param` must never receive `keyword.control*` in expression position or after `.`.

## Tests

| Test | Mark | What it holds |
|---|---|---|
| `rezono/test/test_contextual_keywords.py::test_dotted_member_names_parse_and_typecheck_without_backticks` | `M3` | `require active: shelf.open is known`, `item.version`, `entry.known`, `claim.valid`, `x.value`, `x.type`, `x.range`, hard-keyword member segments (`x.where`, `x.at`), and dotted `suppose` paths parse, print without backticks, round-trip through JSON, and typecheck cleanly while `.where(...)` and `.count()` keep their method/aggregate trees. |
| `rezono/test/test_contextual_keywords.py::test_contextual_declaration_keywords_work_as_identifiers_while_expression_keywords_stay_reserved` | `M3` | `rule-names.ts` exports the exact 15 hard expression keywords; contextual declaration words (`open`, `closed`, `version`, `valid`, `known`, `world`, `view`, `sources`, `param`, `unit`, `enum`, `kind`, `example`) work bare as slot names, expressions, parameter names, and schema names; hard expression keywords remain refused with `R000` when used bare; trailing clause words after numbers (`3 limit 5`) are not read as units. |
| `rezono/test/test_contextual_keywords.py::test_syntax_grammar_does_not_color_dotted_slots_or_contextual_words_as_control_keywords` | `M3` | The TextMate grammar generated by `rezono/src/syntax-grammar.ts` never assigns `keyword.control*` (or operator/state scopes) to slot names after `.` (`shelf.open`, `item.version`, `entry.known`, `claim.valid`, `x.value`, `x.type`, `x.range`, `x.where`, `x.and`) or to contextual declaration words in expression or slot-declaration position, while still scoping hard expression keywords and line-start declaration headers. |
| `rezono/test/test_schema_keyword_name.py::test_schema_keyword_name` | green guard | Updated from `example` (now contextual) to the hard expression keyword `where`, so backticked schema names continue to be tested against a reserved keyword before and after this change. |

## Considered

- **Keep all 56 words globally reserved and require backticks for slots like `shelf.\`open\`` and `item.\`version\``.** Rejected: it breaks natural domain modelling (including the check example in `decisions/language-checks.md`) and turns routine business terms (`open`, `closed`, `version`, `valid`, `known`, `sources`, `view`, `unit`, `kind`) into syntax errors.
- **Make every keyword contextual, including `and`, `or`, `when`, `where`, and `is`.** Rejected: expression operators and delimiters directly determine precedence and expression boundaries (`a where b`, `when a then b else c`, `unknown show`), so keeping the 15 expression keywords hard avoids fragile backtracking and ambiguous error diagnostics while allowing them after `.`.
- **Gate contextual keywords on `rezono 1` only.** Rejected: standalone questions and `check`/`require` statements carry no `rezono` version header, and `require active: shelf.open is known` must work uniformly without splitting the expression lexer into two incompatible dialects.
