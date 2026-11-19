---
decider: [loop]
decided_on: 2026-11-19
valid_from: 2026-11-19
state: in_force
subject: decision-records
---

# Give every decision a head that the build pack reads

A decision in this folder is running text: who took it, on which day, whether it still stands and what it replaces are sentences, so no rule can read them. [`std-decision`](../packs/std-decision/README.md) already has the kind for a decision and the rules for "in force on a day", and the build pack imports it to read the claim lease, the track priority and the queue limit ([build reconciliation](build-reconciliation.md#task-and-queue-observations)). This decision gives each decision file a typed head in the words of that pack, makes the heads an input of the build pack, adds two rules that read them, and sets a budget for the decisions that have no head yet. [Decision record](../packs/std-decision/schema/decision.yaml) · [Leak budget](../scripts/leak_check.py)

## 1. The head

A head is a YAML block at the very top of the file, between two lines `---`. One empty line follows it, then the title line `# <title>`. The title is what was decided; it is the `title` of the decision. The file name without `.md` is its `id`.

| Field | Value | Required | `Decision` slot |
| --- | --- | --- | --- |
| `decider` | a non-empty list of deciders (section 2) | yes | `decider` |
| `decided_on` | the day it was taken, `YYYY-MM-DD` | yes, except when `proposed` | `decided_on` |
| `valid_from` | the first day it applies, `YYYY-MM-DD` | yes, except when `proposed` | `valid_from`, `valid_from_day` |
| `valid_until` | the first day it no longer applies, `YYYY-MM-DD` | no | `valid_until`, `valid_until_day` |
| `state` | `proposed`, `in_force`, `superseded` or `withdrawn` | yes | `state` |
| `supersedes` | a non-empty list of ids of decisions with a head | no | `supersedes` |
| `subject` | one lowercase slug, words joined by `-` | yes | `subject` |

A day is written as a plain YAML date, without quotes. A list is written in flow form, as `[a, b]`. No other field is allowed, and no field is empty. The rules of `std-decision` count from `valid_from`: a decision without that day is in force on no day, so every decision that was taken names it. `valid_until` comes after `valid_from`.

Decisions that succeed each other share a subject. A head that says `superseded` is named in the `supersedes` of a decision with a head; otherwise `std-decision` reports it as `superseded_in_force`, which blocks a publication. When a decision replaces another, its head names the other in `supersedes`, and the other's head changes its state to `superseded` in the same pull request.

## 2. Who decides

The decider is the track that took the decision: `core`, `language`, `platform`, `loop`, `k8s-admission` or `run`. It is `owner` where the root [AGENTS.md](../AGENTS.md) leaves the choice to the owner, as for a dependency under another licence. A decision taken by two tracks names both.

| Decider | Usually decides on |
| --- | --- |
| `core` | the compiler, checker, canon, admission, edge, contracts, publication and the tests and docs of the engine |
| `language` | the language, the standard packs and the content of the examples |
| `platform` | the platform example |
| `loop` | the loop, `std-loop`, the build pack and the formal models |
| `k8s-admission` | the Kubernetes admission policy |
| `run` | the runs under `run/` |

## 3. The days of an existing decision

Whoever gives an existing decision its head takes `decided_on` and `valid_from` from the commit that brought the file to `main`: the last line of `git log --diff-filter=A --follow --format=%cs -- decisions/<file>`. A later change of the text does not move those days; a new decision that supersedes it does.

## 4. The heads as input of the build pack

An adapter, `loop/build_decision_capture.py`, reads the heads at every build run, from the same tree as the other observations of that run. Nothing it makes is committed.

- `decision_rows(root)` reads `root/decisions/*.md` except `AGENTS.md`. A file without a head gives no row. A file whose first line is `---` and whose head breaks section 1 raises `ValueError` with the file's path, so a broken head is never read as a missing one. Each head gives one `decision` row with the fields of section 1: the `id` and `title`, the lists `decider` and `supersedes` (left out when absent), the days as `YYYY-MM-DD` strings, and each day also as the whole number `YYYYMMDD` in its `*_day` slot. Each subject gives one `subject` row whose `title` is its slug. Rows are sorted by `id`.
- `citation_rows(root, paths, red_tests, *, run, observed_at, source)` says which file names which decision. `paths` are the tracked files of the tree, relative to `root`, and `red_tests` are mappings with the `id` and `reason` of each red test, as `scripts/red_list.py --json` gives them. It gives one `build_citation_scan` row `{id, run, observed_at, source}` for the complete read, one `build_decision_citation` row `{id, scan, path, decision}` for each other file whose text names a decision with a head, and one `build_red_citation` row `{id, scan, test, decision}` for each red test whose reason names one. A text names a decision when it contains `decisions/<id>.md`; a file in `decisions/` also names it with a relative link `](<id>.md`. A file does not cite itself. A decision without a head is not cited, because it has no row.

## 5. Two rules in the build pack

Both read the decisions on the policy date of a verified cut (`build_policy_date_at_cut`), and only through a citation scan of that run whose `observed_at` is the cut tick. The kinds `BuildCitationScan`, `BuildDecisionCitation` and `BuildRedCitation` carry the fields of section 4.

- `build_red_cites_replaced(run, test, decision, successor)`: a red test whose reason names a decision that `successor` has replaced on that day (`replaced` of `std-decision`). It is a finding with its witness: the scan, the citation and the replacement are the proof. A reason that names a decision whose successor has not yet taken effect is no finding.
- `build_uncited_decision(run, decision)`: a decision in force on that day (`in_force_on`) that no test, document, script or other decision names in that scan. It is a warning. Without a scan at the cut the absence is unknown, so there is no row.

Both are published with the other build relations. Neither blocks a pull request.

## 6. Decisions without a head

A new decision has a head, and so does a decision whose text changes. `loop/decision-head-budget.json` lists every decision without a head with the SHA-256 of its bytes, and `loop/tests/test_decision_heads.py` requires every decision without a head to be listed there with exactly those bytes, and every head to follow section 1. So a new file without a head, or a changed file without one, fails the check, and a head that adds an unknown field or leaves out `valid_from` fails too. The budget is an upper bound per file, not an exact list: a listed decision that gains a head or goes away stays green, so pull requests that land in the same merge group do not break each other, and its line can go in any later pull request. The budget only goes down: the test holds a ceiling, the count when the budget was set. The loop component reads `decisions/`, so a pull request that changes only a decision runs this check.

No one fills the heads at once. Each track gives its own decisions a head when it touches them.

## Alternatives

- **A head as a table or a list under the title.** It reads like the rest of the text, but nothing marks where it ends, and a Markdown table has no types. YAML front matter is what [MADR](https://adr.github.io/madr/) uses, and GitHub shows it as a table.
- **A separate facts file per decision.** It would keep the text unchanged, but the head would drift from the text it describes, and every decision would be two files.
- **A generated `decision` facts file in Git.** Generated output does not go into Git (root AGENTS.md); the adapter reads the heads at every run instead.
- **Deciders as people.** The repository records no persons; the track is the party that answers for a decision here.
- **Fill every head now.** It would put a guess on about two hundred decisions. The day of the first commit is known, but the subject, the deciders and what each one replaces need the reading of the track that owns it.
