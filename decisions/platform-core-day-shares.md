# Share a monthly platform cost by observed core-days

A monthly platform decision supplies an ID, inclusive start and exclusive end
(day ordinals), and integer cents. A loop observation supplies its own ID,
delivery, tenant, day and observed core count. Zero closes an interval. Carry
the last observation into the month and stop at month end. An observed resize
starts a new interval that day. Requested sizes do not set observed usage.

An independent `observed_delivery_coverage` record supplies its own ID,
inclusive `start_day` and exclusive `end_day`. It attests that the platform's
inventory included the deliveries already active at the start and all changes
throughout that interval. A month needs a coverage record spanning the entire
billing interval. If coverage is missing or partial, the month has no share
or balance. The monthly cost decision does not attest to inventory coverage.

Derive `shared_cost_share(month, owner, core_days, numerator, denominator)`
in the platform pack. Numerator and positive denominator are reduced integers
in cents. Positive usage owners receive their proportional shares. At proven
zero usage the platform receives the whole amount. Derive a separate
`shared_cost_balance(month, total_numerator, total_denominator)` by summing
the resulting shares; compare that sum with the decision. An emitted copy of
the input amount would not verify the allocation. Direct catalog prices
describe a different charge.

The offline oracle enumerates individual days and uses exact fractions.
The acceptance test varies the price and one observed resize, reverses input
order, and holds January's cost and observations fixed while its coverage is
full, missing, or partial.
