# Partial predicates in questions

A question can call a derived relation, as in `ask x: Stage where not zero(x)`. Until now the role schema described such a relation only by its binders and its world. Evaluation read a missing success row of a closed relation as false. That is wrong when the relation's guard can be undecided for a key: `zero(x)` defined by `x.rank = 0` has no row for a stage whose rank is unknown, and `not zero(x)` then manufactured a true answer. [Shared expression semantics](language-expression-semantics.md) §2 settles the rule; this decision fixes how a question receives what it needs.

## What the role schema says about a relation

Each entry under `rules` in a question's role schema keeps `binders` and `world`, and adds two fields.

- `states` is the set of truth states a ground call can take, from the linked predicate summary: `known` alone for a decided relation, and `not_applicable`, `unknown` or `invalid` beside it where a source of partiality reaches the relation. An entry without `states` keeps its existing meaning, so existing role schemas do not change.
- `outcome` says whether the publication carries a checked outcome for the relation, keyed by the complete invocation. An outcome row gives the key and either a known truth value or a state with its reason and cause.

## What a question may do with it

1. A positive call such as `zero(x)` is always allowed. A success row proves `T`.
2. If `states` holds more than `known` and there is no outcome, a question cannot tell a miss from an undecided call. Negation, the antecedent of `=>`, `none`, `all`, and a count, sum, minimum or maximum over a filter that calls the relation each need that distinction. The checker reports `R047` at the call or negation, as the rule checker does for `not zero(x)`.
3. With an outcome, evaluation reads the call's truth state from the outcome row. `T` and `F` behave as before. `N`, `U` and `I` keep their reason and cause, so `not zero(a)` is undecided with the reason and the cause of `a`'s rank Value, and the answer classifies the subject as `Undecided`.
4. A relation whose `states` is `known` alone, or that has no `states`, keeps the existing reading: a closed miss is false and an open miss is `unknown` with `open_world`.

Evaluation loads outcome rows beside the success rows, under the relation's name, with the same canonical keys.

## Considered

- Treat a missing `states` as possibly partial. That follows the conservative linker rule, but it would make every existing question over a rule refuse until every publisher emits summaries. The linker stays conservative; the question boundary reads what the publication states.
- Publish only the success rows and let the question re-evaluate the guard. A question does not read the rule's premises and cannot see what the role does not read.
- Report undecided calls as `unknown` without a cause. That loses the reason and cause that §2 requires the answer to keep.

## Acceptance

`tests/conformance/expression-ask-partial-call.yaml` states the cases: the refusal of `not zero(x)` and of a count over `zero(it)` without an outcome, a positive call without an outcome, the keyed undecided row for `a` in both polarities, and a decided relation whose negation stays legal. `rezono/test/test_expression_ask_partial_call.py` runs them through the question checker and evaluator.
