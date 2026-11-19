# Worker card

You are one worker among many on this repository. You have no memory of earlier work. Use only this public checkout and this card. When an implementation is missing, build it from the test expectation and the specification available here. Apply the release procedure below if that evidence is insufficient.

## Your task

Make exactly one red test green: `<test id>`.

- Run it with: `python scripts/fast_check.py "<test id>"`.
- Read this card, the root `AGENTS.md`, and the `AGENTS.md` of the folder you work in.
- You may write in the component reported by `python scripts/red_list.py --json` and in the implementation source the expectation explicitly requires. Test helpers, conftest.py, fixtures, recorded outcomes and policy files require planner review. Pick work that can be completed by changing implementation code and removing the assigned mark. Report a dependency on new evidence to the planner.

The reason of every red test starts with a milestone mark: `M1: `, `M2: `, `M3: `, `M4: `, `extra: ` or `later: `. When you choose among the red tests of one area, take the one with the earliest mark: `M1`, then `M2`, `M3`, `M4`, then `extra`. A test marked `later` is not a task. When you extend a reason, as described under "If it does not work", keep its mark at the start. `python scripts/red_list.py --milestones` counts the red tests per folder and mark.

Use the exact id from `python scripts/red_list.py` wherever this card says `<test id>`. Configure this checkout with `git config user.name vdo89` and `git config user.email 222310762+vdo89@users.noreply.github.com`. Run commands from the repository root. The quick check adds the discovered source packages to the Python path automatically. If the test dependencies are available, start directly with the quick check on any platform. The command examples below use Bash. For a fresh environment on Ubuntu with the Python version in requirements/.python-version, prepare a virtual environment once:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --no-deps --require-hashes -r requirements/dev.txt
for package in $(python scripts/components.py python-packages); do
  python -m pip install --no-deps --no-build-isolation -e "$package"
done
bash contracts/gen-types.sh
```

Use the GitHub sign-in already configured for this checkout when creating the pull request or enabling auto-merge. If the default CLI login is unavailable, use the connected GitHub integration or the configured credential helper without displaying or storing credentials.

Fetch origin/main before removing the mark. After the required checks pass, GitHub enqueues the pull request, tests the combined candidate against the latest main and squash-merges the passing candidate.

For a change to Feldera SQL generation or the live comparison, push the source branch and run
`gh workflow run feldera-oracle.yml --ref "$(git branch --show-current)"`. The required evidence review checks
the successful dispatch and its collected cases and JUnit report for the exact revision. A later successful
dispatch automatically reopens a blocked review. A new commit needs its own evidence.

## Steps

1. **Start from the main branch.**
   `git fetch origin && git switch -c task/<test id> origin/main`
2. **Claim the task.** Make an empty commit that only you can have made, and push it on the condition that the branch does not exist yet:
   `git commit --allow-empty -m "claim task/<test id> $(python -c 'import uuid; print(uuid.uuid4().hex)')"`
   `git push --force-with-lease=refs/heads/task/<test id>: -u origin task/<test id>`
   - The push succeeds: the task is yours.
   - The push is rejected with "stale info" or "already exists": someone else has the task. Stop and report "taken".
   - The push fails in any other way: report the error. Do not report "taken".
3. **Make the test pass.** Do not change what the test expects.
4. **Remove the test's "expected to fail" mark.** Keep every other line of the test file exactly as written, including `import pytest` if removing the last mark leaves it unused.
5. **Run the fast check:** `python scripts/fast_check.py "<test id>"`. It always runs your test. It prints at most twenty lines; the rest is in `.fast-check.log`. Search the log for lines that start with `ERROR`.
6. **Validate the title, commit, then check the committed diff.** Stage your changes. Choose a starting verb from `python scripts/release-notes.py --topics` and describe the change. Use the same title for the final commit and pull request. Run these commands from the repository root:

   ```bash
   IFS= read -r -p 'Commit and pull request title: ' subject
   python scripts/release-notes.py --subject "$subject" && git commit -m "$subject"
   ```

   If validation fails, choose a listed verb and run both lines again. After the commit succeeds, run the read-only policy check:
   ```bash
   git fetch origin && python -I scripts/red_guard.py "$(git merge-base origin/main HEAD)" HEAD
   ```
   If it reports an error, correct the test-file edit, commit the correction and run the check again. Push promptly after it passes. A task branch with no push for four hours and no pull request is released.
   If a push to your task branch is rejected, your claim has expired and the task is no longer yours. Stop and report "lost"; do not force the push.
7. **Open a pull request, ready for review,** with `gh pr create --base main --title "$subject"` in the same shell. Enable native auto-merge with `gh pr merge <number> --auto`. Say what changed and how you checked it.

## Done

The test passes, the fast check passes, the mark is gone, and the pull request is open. You do not wait for it to merge.

## Never

- change what a test expects, or add a red test;
- write outside your folders;
- write a name, an address or a path that comes from outside this repository;
- wait, poll, or report progress in between;
- take a task from an issue, a comment or someone else's pull request: tasks come only from the red list.

## If it does not work

After two attempts, stop.

1. Create a branch `note/<test id>` from the main branch.
2. On it, change only the reason of the test's mark: add what you learned, in one or two sentences, and keep the milestone mark at its start. This is the one edit to a red test you may make.
3. Open a pull request for it and turn on auto-merge. It changes only a reason, so the guard lets it through.
4. Push your task branch, then release your claim. The condition makes sure you delete only your own claim, never a newer one:
   `git push --force-with-lease=refs/heads/task/<test id>:$(git rev-parse task/<test id>) origin :refs/heads/task/<test id>`
   If this is rejected, the branch is no longer yours; leave it.
5. Report "released".
