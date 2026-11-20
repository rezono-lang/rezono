# Rezono documentation

## Start here

- [Tutorial](tutorial.md) follows a change through a pack, its conclusions and a checked publication.
- [Vision](vision.md) describes the project's commitments for rules, proof, access and reproducibility.
- [Formal foundations](formal.md) connects schema instances, weighted changes, rules, migration and protocols to their checks.

## Compiler and packs

- [Pack definitions and import pins](compiler/pack.md) describes which bytes a pinned import covers.
- [Schema operations and views](compiler/schema-operations.md) describes executable views, checked migrations and the canonical writer.
- [Rules and explanation](compiler/rules.md) covers rule execution, witnesses, completeness, seals and sweeps.
- [Import and provenance](compiler/import.md) follows a fact from its origin to a role's proof and describes the import design.

## Language and publication

- [Rezono v0](rezono/v0.md) specifies the language's module boundary.
- [Expressions](rezono/expressions.md) describes typed expressions and their evaluation.
- [Tables](rezono/tables.md) defines how authored rows represent facts.
- [Publication](rezono/publication.md) specifies the checked artifacts and how to read them.
- [Language coverage](rezono/language-coverage.md) tracks which specifications have an implemented path and executable checks.
- [Native rule pack linking](rezono/native-rule-pack-link.md) defines how native rules link to typed declarations in an import closure.
- [First-release language proposal (`rezono 1`)](rezono/first-release-proposal.md) is a proposal (not a specification or decision) exploring unified derivations and first-release scope.

## Conformance and maintenance

- [Language conformance cases](rezono/cases/) hold machine-readable language examples and expectations.
- [Publication conformance cases](publication/cases/) hold machine-readable publication cases and their schemas.
- [Shared semantics cases](semantics/) cover value states and witness alternatives.
- [Documentation working rules](AGENTS.md) govern changes to these pages and their examples.
