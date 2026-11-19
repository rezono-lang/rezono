# Tests for every pending building block

`compiler/tests/rezono/language_usage.py` names a building block Pending until its reading and lowering tests pass. Every pending building block has a red test for reading and one for lowering, or this decision says why it has none yet.

| Building block | Reading | Lowering |
| --- | --- | --- |
| calculation | `rezono/test/test_calculation.py`; version blocks with definitions, `unit` and `overrides` in `rezono/test/test_calculation_versions.py` | `compiler/tests/rezono/test_lower_calculation.py` |
| parameters | `rezono/test/test_parameters.py`, `rezono/test/test_version_replaces.py` | a row-backed parameter in `compiler/tests/rezono/test_lower_parameters.py` |
| dated-fact | `rezono/test/test_dated_fact.py`, `rezono/test/test_fact_context_axes.py` | none yet, see below |
| exceptions | `rezono/test/test_exceptions.py` | none yet, see below |
| schema-metadata, fact-provenance, structured-fact, open-world, inverse-reference, table-policy | their existing reading tests | their existing lowering tests |
| deprecated-declaration | `rezono/test/test_deprecated_declaration.py` | `compiler/tests/rezono/test_lower_deprecated.py` |
| step-declaration | `rezono/test/test_step_declaration.py` | none yet, see below |
| intermediate-invariant | `rezono/test/test_invariant_intermediate.py` | none yet, see below |

The lowering tests of calculations and parameters compare with the existing `calc/*.yaml` files of `examples/subsidy-scheme` and `examples/subsidy`, as [Calculated values](language-calculations.md) says.

## Why dated facts, exceptions and inline parameters have no lowering test yet

Only `examples/zorgtoeslag` uses them. That example is already written in the language and has no file in an existing notation, so there is no oracle to lower against, and it is not a pack that a conversion waits for.

- **Exceptions.** The calculation model has no operator for `unless`; [Calculated values](language-calculations.md) refuses it with `R050`.
- **Dated facts.** The fact contracts have no place for versioned values yet ([Dated facts](language-dated-facts.md)).
- **Inline parameter versions.** `rezono.calc/1` reads parameters as rows; lowering refuses an inline parameter with `R050`.

They stay Pending. No pack of `examples/`, `packs/` or `run/packs/` uses them, so they hold back no conversion. When a pack needs one, a decision gives its lowering and its oracle first, and then its lowering test.

## Why safe steps have no lowering test yet

[Safe steps](language-safe-steps.md) registers three building blocks: the whole-record assumption, the step declaration and the intermediate invariant. Each has its reading test. The step declaration and the intermediate invariant hand their lowered results to `pack.read` beside the native rules they name, so their lowering tests follow once native rules publish through the ordinary pack compiler (`compiler/tests/rezono/test_native_rule_publication_parity.py`). The whole-record assumption lowers in the question evaluator of `rezono/`, from the tree its reading test fixes, so its lowering test follows that reading test. A suppose line is a question, not a declaration of a module, so the usage inventory does not count it.

## Considered

- **Lowering tests against `examples/zorgtoeslag` itself.** The expected program would be the current output, not an independent source.
- **Removing these building blocks from the table.** They are part of the language and stay visible as Pending.
