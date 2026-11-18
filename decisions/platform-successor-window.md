# Product succession on the first unsupported day

The old support interval ends at day 20, the first day without support. The successor must cover that same position on the same std-time axis. Starts are inclusive and ends exclusive. Each phase-out stance and succession link identifies a std-decision decision. Product stance rows use in_use, phase_out or retired. Date coverage comes from the originating platform support intervals. Use the ordinary platform support binding shipped by #234.

Four products exercise an on-time successor, a late one, a successor whose support ends on the handoff, and an absent link. Moving the late start back by a day removes only its finding and its affected services. Services using the affected product and their running consumers up to two hops are identified individually. Each proof must cite the specific decisions, support dates, product use and relevant needs.

Run `python -m pytest -q examples/platform/proof_cases/test_successor_window.py`. Implement the typed bindings and rules under `examples/platform/schema` and `examples/platform/rules`. The successor case can consume the shared service_need and std-decision bindings when present.
