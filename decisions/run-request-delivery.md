# A committed request starts the delivery trace

A consumer submits a request through Backstage. A scoped integration writes
the request artifact to a Forgejo repository. Record repository identity,
commit, path and the digest of the exact file bytes as its source. A portal
success message alone does not establish that Forgejo accepted the request.

Pass those bytes and their source to the ordinary run-scoped reconciliation
loop. Keep the run ID associated with the request through planning, observed
installation and delivery. Report delivery only when matching observed
readiness evidence exists for that request. Replaying the same committed
request retains its identity. Incomplete evidence leaves delivery unknown.
The request cannot approve spend or relax the plan hash, ceiling or expiry.

The operator-triggered integration plan includes the portal and request
repository in the dependency graph. Its acceptance trace follows a submitted
request through a verified repository commit to a ready delivered object,
then includes both services in inventory and cleanup. Treat provider, portal
and repository credentials as externally supplied references.

CI reads a synthetic local request file. Supply its exact bytes to the same
consumer-side boundary and check the request-to-delivery trace against
recorded observations. This deliberately exercises no portal UI, Forgejo
authentication or remote repository write. Live service interoperability
requires separate evidence from the operator-triggered run.

An alternative request encoded only as form fields would require separate
replay and production ingestion paths, and would lose the committed artifact
as an independent provenance anchor.
