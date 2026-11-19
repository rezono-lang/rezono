# Defer the loop and the runner as dependents of a pull request

A pull request check selects the components a change reaches, and everything that depends on them. The merge queue then runs the same closure or more. Two components, `loop` and `run`, now run in a pull request only when the pull request reaches them itself, and otherwise first in the merge queue. [Selector](../scripts/components.py) · [Selection regressions](../.github/workflows/tests/test_components.py)

## Choice

- `PR_DEFERRED_DEPENDENTS` in `scripts/components.py` names `loop` and `run`.
- A pull request runs such a component when it changes a file of that component, when the selection routes a changed path to it as a reader (a shared reader in `SHARED_READERS`, a script or workflow it names, `build/`), when its files name a changed file of another component in the base or the head, or when the selection falls back to every component.
- "Names" means that a file of the component contains the changed file's stem, the way an import, a `run_path` call or a subprocess path does. Entry points and manifests (`__init__.py`, `conftest.py`, `index.*`, `pyproject.toml`, `package.json`, `setup.py`) are not named this way; a change to them reaches a deferred component only through its closure. Example: `run/tests/test_offline_run.py` executes `loop/replay.py`, so a pull request that changes `loop/replay.py` runs `run`.
- When the component is only a dependent and names no changed file, for example of the compiler, of `k8s-admission` or of the loop for `run`, the pull request leaves it out. The closure still passes through it, so a component that depends on it runs as before.
- The merge queue and a push to `main` keep their own selection, which includes these dependents.
- The run summary of `discover` names, for every component that runs, the path that selected it.
- Making the set empty restores both as pull request dependents. A regression checks that the empty set gives back the full closure.

## Why

- In 34 failed pull request runs before this change, `loop` or `run` never failed alone: a change that broke them broke a component the pull request still runs, or their own tests.
- A typical loop task adds a module and its test. It runs `loop`, `run` and every `examples` shard. Without `run` it saves one job of about five minutes; `examples` is the larger share, see below.
- `examples` stays a dependent. Whether to defer it too is decided after a day of measurements, against the merge-queue groups that fail on something a pull request should have caught.

## Alternatives

- **Defer `examples` as well.** It is the most expensive dependent, but it reads every pack and fails more often; first measure.
- **Narrow by module, inside a component.** A change to a module no other component names would then skip all dependents. That needs an import closure per component and is left for the build rules (`build/rules/selection.dl`).
- **Keep the full closure.** A pull request then costs about as much as a merge-queue group.

## Risk and when to undo it

A change that breaks only a deferred component lands in the merge queue first, which removes that pull request and restarts the groups behind it.

Undo criterion: when a merge-queue group fails on `loop` or `run` for a change whose pull request check was green and did not run that component, empty `PR_DEFERRED_DEPENDENTS`. The failing group's run and the pull request's run summary, which lists the components it ran, are the evidence.

Undoing is one constant in `scripts/components.py`, plus the regressions in `.github/workflows/tests/test_components.py` that expect the deferral. Changing them is a test change, so that pull request needs the `planner` label.
