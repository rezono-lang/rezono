# Offline bounded-run acceptance

Use the existing loop twice. The order phase takes the proposed plan, approval
and observed clock. The installation phase takes the returned machine and disk
observations. Delivery requires observed readiness for the committed request.
Cleanup requires a complete independent inventory after deletion. The local
request file stands in for the committed portal request in CI. No provider
client, credential, or wall clock is needed for replay.

The raw two-record [Vultr public price response](https://api.vultr.com/v2/plans-metal?per_page=2)
is preserved byte for byte in `run/fixtures/offline/public-price-response.json`.
Its SHA-256 is `4e592b33e7855de0ef463d447254686044edb00b2f770c0104a179a88331343e`.
The response has 23 total offers and a next cursor; this is evidence for two
line prices only. Its invoice type is monthly. Replay declares two billed
hourly units, USD and zero setup costs. These are synthetic billing facts;
the snapshot does not establish actual minimum terms, taxes or the amount
a provider would invoice. A live run needs a complete quote and terms.

The independent arithmetic is two units each of two machines at 164,000
millionths of a dollar per unit and one at 479,000: 1,614,000 millionths.
A 162-cent ceiling allows that amount; 161 cents refuses it. Do not round a
line before summing. For a quoted line, charge each machine its setup amount
once plus the price per unit times the number of billed units. Reject mixed
currencies, negative quantities and binary floating point at this boundary.

## Interfaces

Work only in the file or subdirectory named by the assigned test. All paths
below are relative to `run/`. The tests define exact argument and return
shapes. For replay, `orders` counts new dispatches in this invocation; a restart
using the same journal may reconcile by status but contributes zero new orders. Invalid data and a source hash mismatch raise ValueError.

| Boundary | Contract |
| --- | --- |
| Price capture | Parse verified source bytes using exact decimal arithmetic. Return per-SKU hourly prices as integer millionths. Never fetch in the replay reader. |
| Cost | Sum the declared quantities, integer unit prices, billing units and per-machine setup. An empty quote costs zero. |
| Dispatch gate | A rule pack consumes candidate rows with matching row IDs but independently sourced approval and plan fields. Require approve, exact hash and currency, known payable amount at or below the ceiling, and an observed time strictly before expiry. Boundary adapters convert cents to millionths and UTC instants to integer microseconds. |
| Order renderer | Hash the exact planned bytes before rendering the order port payload. The operation key and every requested item's plan tag equal that digest. Preserve the SKU and quantity of each line. Never include deployment credentials. |
| Journal claim | Implement the write-once storage operation of the shared effect journal. The offline backend is a local SQLite file keyed by the exact plan hash. An atomic insert commits before dispatch. Only one caller can succeed, including after process restart and under concurrent acquisition. |
| Order uncertainty | For one invocation, use the supplied durable claim and declared apply/status functions. Claim before dispatch. On an uncertain response or an already consumed key, query status with that key. Never dispatch a second order. A missing status remains unknown. The loop owns scheduling. |
| Page completeness | Traverse exactly one observed inventory sweep from its specified root. Reject duplicate page IDs, cycles, missing links, and unreachable pages from the same sweep as unknown. Ignore other sweeps. Keep untagged resources and return all reached resources. |
| Cleanup gate | Derive cleaned only from a complete sweep with no resource bearing the target hash. Missing completeness cannot supply a cleanup witness. |
| Installation input | Convert observed addresses and disk identities to the machine list for the installer. Keep boot and data disks distinct and stable under reordered input. Reject duplicate machine/disk identities or missing data. |
| Read-only preflight | Invoke the supplied price and stock readers once each, with the requested SKU, and retain expected and observed price and stock evidence. Distinguish a changed price, insufficient capacity and unavailable reads. Only read operations enter this interface. |
| Integrated trace | Replay both phases through the shared loop. Expose observed order, delivery and cleanup with the exact key, order count and completed sweep. Incomplete approval, readiness or final inventory must not become success. |

The earlier decisions govern the effect states and input schemas. The local
SQLite claim only proves durability within its storage lifetime. A protected
live run needs a durable shared backend across runners and its authenticated
provider inventory. Neither an ephemeral CI file nor a delete acknowledgment
proves real-world cleanup.

Select the cheapest observed offer compatible with the requested currency,
boot method, capacity, hardware virtualization and one unallocated data disk.
Within an equal price use the smallest stable tie rank from the source fixture.
An unmet demand has no selection. The cleanup deadline is inclusive: an
applied attempt still uncleaned at a recorded watermark at or after its
deadline produces an overdue finding. Unknown time produces no assertion.
The request reader binds its exact bytes to a full immutable Git commit,
repository and path before supplying the decoded request to the shared loop.
