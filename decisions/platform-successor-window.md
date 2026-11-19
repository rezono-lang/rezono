# Product succession on the first unsupported day

The old support interval ends at day 20, the first day without support. The successor must cover that same position on the same std-time axis. Starts are inclusive and ends exclusive. Each phase-out stance and succession link identifies a std-decision decision. Product stance rows use in_use, phase_out or retired. Date coverage comes from the originating platform support intervals. Use the ordinary platform support binding shipped by #234.

Four products exercise an on-time successor, a late one, a successor whose support ends on the handoff, and an absent link. Moving the late start back by a day removes only its finding and its affected services. Services using the affected product and all their running consumers, at any number of steps, are identified individually. Each proof must cite the specific decisions, support dates, product use and relevant needs.

Run `python -m pytest -q examples/platform/proof_cases/test_successor_window.py`. Implement the typed bindings and rules under `examples/platform/schema` and `examples/platform/rules`. The successor case can consume the shared service_need and std-decision bindings when present.

## Revised: impact follows every running step

The first form stopped at two steps of running dependencies. A consumer three steps away then lost its support without a finding, while the [outage chain](platform-outage-chain.md) reports the same consumer when the product fails. Both questions ask which services stop running when a provider stops, so they follow the same relation: a recursive closure over `service_need` rows with mode `run`, as `unavailable_service` in `rules/outage.dl` does. A change-only need does not carry the impact. A fixed number of steps was considered and rejected: any bound leaves the next consumer out, and the closure terminates because the services are finite.
