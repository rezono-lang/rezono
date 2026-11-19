# Working in decisions

Record one design choice per file, with alternatives and rationale.

Start a new decision, and a decision whose text you change, with its head: a YAML block between two `---` lines, then one empty line and the title line `# <title>`. The head names `decider`, `decided_on`, `valid_from`, `state` and `subject`, and `supersedes` and `valid_until` where they apply, in the words of `std-decision`. The [decision heads decision](decision-heads.md) says what each field holds, who the decider is, and which days an existing decision takes. When a decision replaces another, set the other's `state` to `superseded` in the same pull request.
