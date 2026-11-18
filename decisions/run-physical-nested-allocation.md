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
| Preference | A dated decision may identify acceptable alternatives for a particular workload, purchasing scope and time. A complete decision register establishes whether an applicable preference is absent. |

Use `std-decision` for every reserve, limit, term and preference, with actor and date. Use `std-time` to select observations and terms valid at the comparison time, and `std-identity` when independent sources name the same host or plan differently. `std-part` relates proposed assignments to hosts and workloads.

## Derivation and publication

For each alternative, derive whether all workload members are placed. Sum their demands on each host and apply the approved reserve there. Compare the result with CPU, memory and disk capacity. Check stock and account and plan constraints for the full order. Derive the payable total from every charge, in one comparable currency, using the offer selection pack's exact amount and whole-order guarantee semantics. Shares of host capacity and a candidate's payable total are computed from these inputs.

Choose from the complete set of feasible, comparable alternatives. A single lowest payable total gives a choice. At a tie, an applicable preference must leave exactly one of the equal-price alternatives. The choice cites the other candidates and the evidence for every exclusion. A complete register with no applicable preference supports a missing-preference finding. A preference that leaves several tied alternatives supports an ambiguous-preference finding. Incomplete coverage, missing resource dimensions or unknown full-order costs leave the relevant comparison unknown. Eligibility always requires supported capacity and price evidence.

Publish the reported resources and derived fit, total and comparison results. The reader question in `questions.yaml` shows the choice or the reason it remains undecided, with both sides of a tie available through `grounds` from `std-explain`. Its witnesses cite the workload design, proposed assignments, supplier evidence, the complete candidate inventory, and the applicable decisions. A reader needs access to the grounds required for that conclusion. Keep titles, descriptions and headings in the message catalogue. Rules derive the fit and choice. Adapters carry the recorded proposals and supplier evidence.

## Independent acceptance evidence

Use a handwritten workload with three members. A physical allocation places one member on each of three hosts. A nested allocation places two members on one host and one on another. Author equally priced offers of 400 minor units for each physical host and 600 minor units for each nested host, with identical billing scope. The independent totals are both 1,200 minor units. A single preference selects its named candidate, including when it is listed last. Removing that preference from a complete register leaves both candidates tied. A preference covering both candidates gives the ambiguous result. An additional feasible alternative with a strictly lower whole-order price wins even with the old preference still present.

For the nested host with two members, two disk demands of 80 and a decision reserve of 40 fit an observed capacity of 200. A what-if sweep of that decision over reserves of 39, 40 and 41 makes the last variant fail. In a separate counterexample, lowering the applicable account limit to two host orders excludes the three-host allocation. Withholding a capacity dimension or inventory coverage yields unknown where the comparison needs it.

Give `run/tests/test_physical_nested_allocation.py` its own acceptance case. Read the answer, alternatives and witnesses from the published pack and replay the decision sweep using the same rules. The handwritten host calculations and exact charge totals are the oracle. Supplier terms are evidence about the market captured in that fixture.
