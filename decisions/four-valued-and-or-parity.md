---
decider: [core]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: four-valued-logic-parity
---

# Enforce one four-valued `and`/`or` truth table and commutative reason choice across every engine

The normative expression specification ([`docs/rezono/expressions.md`](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) Appendix A.1 and A.4), the settled conformance decisions ([`decisions/conformance-value-tt-and-false-invalid.md`](conformance-value-tt-and-false-invalid.md), [`decisions/conformance-value-tt-or-true-invalid.md`](conformance-value-tt-or-true-invalid.md), and [`decisions/conformance-value-reason-tie.md`](conformance-value-reason-tie.md)), and the TypeScript evaluator (`rezono/src/evaluate.ts`) already agree on one four-valued semantics: `false and invalid = false`, `true or invalid = true`, and every multi-operand state tie picks the least reason in UTF-8 byte order.

However, the calculation SQL generator (`compiler/rezono_compiler/calc_sql.py`, which emits both DuckDB and Feldera SQL), the independent calculation checker (`checker/rezono_checker/calc.py`), and the calculation test oracle (`compiler/tests/calcoracle.py`) still let `invalid` override a decisive `false` in `and` or `true` in `or`, and still select the positional first operand's reason on a state tie. Because `compiler/rezono_compiler/rezono_calc.py` lowers Rezono `and`/`or` expressions directly into `rezono.calc/1`, the compiled engines and the checker diverge from the language evaluator and from the settled conformance decisions.

This decision mandates exact cross-engine parity for `calc_sql.py` (DuckDB and Feldera), `rezono_calc.py`, `checker/rezono_checker/calc.py`, `compiler/tests/calcoracle.py`, and `rezono.rules/2` ([`decisions/language-rezono-1.md`](language-rezono-1.md)), and makes the two shared conformance cases executable across compiler, checker, and Feldera.

## 1. Normative truth table (`and` and `or`)

Every engine that evaluates four-valued Boolean expressions — `rezono/src/evaluate.ts`, `compiler/rezono_compiler/calc_sql.py` (DuckDB and Feldera SQL), `compiler/rezono_compiler/rezono_calc.py`, `checker/rezono_checker/calc.py`, `compiler/tests/calcoracle.py`, and `rezono.rules/2` (DuckDB, Feldera, the Soufflé oracle, and `checker/rezono_checker/`) — MUST follow Appendix A.1 of [`docs/rezono/expressions.md`](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) for any arity ≥ 2:

- **`and`:**
  1. If any operand is `known(false)`, the result is `known(false)` with empty reason `""`, even when another operand is `invalid`, `unknown`, or `not_applicable`.
  2. Otherwise, if any operand is non-`known`, the result has the highest severity state (`invalid` > `unknown` > `not_applicable`) with the reason selected by Section 2.
  3. Otherwise (every operand is `known(true)`), the result is `known(true)` with empty reason `""`.
- **`or`:**
  1. If any operand is `known(true)`, the result is `known(true)` with empty reason `""`, even when another operand is `invalid`, `unknown`, or `not_applicable`.
  2. Otherwise, if any operand is non-`known`, the result has the highest severity state (`invalid` > `unknown` > `not_applicable`) with the reason selected by Section 2.
  3. Otherwise (every operand is `known(false)`), the result is `known(false)` with empty reason `""`.

Controls remain unchanged: `true and invalid = invalid`, `invalid and true = invalid`, `false or invalid = invalid`, and `invalid or false = invalid`. Both operators are strictly commutative in value, state, and reason.

## 2. Commutative UTF-8 least reason selection (Appendix A.4)

Whenever `and`, `or`, or any strict operator (`add`, `sub`, `min`, `max`, `ratio`, `pow`, `eq`, `lt`, `lte`, `gte`, and functional-expression operators in `rezono.rules/2`) yields a non-`known` state (`not_applicable`, `unknown`, or `invalid`) and more than one operand carries that winning state, every engine MUST choose the **least reason text in UTF-8 byte order** among the operands in that winning state:

