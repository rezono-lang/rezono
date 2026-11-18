# Physical and nested allocations

The Run offer selection example owns the reader question `physical-or-nested`. It compares complete allocations for one workload and one purchase scope. An allocation includes the assigned workloads, the hosts they occupy, and all charges that apply to those hosts.

Ranking individual host prices would answer a smaller purchasing question. Setup charges, reserves and the number of usable hosts can change the order of the complete allocations.

## Facts and decisions

| Input | Origin and purpose |
| --- | --- |
| Workload and resource requirements | An approved probe design identifies the workload members and the resources each requires. These are requirements on the proposed installation, independent of a provider's capacities. |
| Proposed allocation and assignment | A recorded design alternative identifies the physical or nested placement and the hosts assigned to each member. It is an independently stated proposal with its own identity. Use the proposal inventory's coverage to establish which alternatives are being compared. |
| Capacity and commercial terms | Identified supplier publications, observations and binding quote records give stock, per-host capacities, account and plan limits, currency, period rates and setup charges. The evidence names the supplier, source and validity period. |
| Reserve and acceptance terms | Dated decisions by the accountable run authority specify the applicable CPU, memory and disk reserves and any adopted account, plan, cost or time limit. Provider limits retain their supplier origin separately from these adoption decisions. |
| Preference | Dated decisions by the accountable run authority identify acceptable alternatives for a workload and purchase scope. An authoritative register must establish complete coverage for that authority, workload, purchase scope and comparison date, including the decisions and supersession records needed to establish which preferences apply. |

Use `std-decision` for every reserve, limit, term and preference, with actor and date. Use `std-time` to select observations and terms valid at the comparison time, and `std-identity` when independent sources name the same host or plan differently. `std-part` relates proposed assignments to hosts and workloads.

## Derivation and publication

For each alternative, derive whether all workload members are placed. Sum their demands on each host and apply the approved reserve there. Compare the result with CPU, memory and disk capacity. Check stock and account and plan constraints for the full order. Derive the payable total from every charge, in one comparable currency, using the offer selection pack's exact amount and whole-order guarantee semantics. Shares of host capacity and a candidate's payable total are computed from these inputs.

Choose from the complete set of feasible, comparable alternatives. A single lowest payable total gives a choice. Incomplete candidate coverage, missing resource dimensions or unknown full-order costs leave the relevant comparison unknown. Eligibility always requires supported capacity and price evidence.

At a tie, establish the complete set of applicable preferences using the register's authority and coverage and `std-decision`'s `in_force_on` at the comparison date. A supersession excludes a preference when `replaced` shows that its decided successor has taken effect and the replacement is authorized for the preference's scope. Keep the authority, scope, date, coverage, standing and any replacement evidence in the proof. Missing or incomplete evidence for the applicable set leaves the tie unknown. A proven complete set with no applicable preference supports a missing-preference finding.

With a proven nonempty set, choose only if every applicable preference leaves the same single equal-price alternative. If the preferences leave several candidates or disagree about the sole candidate, report `ambiguous_preference` without choosing. Use that finding also if a preference leaves none of the tied candidates. Cite all applicable preferences and the evidence for every candidate exclusion so the choice or finding can be replayed.

Publish the reported resources and derived fit, total and comparison results. The reader question in `questions.yaml` shows the choice or the reason it remains undecided, with both sides of a tie available through `grounds` from `std-explain`. Its witnesses cite the workload design, proposed assignments, supplier evidence, the complete candidate inventory, and the applicable decisions. A reader needs access to the grounds required for that conclusion. Keep titles, descriptions and headings in the message catalogue. Rules derive the fit and choice. Adapters carry the recorded proposals and supplier evidence.

## Independent acceptance evidence

Use a handwritten workload with three members. A physical allocation places one member on each of three hosts. A nested allocation places two members on one host and one on another. Author equally priced offers of 400 minor units for each physical host and 600 minor units for each nested host, with identical billing scope. The independent totals are both 1,200 minor units. An additional feasible alternative with a strictly lower whole-order price wins even with the old preference still present.

In a separate price variant with the same scope and billing period, use whole-allocation recurring charges of 100 and 120 minor units and setup charges of 50 and 0, respectively. The independent payable totals of 150 and 120 select the second allocation even though its recurring charge is higher.

Author two independent decisions by the accountable authority for the same workload and purchase scope. Give both the same first day and no supersession. One selects only the physical candidate and the other only the nested candidate. Test on that first day. With complete coverage, each decision alone chooses its named candidate, even when that candidate is listed last. Together they are both in force and give `ambiguous_preference` with both grounds and no choice, for either record order. With both decisions naming the same single candidate, they agree and that candidate wins. A single decision naming both candidates is ambiguous. When the nested decision is instead recorded as an authorized successor that takes effect on the comparison day, the nested candidate wins and the proof shows why the physical decision ceased to apply.

Remove both preferences from a complete register for the tested scope to prove the missing-preference finding. Restore just one preference, with the candidate evidence unchanged. Withhold the register's coverage or replace it with a complete register for another purchase scope. The tie stays unknown in both variants, even though one preference is visible. A conflicting preference proved to be for another scope leaves the in-scope choice unchanged when coverage for the tested scope is complete.

For the nested host with two members, two disk demands of 80 and a decision reserve of 40 fit an observed capacity of 200. A what-if sweep of that decision over reserves of 39, 40 and 41 makes the last variant fail. In a separate counterexample, lowering the applicable account limit to two host orders excludes the three-host allocation. Withholding a capacity dimension or inventory coverage yields unknown where the comparison needs it.

Give `run/tests/test_physical_nested_allocation.py` its own acceptance case. Read the answer, alternatives and witnesses from the published pack and replay the decision sweep using the same rules. The handwritten host calculations and exact charge totals are the oracle. Supplier terms are evidence about the market captured in that fixture.
