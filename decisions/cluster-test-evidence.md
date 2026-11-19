# Cluster tests prove what they claim

A test with the `cluster` mark runs only in the disposable cluster workflow
([shared disposable cluster](shared-disposable-cluster.md)). Ordinary
collection deselects it. That leaves two ways for such a test to look green
without proving anything:

- The required check "Added tests on the base source" runs the added tests
  of a pull request on the base source. It cannot run a cluster test there,
  so the test counts as not selected and the check only warns.
- In suite mode the cluster workflow accepts any pytest exit status 0. A
  cluster test that calls `pytest.skip`, carries a `skip` or `skipif` mark, or
  uses `pytest.importorskip` passes the suite while it checked nothing.

## 1. A skip in a cluster run is a failure

When `--rezono-cluster` is active, the cluster plugin in `loop/rezono_cluster.py`
reports every cluster item that ends as skipped as failed. The failure text
starts with `Skipped cluster test: ` followed by the skip reason. This holds in
suite mode (`loop/cluster/select_tests.py`) and for assigned tasks alike.

- An expected-red result is not a skip. A cluster test with a strict
  `xfail` mark that fails stays `xfailed`, so a pending cluster task does not
  break the suite.
- `--rezono-report-cluster` on an ordinary runner is unchanged: it reports
  cluster items as skipped without running them, and that is not a cluster run.
- A test that depends on something the fixture does not provide yet stays a
  red test with a reason. It does not skip.

## 2. Added cluster tests run on the base in the cluster workflow

On a pull request, after the candidate's own cluster run, the cluster
workflow lays the pull request's protected paths over the base exactly as the
base-source check does: the base copy of `scripts/red_before.py prepare`
writes the selection of added tests without a red mark. A new
`loop/cluster/base_check.py [--root ROOT] SELECTION` runs the cluster items of that
selection with `--rezono-cluster -m cluster` in the same fixture and reads
each outcome from a JUnit report.

| Outcome on the base | Status |
| --- | --- |
| no cluster item in the selection | 0, and it says so |
| at least one cluster item fails and none skips | 0 |
| a cluster item skips (reported as `Skipped cluster test: `) | 1 |
| every cluster item passes | 1 |

A skip on the base is never counted as the base failing: it proves nothing,
and section 1 already forbids it. Ordinary items in the selection remain the
base-source check's work; `base_check.py` ignores them. The step runs only for
pull request events, like the base-source check.

## Alternatives considered

- Run cluster tests in the required base-source check. That needs the
  fixture in the required workflow, which must stay fast and independent.
- Treat "none ran on the base" as an error in `scripts/red_before.py`. That
  would fail every pull request that adds a cluster test, without proving
  anything either way.
- Forbid `pytest.skip` in cluster test files by a source scan. A scan misses
  `skipif` marks from conftests and `importorskip`; the outcome of the run is
  the reliable signal.
