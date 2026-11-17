# Compare two changes to the platform principles

Evaluate each scenario independently against the same fixture. Compute allowed flows from requested flows and active policy, excluding a recovery flow when its function forbids recovery access. Relaxing recovery isolation permits the previously excluded flow. Retain the raw requested flows for diagnostics.

For edge TLS termination, mark one synthetic HTTPS service path and its entry service explicitly. Replace its direct transport with client-to-entry TLS and entry-to-backend transport on the declared backend port. Leave unrelated functions alone. Author the endpoints and ports as scenario inputs since topology alone cannot identify an application path.

For each scenario return sorted added and removed sets for effective flows and their projected firewall rules. Project before taking differences so a rule used by another flow stays present. Comparing only counts would hide substitutions.
