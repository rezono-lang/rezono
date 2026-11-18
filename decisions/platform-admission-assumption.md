# Publish the downstream effect of withdrawing an external connection decision

In the platform pack use the same normalized request rows in both worlds.
Order requests by submission time, then tenant and service. Calculate the
capacity charged only to landed requests. The older catalog total remains
a preview of requested reservations. A withheld or refused request charges
zero. Keep loop sightings immutable even when an assumption changes admission.

For this example the additional typed inputs are `offered_cores(id, cores)`
with catalog item/size identifiers, `pool_cores(id, cores)`,
`outbound_approval(id, connection)` and `landing_sighting(id, request)`.
Publish `request_outcome(request, status)`, `landed_request(request)` and
`free_cores(pool, count)` as ordinary derived relations. The exit statuses
used by this projection are landed, review, denied and capacity.

Use the ordinary epoch publisher for main and the variant. The public platform
adapter `portal/assumption_scene.py` writes a combined scene to the store via
`publish_scene(store, pack, before, after, role, relations)` and returns its
object key. Its changes contain relation, full key, signed unit weight and
the supporting witness from the corresponding side. Positions contain side
(the manifest ID), relation, full key, band and slot. Reuse a position for
the same row in both worlds. Preserve separate positions for different rows
in the combined picture, including rows no longer present.

An offline example uses a seven-core pool and three actual request files.
With approval the six-core cluster-and-database delivery lands first. A
cross-tenant connection is denied. Four more cores cannot fit. Removing only
the approval admits the last request and leaves three cores. Reversing the
first and last submission times supplies an independent ordering control.
