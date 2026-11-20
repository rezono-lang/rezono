# Follow a subsidy award from inputs to proof

The [subsidy example](../examples/subsidy/README.md) models a fictional municipal energy-saving scheme. The [scheme pack](../examples/subsidy-scheme/README.md) supplies the kinds and rules. The subsidy pack supplies synthetic applications, policy decisions and payment records.

Run the commands from the repository root with the compiler and DuckDB installed. Use a checkout that preserves LF line endings, because the pack imports are pinned to the hashes of their files. The repository's [setup instructions](../README.md) show how to install the local packages.

## Check the pack and compile its schema

```bash
python -m rezono_compiler check examples/subsidy
python -m rezono_compiler compile examples/subsidy generated/subsidy
```

The first command reports `ok examples/subsidy`. The second writes the compiled schema to `generated/subsidy/bundle/schema-bundle.json`.

## Follow application A001

In [the application facts](../examples/subsidy/facts/applications.yaml), A001 belongs to a household of three and claims €11,000:

```yaml
household:
  - {"id": "H001", "persons": 3}
application:
  - {"id": "A001", "household": "H001", "claimed_costs": 1100000}
```

The claim has three quote lines. The first two count toward eligible costs, for a total of €10,600.

```yaml
cost_line:
  - {"id": "L0001", "application": "A001", "item": "heat-pump", "amount": 820000}
  - {"id": "L0002", "application": "A001", "item": "roof-insulation", "amount": 240000}
  - {"id": "L0003", "application": "A001", "item": "scaffolding", "amount": 40000}
```

[The cost rules](../examples/subsidy-scheme/rules/costs.dl) add the eligible lines:

```
.decl eligible_costs(application: symbol, cents: number)
eligible_costs(a, t) :- has_quote(a), t = sum c : { eligible_line(a, _, c) }.
```

The [assessment rules](../examples/subsidy-scheme/rules/assessment.dl) give a reason when either input is missing:

```
assessment(a, "unknown", "income_statement_not_received") :- income_missing(a).
assessment(a, "unknown", "quote_not_received") :- quote_missing(a).
```

A001 has both an income statement and a registered advice report:

```yaml
income_statement:
  - {"id": "S001", "household": "H001", "income": 3140000}
advice_report:
  - {"id": "R001", "household": "H001"}
```

The [award calculation](../examples/subsidy-scheme/rezono/award.rezono) takes the partial rate when income is above the threshold and at or below the limit:

```rezono
      definition partial_rate when income_threshold < assessed_income.cents
        and assessed_income.cents <= income_limit
        then round(assessed_costs.cents * partial_rate / 1000000)
```

At the pack's evaluation date of 10 November 2026, the threshold for three people is €30,000 and the limit is €42,000. A001's income of €31,400 makes the 24% rate apply. Its cost share is €2,544. Adding the €150 advice allowance gives €2,694, below the €5,000 cap.

The parameters name their supporting decisions. [The scheme rules](../examples/subsidy-scheme/rules/scheme.dl) derive whether each parameter's decision is in force and report parameters without one:

```
decided_parameter(p, d, r) :- scheme_parameter__decision(p, d), in_force_on(d, r).
```

```
undecided_parameter(p, r) :- scheme_parameter(p), reference_date(r), !has_decision_in_force(p, r).
```

## Inspect a proof

```bash
python -m rezono_compiler explain examples/subsidy generated/subsidy-explained
```

In `generated/subsidy-explained/0-applications/proofs.json`, look for the following root. This excerpt shows its direct witness. The full proof also contains the witnesses for its derived premises.

```json
{
  "root": {
    "relation": "assessment",
    "key": "[\"A001\",\"known\",\"\"]"
  },
  "witnesses": [
    {
      "rule_id": "assessment_3",
      "bindings": [
        {
          "variable": "?a",
          "value": "A001"
        }
      ],
      "premises": [
        {
          "row": {
            "relation": "application",
            "key": "[\"A001\"]"
          },
          "polarity": "positive"
        },
        {
          "row": {
            "relation": "income_missing",
            "key": "[\"A001\"]"
          },
          "polarity": "negative"
        },
        {
          "row": {
            "relation": "quote_missing",
            "key": "[\"A001\"]"
          },
          "polarity": "negative"
        }
      ]
    }
  ]
}
```

The witness binds A001 to the application row. Its two negative premises record that neither the missing income nor the missing quote rule derived a row for A001.

## Compare the baseline and a policy scenario

Run the independent Python reference in summary mode. It prints one line for the baseline and then one for each successive scenario, without writing result fixtures.

```bash
python examples/subsidy/reference.py --summary
```

`0-applications` has 240 applications, 17 with an unknown assessment, 205 with a positive award and zero undecided parameters. Its awards total 49,800,714 cents. After the four existing scenarios, `4-family-threshold` totals 50,898,411 cents and reports two undecided parameters.

Suppose the advice allowance increases from €150 to €250. Save the following as `examples/subsidy/scenarios/5-higher-allowance.yaml`. The scenario replaces the parameter with the same ID and links it to a proposed decision. The supplied figures are examples in whole cents.

```yaml
decision:
  - {"id": "supposed-allowance", "title": "Supposed: higher advice allowance", "valid_from": "2026-01-01", "valid_from_day": 20260101, "state": "proposed"}
scheme_parameter:
  - {"id": "par-07", "name": "advice_allowance", "value": 25000, "unit": "cents", "valid_from": "2026-01-01", "valid_until": "2027-01-01", "calendar": "civil", "article": "art-6", "decision": "supposed-allowance"}
```

```bash
python examples/subsidy/reference.py --summary
```

The earlier lines stay the same. The appended `5-higher-allowance` line reports 51,558,411 cents in total awards, an increase of 660,000 cents over the fourth scenario. It reports three undecided parameters because the allowance and the two threshold parameters stand on proposed decisions.
