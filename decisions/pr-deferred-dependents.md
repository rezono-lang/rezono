# Defer the examples, the loop and the runner as dependents of a pull request

A pull request check selects the components a change reaches, and everything that depends on them. The merge queue then runs the same closure or more. Three components, `examples`, `loop` and `run`, now run in a pull request only when the pull request reaches them itself, and otherwise first in the merge queue. [Selector](../scripts/components.py) · [Selection regressions](../.github/workflows/tests/test_components.py)

## Choice

- `PR_DEFERRED_DEPENDENTS` in `scripts/components.py` names `examples`, `loop` and `run`.
- A pull request runs such a component when it changes a file of that component, when the selection routes a changed path to it as a reader (a shared reader in `SHARED_READERS`, a script or workflow it names, `build/`), when its files name a changed file of another component in the base or the head, or when the selection falls back to every component.
- "Names" means that a file of the component contains the changed file's name with its extension (`replay.py`, as a path or a `run_path` argument), its dotted module (`rezono_compiler.emit`), an import of it from its package (`from rezono_compiler import emit`), an import of a top-level module (`import replay`), or a script import path ending in its stem. A bare word such as `emit` does not count. Entry points and manifests (`__init__.py`, `conftest.py`, `index.*`, `pyproject.toml`, `package.json`, `setup.py`) are not named this way; a change to them reaches a deferred component only through its closure. Example: `run/tests/test_offline_run.py` executes `loop/replay.py`, so a pull request that changes `loop/replay.py` runs `run`.
- When the component is only a dependent and names no changed file, for example of the compiler, of `k8s-admission` or of the loop for `run`, the pull request leaves it out. The closure still passes through it, so a component that depends on it runs as before.
- `examples` names many modules of the compiler, the publication package, the connectors and `tests/slip`, so a change to one of those still runs it. Of 124 single-file changes sampled across the compiler, canon, the connectors, `k8s-admission`, the loop, the publication package and `tests/slip`, 60 ran `examples` in a pull request before this change; 14 still do, all because `examples` names the changed file. The merge queue runs `examples` for all 124.
- The merge queue and a push to `main` keep their own selection, which includes these dependents.
- The run summary of `discover` names, for every component that runs, the path that selected it.
- Making the set empty restores all three as pull request dependents. A regression checks that the empty set gives back the full closure.

## Why

- In 34 failed pull request runs before the first deferral, `loop` or `run` never failed alone: a change that broke them broke a component the pull request still runs, or their own tests.
- A typical loop task adds a module and its test. It runs `loop`, `run` and every `examples` shard. Without `run` it saves one job of about five minutes.
- `examples` was left as a dependent until it was measured. Over three hours of queue traffic, pull request runs took 51% of the runner minutes and merge-group runs 30%. `examples`, with seven shards, took 38% of the pull request minutes, and it was the failing job in none of the failed pull request runs. Its share of the pull request cost buys no failure that another job did not find first.

## Alternatives

- **Keep `examples` as a dependent.** It reads every pack, but the measurement shows it catches nothing in a pull request that the other jobs miss, at the largest share of the cost.
- **Narrow by module, inside a component.** A change to a module no other component names would then skip all dependents. That needs an import closure per component and is left for the build rules (`build/rules/selection.dl`).
- **Keep the full closure.** A pull request then costs about as much as a merge-queue group.

## Risk and when to undo it

A change that breaks only a deferred component lands in the merge queue first, which removes that pull request and restarts the groups behind it.

Undo criterion: when a merge-queue group fails on `examples`, `loop` or `run` for a change whose pull request check was green and did not run that component, take that component out of `PR_DEFERRED_DEPENDENTS` (all of them if the cause is not one component). The failing group's run and the pull request's run summary, which lists the components it ran, are the evidence.

Undoing is one constant in `scripts/components.py`, plus the regressions in `.github/workflows/tests/test_components.py` that expect the deferral. Changing them is a test change, so that pull request needs the `planner` label.
