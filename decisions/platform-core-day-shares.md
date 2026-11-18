# Share a monthly platform cost by observed core-days

A monthly platform decision supplies an ID, inclusive start and exclusive end
(day ordinals), and integer cents. A loop observation supplies its own ID,
delivery, tenant, day and observed core count. Zero closes an interval. Carry
the last observation into the month and stop at month end. An observed resize
starts a new interval that day. Requested sizes do not set observed usage.

Derive `shared_cost_share(month, owner, core_days, numerator, denominator)`
in the platform pack. Numerator and positive denominator are reduced integers
in cents. Positive usage owners receive their proportional shares. At zero usage
the platform receives the whole amount. Derive a separate
`shared_cost_balance(month, total_numerator, total_denominator)` by summing
the resulting shares; compare that sum with the decision. An emitted copy of
the input amount would not verify the allocation. Direct catalog prices
describe a different charge.

The offline oracle enumerates individual days and uses exact fractions.
The acceptance test varies the price and one observed resize, reverses input
order, and includes a month before any observed delivery.
