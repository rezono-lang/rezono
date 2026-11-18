# Rezono

Rezono is a language and reasoning engine for describing facts and the rules they must satisfy. You write questions and checks in Rezono, and the batch engine computes the results for a pack. The publisher runs an independent checker before producing a JSON manifest that records content hashes, checks and references to proof data.

## Publish the library example

Start in a clean checkout on Ubuntu 24.04 x86-64 with Python 3.13.18, Bash and jq. The example includes both valid library records and deliberately invalid teaching data. These commands install the locked dependencies into a temporary virtual environment, copy the valid example, publish it locally and show the independent checker's result.

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

The final command prints the recorded proof check. Open the same manifest to see the snapshot hashes and witness references. Explore other [examples](examples/) or read the [language guide](rezono/README.md).

## Feldera relation names

The pipeline plan, exported row tags and published snapshots identify relations by their logical names. For Feldera ingress and SQL queries, use the physical name in the compiled SQL. Feldera reserves the SQL function name `interval` even for quoted relations, so the compiler spells that relation `__rezono_interval` on Feldera. Pack names start with a letter, which keeps the alias distinct from a pack relation such as `rezono_interval`. The compiler's `facts` command emits updates keyed by the Feldera table name.

## Licences and contributing

Code, tests and build scripts use Apache-2.0. Schemas and theories use CC0-1.0. Documentation and example content use CC-BY-4.0. See [LICENSE](LICENSE), the [licence texts](LICENSES/) and the [path-by-path attribution notice](NOTICE).

Read [AGENTS.md](AGENTS.md) and the component's working instructions before making a change. Contributors select one expected failure from `python scripts/red_list.py` and follow [the worker card](WORKER.md).

Pull requests require `check` and the `Inspect test evidence` check. A read-only workflow from the base revision checks proposed Git objects. GitHub attaches the read-only check directly to the reviewed commit. Builders and maintainers who need to move or edit tests, fixtures, recorded outcomes, test helpers or the policy itself must apply the `planner` label and explain why in the pull request. The merge queue runs every discovered component against the combined changes. The compiler and example suites require the pinned Soufflé 2.5 oracle in CI. Job summaries report actual skips by reason, including Feldera comparisons that need an endpoint. Run `python scripts/red_list.py --skips report.xml` on a pytest JUnit report to reproduce a summary. Inactive task claims without an open pull request expire after four hours.
