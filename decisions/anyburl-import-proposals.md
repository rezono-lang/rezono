# Keep AnyBURL as a manual proposal experiment

Run AnyBURL through the manually dispatched platform probe for research and proposal review.
Use ordinary import inputs in the default workflow. A reviewer can submit a candidate from AnyBURL
through the ordinary rule proposal process. [Import rule proposal decision](import-rule-proposals.md)

The pinned experiment recorded 1,543 rules. Of the 575 with confidence at least 0.9, 464 could be
checked in the rule language and none qualified. The exact engines found excess rows in two candidates.
Another 245 left unverified remainder origins, and 217 failed the canonical byte bound. No inexact
candidate fell inside the 5% exception window. Evaluation of the retained raw rules reproduced the
report byte for byte. [Run report and archived evidence](../probes/anyburl/README.md#recorded-run)

AnyBURL confidence can order candidates for a reviewer. Eligibility requires a successful comparison
against the same pinned typed facts in DuckDB and Soufflé, verified original sources for the retained
rows, and a strict reduction in canonical bytes after charging the support facts. A proposed exception
remains a candidate for review until a rule in the pack derives it with a proof.

A later decision can revisit default integration when a concrete import question yields reproducibly
eligible proposals on representative pinned data. Preserve the raw output and keep the exact comparison
and ordinary review in that evaluation.
