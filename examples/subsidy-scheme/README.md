# Example pack `subsidy-scheme`: the scheme as a definition

The Energy-Saving Subsidy Regulation 2026 of a fictional municipality, as a fact-free pack (`theory: true`): what several municipalities could share. It is the definition that [`subsidy`](../subsidy/README.md) imports by path and hash (RV-X35, [shared definitions](../../docs/ring2/shared-definitions.md)). Everything here is synthetic.

## What is in it, and what is not

| In this pack (the definition) | In the pack that imports it (`subsidy`) |
|---|---|
| the kinds: articles, scheme parameters, the calendar their dates are days of, the evaluation day, cost items, households, applications, quote lines, income statements, advice reports (`schema/subsidy.yaml`) | the decided amounts and rates (`scheme_parameter` rows with their decision): facts with a decider, never part of a definition |
| the rules of assessment and award: `rules/costs.dl`, `rules/assessment.dl`, `rules/scheme.dl`, `rules/findings.dl` | the cases: households, applications, quotes, income statements, advice reports |
| the calculation of the award in six steps (`calc/award.yaml`) | the date the calculation is evaluated on (`as_of`) |
| the labels and messages of all of the above, and its signs (`channels.yaml`) | the roles and what each may read (`rules/access.dl`): grants are the consumer's |
| | the payment ledger, its close and the drift against the award: a reference source |

It imports [`std-decision`](../../packs/std-decision/README.md), whose `Decision` a scheme parameter points to and whose `in_force_on` the rule `decided_parameter` reads.

## Using it

A pack imports it in `pack.yaml` with `{name: subsidy-scheme, path: <path to this directory>, sha256: <hash>}`, where the hash is what `python -m rezono_compiler hash examples/subsidy-scheme` prints; another value is refused. The importing pack states the evaluation date in a calc file of its own and holds the facts. `python -m rezono_compiler check examples/subsidy-scheme` checks the definition on its own; a theory publishes no instance.

The model, kind by kind, the five questions it answers and the worked example are in the README of [`subsidy`](../subsidy/README.md), which also has the tests and the independent reference (`reference.py`).
