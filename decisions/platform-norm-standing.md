# Derive platform norm standing from valid rulings

At a stated reference date, report standing from a ruling whose latest valid position is established at the stated cutoff. Report unknown when the authority intake leaves that comparison open. Keep conflicting judgments, missing registrations and registrations based only on proposals visible to readers.

## Inputs and origins

| Input | Origin and reason to keep it |
| --- | --- |
| Norm and required scope | A design or governance decision establishes what is required for an identified subject. Declare a typed norm scope only where existing decisions cannot express the requirement. That independently stated scope is needed to identify a missing judgment. |
| Ruling | An identified authority issues a typed judgment about the norm and subject. Reuse the `std-decision` record for authority, decision date, validity, proposals and replacements. A typed ruling binding specifies the judgment the authority actually made. The result of applying other rulings cannot reconstruct it. |
| Authority intake and coverage | A separate receipt or other verified evidence establishes what the determining authorities covered for this norm, subject and cutoff. Pin its origin, authority scope, revision and cutoff independently of the candidate judgment. |
| Registration inventory and coverage | An independent register supplies its dated entries as reference evidence. A scoped enumeration receipt can attest coverage for a specific revision and cutoff. Retain the register's own identity and position. Its listing state does not give a ruling validity. |

A norm binding describes an obligation. A ruling binding describes an act of judgment. A completeness receipt describes what a reader actually covered. Add each kind only where its assertion is absent from the existing model and cannot be derived. Derive current standing, conflict and missing registration from the recorded grounds.

## Rules and proof

Use `std-decision` standing and `std-time` to evaluate validity on the supplied reference date. Compare the effective starting dates of valid judgments for the same norm and subject at the stated authority cutoff. An expired, withdrawn, superseded or proposed judgment cannot determine current standing. Receive order and identifier spelling have no effect on selection.

Establish a known standing only when independent authority evidence covers all judgments that can determine it for that norm and subject through the exact cutoff. A narrower proof may instead establish that any unenumerated judgment is ineligible or strictly earlier than the selected effective date. The proof must rule out an unseen later or equally recent valid candidate and cover the validity evidence for the selected judgment, including withdrawals and replacements. The authoritative cutoff must be independently established for the requested reference date. The time of the last received row does not establish coverage. With missing, stale, or mismatched authority evidence, report unknown for incomplete authority coverage. With complete coverage and no valid judgment, report unknown for lack of a valid ruling. A complete register of registrations only establishes what was registered.

The standing witness names the authority scope, reference date and cutoff, the evidence that closes the comparison, and the selected and compared judgments with their deciders, validity and stated outcomes. Independently evidenced valid judgments that conflict remain a finding even if the ordering settles standing. Once the latest effective date is established, disagreement at that date yields unknown with the conflict reason and the establishing keys. If all tied judgments agree, retain their grounds and publish their standing. A different date or ordering policy requires a dated decision with a stated decider.

Compare authoritative judgments and the independently recorded registration inventory within the exact scope. Publish missing registration only with the register's positive coverage witness and the checked absence. Treat incomplete register coverage as unknown for registration and preserve a distinct reason for an entry that only relates to proposals. Finding a registration supplies no judgment of compliance. Retain the proof on both sides of a drift finding.

Apply the normal role proof visibility rules to both comparisons. Publishing a known standing to a role requires a readable proof of the judgment and of the authority comparison. A role's filtered intake supplies no scope closure. Any visible unknown reason must avoid revealing hidden judgments, and a visible conflict finding requires readable grounds for that conflict. [Witnessed read completeness](witnessed-read-completeness.md) · [Required publication conclusions](role-publication-requirements.md)

## Acceptance

The reader question `norm-standing` and `test_norm_standing.py::test_norm_standing` read standing and reasons from the publication. Use independently stated expected rows and grounds for the following cases.

- At a reference date of 1 March, the intake shows a valid passing judgment effective 1 January. Keep the same complete external register in each case. An unseen valid failing judgment effective 1 February would change standing to fail. An unseen valid failing judgment effective 1 January would instead create a latest-date conflict. With the same visible inputs and incomplete authority coverage, expect unknown for incomplete authority coverage in each case.
- With verified authority coverage for the exact scope and cutoff, expect pass in the January-only case, fail in the February case, and unknown with both keys in the conflicting January case. Cover an agreeing tie, a later proposal, a later expired or withdrawn judgment, and reversed input order. Also confirm pass when an independent proof establishes that every unenumerated judgment is earlier or ineligible. Check both sides of a conflict and the actual coverage receipt or independent exclusion proof in the standing witness.
- Replace the authority evidence with a cutoff that ends before the requested one, evidence for another norm or subject, or evidence that excludes later judgments but leaves equally recent ones possible. Expect unknown for incomplete authority coverage. For a reader missing proof grounds, expect no known result and an identical visible answer whether an unreadable competing judgment exists or is absent.
- Vary register coverage independently of authority coverage. Require distinct results for covered missing registration, incomplete register coverage and proposal-only registration. Hold the authority evidence fixed when varying the register, and keep the register fixed when varying authority coverage.

Taking the last register line can promote a proposal and make order significant. Selecting from a proven authority comparison and checking registration separately lets the publication explain both findings.
