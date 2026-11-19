# Rezono

Facts and rules in, answers with proof out: every conclusion carries a witness that an independent checker verifies.

## What you get

- Rules over facts, computed for a whole pack by a batch engine on DuckDB.
- A witness for every derived row: the rule that derived it and the rows it used.
- An independent checker that verifies the proofs before anything is published.
- A manifest per publication with content hashes, checks and references to the proofs.
- Example packs to copy, from a library catalogue to a municipal subsidy scheme.

## Example

The [subsidy example](examples/subsidy/README.md) is a fictional energy-saving subsidy. Two of its facts: application A001 comes from household H001, and household H001 has a registered advice report.

```yaml
application:
  - {"id": "A001", "household": "H001", "claimed_costs": 1100000}
advice_report:
  - {"id": "R001", "household": "H001"}
```

One rule, from [the assessment rules](examples/subsidy-scheme/rules/assessment.dl): an application is advised when its household has an advice report. The slot `household` of `application` is the relation `application__household`.

```
advised(a) :- application__household(a, h), advice_report__household(_, h).
```

The answer and its witness: the derived row, the rule that derived it, and the two fact rows it used. The checker verified this witness before the publication was written.

```text
advised(A001)
  rule: advised
  premise: application__household(A001, H001)
  premise: advice_report__household(R001, H001)
```

## Try it

Start in a clean checkout on Ubuntu 24.04 x86-64 with Python 3.13.18, Bash and jq. Run the steps in order in one shell.

### 1. Publish the library example

Install the locked dependencies into a temporary virtual environment, copy the valid part of the library example, publish it to a local store and show the independent checker's result.

```bash
work=$(mktemp -d)
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

Publish the subsidy example to the same store. The publisher only writes the manifest once the checker has accepted every proof. Then read the witness of the row from the example.

```bash
manifest=$("$work/venv/bin/rezono-publish" examples/subsidy --store "file://$work/store" --role reader=complete --epoch 1 --knowledge-time 2026-01-01T00:00:00Z)
witnesses="$work/store/subsidy/objects/$(jq -r '.witnesses[0].sha256' "$work/store/subsidy/manifests/$manifest.json").json"
jq -er 'def row: "\(.relation)(\(.key | fromjson | join(", ")))"; .witnesses[] | select(.conclusion == {relation: "advised", key: "[\"A001\"]"}) | (.conclusion | row), "  rule: \(.rule_id)", (.premises[] | "  premise: \(.row | row)")' "$witnesses"
```

```text
advised(A001)
  rule: advised
  premise: application__household(A001, H001)
  premise: advice_report__household(R001, H001)
```

### On any other machine

With Docker, build an image from the checkout with the same Ubuntu, Python and jq, start a shell in it, and run the steps above there. The image stays on your machine.

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
