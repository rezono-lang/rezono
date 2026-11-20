# Rezono

Facts and rules in, answers with proof out: every conclusion carries a witness that an independent checker verifies.

## What you get

- Rules over facts, computed for a whole pack by a batch engine on DuckDB.
- A witness for every derived row: the rule that derived it and the rows it used.
- An independent checker that verifies the proofs before anything is published.
- A manifest per publication with content hashes, checks and references to the proofs.
- Example packs to copy, from a library catalogue to a municipal subsidy scheme.

## Example

The [subsidy example](examples/subsidy/README.md) is a fictional energy-saving subsidy. Some of its facts: application A001 comes from household H001, which has an income of € 31,400 and an advice report; application A003 comes from household H003, which has not sent its income statement.

```yaml
application:
  - {"id": "A001", "household": "H001", "claimed_costs": 1100000}
  - {"id": "A003", "household": "H003", "claimed_costs": 327550}
income_statement:
  - {"id": "S001", "household": "H001", "income": 3140000}
advice_report:
  - {"id": "R001", "household": "H001"}
```

The answers. A001 gets € 2,694: a household of three with € 31,400 lies between the € 30,000 threshold and the € 42,000 limit, so the partial rate of 24% gives a cost share of € 2,544, plus the € 150 advice allowance. Each step names its calculation rule, version, evaluation date, definition and the parameters it read, and a parameter leads back to its article and council decision. For A003 the assessment is unknown with its reason, and the calculated award stays unknown, not zero, while the income statement is missing, even though the example's payment ledger records a payment for it.

```text
A001: calculated award € 2,694
  award € 2,694 = rule award, version 2026, evaluated on 2026-11-10, definition at_most_the_maximum, parameter maximum_award € 5,000
  entitlement € 2,694 = rule entitlement, version 2026, evaluated on 2026-11-10, definition share_plus_allowance
  cost_share € 2,544 = rule cost_share, version 2026, evaluated on 2026-11-10, definition partial_rate, parameter partial_rate 24%
  advice_allowance € 150 = rule advice_allowance, version 2026, evaluated on 2026-11-10, definition allowance_or_nothing, parameter advice_allowance € 150
  income_limit € 42,000 = rule income_limit, version 2026, evaluated on 2026-11-10, definition threshold_plus_margin, parameter income_margin € 12,000
  income_threshold € 30,000 = rule income_threshold, version 2026, evaluated on 2026-11-10, definition base_plus_persons, parameter income_threshold_base € 24,000, parameter income_threshold_per_person € 2,000
  parameter partial_rate: Article 5: cost share, council decision 2026-047: First amendment: a higher partial rate from 1 July 2026
A003: assessment unknown, reason income_statement_not_received
  calculated award unknown while the income statement is missing: fact assessed_income.cents is missing
```

The independent checker verified the witness of every answer before the publication was written, and a separate computation, `examples/subsidy/reference.py`, gives the same amounts.

## Try it

Start in a clean checkout on Ubuntu 24.04 x86-64 with Python 3.13.18, Node 24 (the version in `.node-version`), npm, Bash and jq. Run the steps in order in one shell.

### 1. Publish the library example

Install the locked packages of the Rezono reader in `rezono/`: the compiler reads authored `.rezono` pack sources through Node. Then install the locked dependencies into a temporary virtual environment, copy the valid part of the library example, publish it to a local store and show the independent checker's result.

```bash
work=$(mktemp -d)
npm ci --prefix rezono --cache "$work/npm-cache" --no-audit --no-fund --silent
python3 -m venv "$work/venv"
"$work/venv/bin/python" -m pip install -q --no-deps --require-hashes -r requirements/run.txt
"$work/venv/bin/python" -m pip install -q --no-deps --no-build-isolation -e admission -e canon -e compiler -e checker -e edge/publisher
"$work/venv/bin/python" -m pip check
cp -R examples/library "$work/library"
rm "$work/library/facts/errors.yaml"
manifest=$("$work/venv/bin/rezono-publish" "$work/library" --store "file://$work/store" --role reader=complete --epoch 1 --knowledge-time 2026-01-01T00:00:00Z)
jq -e '.checks[] | select(.name == "rezono:proofs" and .status == "green" and .violations == 0)' "$work/store/library/manifests/$manifest.json"
```

```text
No broken requirements found.
{
  "name": "rezono:proofs",
  "status": "green",
  "violations": 0
}
```

### 2. Compute and prove with the subsidy example

Publish the subsidy example to the same store. The publisher only writes the manifest once the checker has accepted every proof. Then read the two answers from the witnesses, and the article and council decision from the parameter rows.

