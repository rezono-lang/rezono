# Back up and restore independently of cluster management

Place backup producers with their data services. Put object storage on the data plane. The recovery cluster reads backups directly over the declared recovery route and restores without the management API, issuer or controller. Derive a producer-to-store flow per protected service and a recovery-to-store flow for the restore job. Select producers by their data function, with separate sourced product facts for cluster resources, database backups and secret-store snapshots.

Each data service has a dataset, storage target, schedule, retention and a governing decision. Use the time and decision packs for the evaluation date and maximum age. A June 7 backup is three days old on June 10. At a two-day limit it is too old. A missing backup requires a complete inventory of the service and target on the evaluation date. A partial or unrelated inventory leaves the outcome unknown. Keep its scope and completion in the witness.

The disposable trial captures a fresh payload and its digest, restores that exact backup and independently reads its bytes in recovery. Probe the management endpoint before and after the restore while its control plane is down. A successful trial proves the named backup only. Bind capture and readback to the same real run through the native recorder Job described in the health decision.
