# What if, locally on the batch engine

A reader can ask "what if" of any value. Until now that needed a pull request (a proposal) or the independent reference of an example. This decision makes it one local command on the batch engine. It does not wait for the incremental engine, which stays an oracle in the tests.

## The command

`rezono-suppose`, a console script of `edge/publisher`, in the module `rezono_publisher.suppose`:

```sh
rezono-suppose PACK --store URL --base-manifest m-N --role ROLE --delta FILE
```

The same as a function, which the command calls:

```python
suppose(pack_dir, store, base_manifest: str, role: str, delta: dict) -> dict
```

It takes the pack's directory, the store, a published main manifest of that pack, one role and one delta in the form of `contracts/delta.yaml`. It calls the existing steps and computes nothing itself:

1. Copy the pack, and every pack it imports by a relative path, into a fresh working directory. `rezono_compiler.writer` writes only into a pack, never elsewhere, and the pack the caller gave stays untouched.
2. Apply the delta there with `rezono_compiler.writer.apply_delta`.
3. Publish the copy next to the base, as the proposal path does (`--proposal` and `--base-manifest` of `rezono-publish`): the epoch is the base's plus one, with the base's knowledge time and sources.
4. Write the role's difference with `rezono_publisher.difference.publish`, passing the delta. The checker compares the two snapshots and rebuilds the proof graph before anything is written, as it does for a proposal.
5. Read that difference back and print the answer.

The REPL shows the result with its existing `:suppose proposal <id>`, and stays read-only.

## The name of a local assumption

A local assumption has no pull request number. Its proposal name is `local-` followed by the first twelve hexadecimal digits of the SHA-256 of the delta's canonical JSON (RFC 8785). The manifest is then `p-local-<digits>-<epoch>`, which the difference step already accepts. The same delta on the same base gives the same name and the same bytes, so a repeat writes nothing new and a run that stopped is completed by the next. The rows the delta writes are stated by that assumption; they never become facts of the main manifest.

## A role that reads everything

There is no separate path for a role that reads everything. The difference is made for a role the base publishes as `may_read`; a role whose `may_read` covers every relation gets the difference of the whole publication. A role the base publishes only as `complete` has no reader on the server, and the command refuses it with that reason.

## The answer

The command prints one JSON document:

```json
{"format": "rezono.supposition/1", "pack": "...", "base_manifest": "m-N", "manifest": "p-local-...-M",
 "role": "...", "rows": [{"relation": "...", "key": [...], "weight": 1, "row": {...}, "witness": "..."}],
 "withheld": null}
```

- A row that the assumption adds has weight `+1`, a row it removes `-1`. A changed row counts on both sides: `-1` for the old row and `+1` for the new one.
- `row` maps each column of the role's snapshot to its cell, as published. A calculated value keeps its columns `value`, `state` and `reason`.
- `witness` is the key in the store of the proof of that row: in the assumption for `+1`, in the base for `-1`. The checker has accepted it before the answer exists.
- A value that is unknown under the assumption has the state `unknown` and its reason. It is never zero.
- Observations do not change under an assumption. A delta that changes a kind whose bundle layer is `observation` is refused with that reason.
- The role sees only the difference in what it reads.
- A delta that may change read access (`rezono_publisher.difference.withheld`) gives no rows. `withheld` then names the reason, as text, and nothing of a difference is written.

Exit 0: answered, also when withheld. Exit 2: the checker refused, nothing written. Exit 1: an error.

A sweep over a range of values stays outside this command: `rezono_publisher.sweep` and `:sweep` are unchanged.

## Where it shows

- The step "Compare the baseline and a policy scenario" of `docs/tutorial.md` runs `rezono-suppose` on `subsidy`. `examples/subsidy/reference.py` stays the oracle in the test and leaves the reading text of that step.
- `README.md` gets a third quickstart step: one assumption and its difference (see [the front door](front-door.md)).
- The row "Change streams" in `docs/formal.md` says that the incremental oracle has no green run on `main` yet, and links the open issue. That sentence goes with the first green nightly run.

## Considered

- **Scenario files in the pack** (`compiler/rezono_compiler/scenarios.py`). They can add or replace a row but not remove one, and the publisher does not publish such a state.
- **A proposal per question.** It needs a pull request, a base commit and a co-author, which a local question has none of.
- **Computing the difference in the command.** The publisher already writes a checked difference; a second computation would be a second meaning.
- **The incremental engine.** It has no green run on `main` yet; the batch engine answers now, and the oracle keeps comparing them.
