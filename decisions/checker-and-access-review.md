# Review of the checker and access before they land

A change to the independent checker or to read access is read by a reviewer before it lands. A change to the workflows or to the meaning of the compiler is still read after it lands. Every other change lands when the check is green, as before.

## The paths read first

A pull request needs a review before it lands when it changes a file that is not a test under one of these paths:

| Path | What it decides |
| --- | --- |
| `checker/rezono_checker/` | whether a witness, a completeness receipt or a round certificate is accepted |
| `canon/rezono_canon/` | the canonical encoding and hashes the checker compares a witness by |
| `packs/std-access/` | which relations and rows a role may read |
| `edge/gate/src/` | what the read kernel and the gate hand to a role |
| `edge/publisher/rezono_publisher/access.py` | how the server applies read access per role |
| `edge/publisher/rezono_publisher/calc_scope.py` | which calculated rows and witnesses a role gets, by the publisher's own reading of the calculation program |
| `edge/publisher/rezono_publisher/sources.py` | which source entries a role receives with the base rows it reads |
| `edge/publisher/rezono_publisher/sweep.py` | which roles get a sweep variant and which see its status (`roles_of`) |
| `edge/publisher/rezono_publisher/difference.py` | whether an assumption can change a read right (`withheld`), and the bounds it hands to the checker |
| `edge/publisher/rezono_publisher/batch.py` | the table of which column holds an element of which kind (`columns`) |
| `edge/publisher/rezono_publisher/publish.py` | what the checker's `check_role` is handed: that column table, the kinds and their parents |
| `edge/publisher/rezono_publisher/proof.py` | the piece size and fan-out of a role's proof graph (`PIECE`, `FANOUT`), bounds the checker is handed |
| `edge/publisher/rezono_publisher/views.py` | which views a role gets, and the proof bounds it hands to the checker |
| `contracts/proof.yaml` | the witnesses and proofs the engine produces and the checker verifies |

A test is a file that `scripts/red_guard.py` treats as test evidence: a `test_*` file, a fixture, a `conftest.py` and the like. A pull request that changes only tests under these paths needs no review label.

## Why these and not the rest

An error in the engine is caught by the tests, by the oracles that compute the same result independently, and by the checker, which refuses a witness that does not hold. An error in the checker is caught by none of these: an unsound proof is then accepted and published as checked. An error in read access is not caught either: a role then sees rows it may not read, and nothing downstream compares what it saw with what it should have seen. Both failures are silent, and both are hard to undo once a publication has been read.

The workflows and the compiler's semantics stay with review after landing. A wrong workflow shows up as a red or skipped check, and a wrong compiler result is caught by the oracles and by the checker. Reading them before they land would slow most of the work and add little.

## How it is enforced

- `scripts/red_guard.py` and `.github/workflows/red-policy.yml` keep such a pull request red until it carries the label `p1-read-` followed by the full id of its last commit (40 hex characters; a label may hold 50). A shorter prefix would let another commit that shares it inherit the label. A new push changes the commit, so the pull request is red again until the new commit has been read.
- The label `planner` does not replace it.
- The check is required to enter the merge queue. In the queue the guard reads no labels.
- Only the maintainer sets the label, after a reviewer has read the difference of that commit and reported no correctness finding. A finding is repaired on the same branch, and the new commit is read again.
- The label is removed from the repository once the pull request has landed.

## Considered

- **Review everything before landing.** Most changes are covered by tests and oracles, and the queue would wait on reviewers for no gain.
- **A code owner file.** It would require a second identity with review rights and a repository setting; a label bound to a commit hash needs neither and expires on every push.
- **Only the checker.** Read access fails just as silently, so it is included.
