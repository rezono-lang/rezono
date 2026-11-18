# Outage impact distinguishes running and changing

A failure observation names a service. Each need has a consumer, provider and mode, either run or change. The derived outage_impact(cause, consumer, effect) excludes the initiating observation. A running dependency propagates a complete outage. A change-only dependency blocks modification of its consumer and stops there. A complete outage takes precedence if both apply.

The two tenant clusters use management only for changes. Their applications continue serving existing work when management fails. Losing the disk takes down the directory and management, which blocks cluster changes. Changing the west cluster's need to run makes its API fail through that cluster. An isolated monitor's failure has no consumers. Each affected row must carry a checker-valid path through the original typed needs.

Run `python -m pytest -q examples/platform/proof_cases/test_outage_chain.py`. Implement the data model and rules under `examples/platform/schema` and `examples/platform/rules`.
