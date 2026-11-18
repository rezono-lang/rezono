# Exercise conflicting identity evidence in an isolated fact state

The platform publishes two source identifiers for one database. Both sources record
the standard edition and the postgres engine. Their explicit identity link and
both source statements belong in the ordinary facts. The published state has no
identity conflict.

In the identity acceptance test, change only the edition asserted by source B to
enterprise in a temporary copy. The pinned std-identity theory must report the
two directed edition conflicts and the checker must trace each to the identity
link and the two incompatible statements. The real publisher must reject that
copy and accept the ordinary state. Putting the disagreement in the ordinary
facts would block every publication of the platform. A schema diagnostics file
alone would only check the input structure and would miss the rule invariant.
