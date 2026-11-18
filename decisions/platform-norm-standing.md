# Derive platform norm standing from valid rulings

At a stated reference date, report the latest valid ruling for each required norm. Keep conflicting judgments, missing registrations and registrations based only on proposals visible to readers.

## Inputs and origins

| Input | Origin and reason to keep it |
| --- | --- |
| Norm and required scope | A design or governance decision establishes what is required for an identified subject. Declare a typed norm scope only where existing decisions cannot express the requirement. That independently stated scope is needed to identify a missing judgment. |
| Ruling | An identified authority issues a typed judgment about the norm and subject. Reuse the `std-decision` record for authority, decision date, validity, proposals and replacements. A typed ruling binding specifies the judgment the authority actually made. The result of applying other rulings cannot reconstruct it. |
| Registration inventory and coverage | An independent register supplies its dated entries as reference evidence. A scoped enumeration receipt can attest coverage for a specific revision and cutoff. Retain the register's own identity and position. Its listing state does not give a ruling validity. |

A norm binding describes an obligation. A ruling binding describes an act of judgment. A completeness receipt describes what a reader actually covered. Add each kind only where its assertion is absent from the existing model and cannot be derived. Derive current standing, conflict and missing registration from the recorded grounds.

## Rules and proof

Use `std-decision` standing and `std-time` on the supplied reference date. Compare the effective starting dates of valid judgments for the same norm and subject. An expired, withdrawn, superseded or proposed judgment cannot determine current standing. The decider, validity, stated outcome and compared judgments appear in the witness. Receive order and identifier spelling have no effect on selection.

Independently valid conflicting judgments remain a finding even when the latest valid judgment settles the standing. If equally recent valid judgments disagree, publish unknown with the conflict reason and both keys. When tied judgments agree, publish that standing and preserve their grounds. A different date or ordering policy requires a dated decision with a stated decider.

Compare authoritative judgments and the independently recorded inventory within the exact scope. Publish missing registration only with a positive coverage witness and the checked absence. Treat incomplete coverage as unknown. Preserve a distinct reason for a registration that only relates to proposals. No judgment or no register match can imply compliance. Retain the proof on both sides of a drift finding and apply the normal role proof visibility rules.

## Acceptance

The reader question `norm-standing` and `test_norm_standing.py::test_norm_standing` read current standing and reasons from the publication. Independently author older and latest valid judgments, a later proposal, a later expired or withdrawn judgment, equal-time agreeing and disagreeing judgments, and separate complete and incomplete inventories. Reverse input order in a countercase. Require exact states, both contradiction witnesses, and distinct covered-missing, uncovered and proposal-only reasons. Use independently stated expected rows to check the publication.

Taking the last register line can promote a proposal and make order significant. Ordering authoritative judgments by effective date and using the registry as reference lets the publication explain both the valid result and the registration evidence.