```bash
manifest=$("$work/venv/bin/rezono-publish" examples/subsidy --store "file://$work/store" --role reader=complete --epoch 1 --knowledge-time 2026-01-01T00:00:00Z)
store="$work/store/subsidy"
snapshot() { echo "$store/objects/$(jq -r --arg r "$1" '.snapshots[] | select(.relation == $r) | .sha256' "$store/manifests/$manifest.json").json"; }
witnesses="$store/objects/$(jq -r '.witnesses[0].sha256' "$store/manifests/$manifest.json").json"
jq -r --slurpfile units "$(snapshot scheme_parameter__unit)" 'def eur: tonumber / 100 | tostring | if length > 3 then .[:-3] + "," + .[-3:] end | "€ \(.)"; (INDEX($units[0][].key; .[0]) | map_values(.[1])) as $unit | INDEX(.calc_witnesses[] | select(.conclusion.key | fromjson | .[0] == "A001"); .rule) as $calc | "A001: calculated award \($calc.award.value | eur)", ($calc[("award", "entitlement", "cost_share", "advice_allowance", "income_limit", "income_threshold")] | "  \(.rule) \(.value | eur) = rule \(.rule), version \(.version), evaluated on \(.valid_at), definition \(.definition)" + ([.steps[] | select(.op == "parameter") | ", parameter \(.ref) \(if $unit[.element] == "ppm" then "\(.value | tonumber / 10000)%" else .value | eur end)"] | add // ""))' "$witnesses"
jq -nr --slurpfile article "$(snapshot scheme_parameter__article)" --slurpfile decision "$(snapshot scheme_parameter__decision)" --slurpfile title "$(snapshot article__title)" --slurpfile decided "$(snapshot decision__title)" 'def at($rows; $id): $rows[0][].key | select(.[0] == $id) | .[1]; "  parameter partial_rate: \(at($title; at($article; "par-06"))), council decision \(at($decision; "par-06")): \(at($decided; at($decision; "par-06")))"'
jq -er '(.witnesses[].conclusion | select(.relation == "assessment") | .key | fromjson | select(.[0] == "A003") | "A003: assessment \(.[1]), reason \(.[2])"), (.calc_witnesses[] | select(.rule == "award" and (.conclusion.key | fromjson | .[0] == "A003")) | "  calculated award \(.state) while the income statement is missing: \(.reason)")' "$witnesses"
```

```text
A001: calculated award € 2,694
  award € 2,694 = rule award, version 2026, evaluated on 2026-11-10, definition at_most_the_maximum, parameter maximum_award € 5,000
  entitlement € 2,694 = rule entitlement, version 2026, evaluated on 2026-11-10, definition share_plus_allowance
  cost_share € 2,544 = rule cost_share, version 2026, evaluated on 2026-11-10, definition partial_rate, parameter partial_rate 24%
  advice_allowance € 150 = rule advice_allowance, version 2026, evaluated on 2026-11-10, definition allowance_or_nothing, parameter advice_allowance € 150
  income_limit € 42,000 = rule income_limit, version 2026, evaluated on 2026-11-10, definition threshold_plus_margin, parameter income_margin € 12,000
  income_threshold € 30,000 = rule income_threshold, version 2026, evaluated on 2026-11-10, definition base_plus_persons, parameter income_threshold_base € 24,000, parameter income_threshold_per_person € 2,000
  parameter partial_rate: Article 5: cost share, council decision 2026-047: First amendment: a higher partial rate from 1 July 2026
A003: assessment unknown, reason income_statement_not_received
  calculated award unknown while the income statement is missing: fact assessed_income.cents is missing
```

### On any other machine

With Docker, build an image from the checkout with the same Ubuntu, Python, Node and jq, start a shell in it, and run the steps above there. The image stays on your machine.

```sh
docker build --tag rezono-quickstart .
docker run --rm -it rezono-quickstart
```

## Read further

- [The tutorial](docs/tutorial.md) follows one subsidy award from its facts to its proof.
- [The language guide](rezono/README.md) describes the Rezono language and its reader.
- [The examples](examples/) are packs to read and copy.
- [The vision](docs/vision.md) says where Rezono is going.

## Status

There is no release yet. Install from a checkout, as the steps above do. At this commit the compiler, the batch engine, the independent checker and the publisher work from a checkout, and CI runs the steps above on every pull request.

## Licences and contributing

Code, tests and build scripts use Apache-2.0, schemas and theories CC0-1.0, documentation and examples CC-BY-4.0: see [LICENSE](LICENSE), [the licence texts](LICENSES/) and [NOTICE](NOTICE).
To report a bug or contribute from a fork, read [CONTRIBUTING.md](CONTRIBUTING.md).
