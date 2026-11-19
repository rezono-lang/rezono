# Standstill alert after two hours

Open one issue labeled `standstill` when no pull request was opened or merged for more than two hours while red tests that are not marked `later: ` remain. The hourly cleanup workflow runs `scripts/standstill.py`, and the limit is the single constant `STANDSTILL_HOURS` in that script.

## What counts

- Progress is the later of two moments: the most recent pull request opened and the most recent pull request merged. Pull requests from branches that start with `dependabot/` do not count, because they arrive on a schedule whether or not anyone works on the open red tests.
- Waiting work is the number of expected-red tests that `scripts/red_list.py` lists, minus those whose reason starts with `later: `. With no such test there is nothing to stall on, and the script stays silent.
- An open `standstill` issue is closed by the next run after a pull request is opened or merged later than the issue. While it is open, the script opens no second one.

## Why two hours

One hour is too close to the usual time between opening a pull request and merging it through the queue. The alert would fire during ordinary review. Four hours or more lets a stall go unnoticed for half a working session, and the hourly schedule adds up to another hour before the issue appears. Two hours is the shortest window that ordinary pull request traffic does not cross, and the issue appears within three hours of the last progress.

## Alternatives considered

- **Alert on age of the oldest red test.** That measures backlog, not standstill: a long-lived red test with active work around it is not a stall.
- **Count Dependabot pull requests.** They would keep the alert quiet during a real stall.
- **Run the engine or a pack to count red tests.** The alert must work when the build itself is red, so it reads test marks from the source the same way `scripts/red_list.py` does and depends on neither.
- **Comment on or reopen an earlier issue.** One fresh issue per stall keeps the moments and the count in the issue body accurate.

## Permissions

The job gets `contents: read` to read the test marks, `pull-requests: read` to read the two moments, and `issues: write` to create the label, open the issue and close it. The current moment is a command-line argument so that tests can run the script with fixed times.