- State precedence (`invalid` > `unknown` > `not_applicable`) is always decided before reason order. A lower-severity operand with a smaller reason never overrides a higher-severity operand.
- Within the winning state, comparison is strict UTF-8 byte order (for example `"B_code" < "a_code"` and `"division by zero in ratio" < "fact item.amount has more than one value"`), never operand position and never a case-insensitive locale collation.
- Where causes (`RowRef`) are tracked alongside reasons (as in `rezono/src/evaluate.ts` and `rezono.rules/2` witnesses), ties on equal reason text break by Appendix A.4: a constant state without a cause sorts before any cause, and two causes sort by `(relation, canonical_key)` in UTF-8 byte order.

Concretely:

- **`compiler/rezono_compiler/calc_sql.py`:** `Lowering.logic` tests the decisive known-operand branch (`any_hit`) before checking `worst > KNOWN`, and both `Lowering.logic` and `Lowering.strict` select the UTF-8 minimum `r` across all operands whose state equals `worst` (using identical SQL expressions for DuckDB and Feldera).
- **`checker/rezono_checker/calc.py`:** `logic` tests for a decisive known operand before returning `worst_of(vals)`, and `worst_of` selects `min(..., key=lambda r: r.encode("utf-8"))` among operands at the maximum severity.
- **`compiler/tests/calcoracle.py`:** `logic` and strict operator evaluation match the same decisive-first truth table and UTF-8 least-reason selection so property-based tests compare every engine against one oracle.
- **`rezono.rules/2`:** Boolean and strict four-valued expressions lowered into `rezono.rules/2` ([`decisions/language-rezono-1.md`](language-rezono-1.md)) MUST emit and check the exact same Appendix A.1 truth table and Appendix A.4 UTF-8 least-reason choice on DuckDB, Feldera, the Soufflé test oracle, and `checker/rezono_checker/`.

## 3. Publication integrity stays separate

Adopting `false and invalid = false` and `true or invalid = true` inside expression evaluation does not relax publication blocking ([`docs/rezono/publication.md`](../docs/rezono/publication.md), [`decisions/conformance-value-value-invalid-blocks.md`](conformance-value-value-invalid-blocks.md)). An `invalid` input row, an `invalid` calculation output, a `check`/`require` violation, or a `conflict_policy: block` functional derivation in `rezono.rules/2` still blocks publication at its own decision point regardless of whether another expression short-circuited over it.

## 4. Executable conformance cases and `M1` red tests

The two shared conformance cases are updated so `compiler`, `checker`, and `feldera` are no longer listed under `unsupported`:

- [`tests/conformance/value-tt-and-false-invalid.yaml`](../tests/conformance/value-tt-and-false-invalid.yaml)
- [`tests/conformance/value-tt-or-true-invalid.yaml`](../tests/conformance/value-tt-or-true-invalid.yaml)

Two strict `M1` red tests enforce this decision until the fix lands:

1. `compiler/tests/test_four_valued_and_or_compiler.py::test_calc_sql_checker_and_feldera_follow_four_valued_and_or_conformance` — loads both conformance cases, evaluates `false and invalid`, `true or invalid`, reversed orders, 3-ary forms, controls, and Appendix A.4 UTF-8 least-reason ties (in `and`, `or`, `add`, and `eq`) across DuckDB (`calc_sql.py`), `calcoracle.py`, `rezono_calc.py` lowering, the independent checker (`checker/rezono_checker/calc.py`), and Feldera SQL (`calc_sql.feldera`, plus live Feldera parity when `FELDERA_URL` is configured).
2. `checker/tests/test_four_valued_and_or_checker.py::test_checker_calc_follows_four_valued_and_or_conformance` — independently of the compiler, loads both conformance cases and tests the full 25-cell Appendix A.1 truth table, multi-arity `and`/`or`, Appendix A.4 UTF-8 least-reason selection, and end-to-end witness verification (`rezono_checker.calc.check`).

## Alternatives considered

- **Keep `invalid` dominant in `calc_sql.py` and `checker/rezono_checker/calc.py` and only use OCL-style short-circuiting in the TypeScript evaluator.** Rejected: `rezono_calc.py` lowers Rezono `and`/`or` directly to `rezono.calc/1`, so the same Rezono expression would evaluate to `false` in `ask` and `invalid` in DuckDB, Feldera, and the checker, violating the single-semantics invariant and contradicting the already settled conformance decisions.
- **Keep positional-first reason selection in SQL while sorting reasons in TypeScript.** Rejected: swapping `a and b` to `b and a` would silently change witness steps and published reason strings across engines, breaking Appendix A.4 commutativity.
