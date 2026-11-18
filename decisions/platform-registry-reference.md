# Reference registry for the platform inventory

The inventory gives service `reg` the product identifier `registry`. It serves the registry function. Builders and workloads consume that function. Choose Distribution v3.0.0 as the reference implementation for this service. Distribution is an OCI registry, so this choice preserves the example's function, consumers and service identity. A suite with an integrated catalogue or scanner would add components beyond the service model.

Keep `registry` as the inventory product key. Give the selected supplier release its own identity, `distribution-3.0.0`, and pin `reg` to it. Bind its project-source notice as `exact-scenario-release`. The tag's LICENSE declares Apache-2.0. The original response is 11,325 bytes with SHA-256 `cb5e8e7e5f4a3988e1063c142c60dc2df75605f4c46515e776e3aca6df976e14`. Record the full notice digest, preserve its source sidecar and publish the information through the catalogue. Image contents and a running deployment require separate evidence. [Distribution v3.0.0 licence](https://raw.githubusercontent.com/distribution/distribution/v3.0.0/LICENSE)

A service pinned to a different registry release needs its own matching notice. Without a selected release the catalogue may show the notice as a reference. The existing model represents these cases with `release`, `pin`, `licence_release_binding` and `vendor_licence_notice`. The release-order day is a scenario input, as are the registry's port, storage and identity requirements.

The pin also includes `reg` and `distribution-3.0.0` in the running-release inventory used by the support query. The supplier's LICENSE establishes the source licence. The example contains no vendor support statement for this release, so its support state is `unknown` under the [support-window decision](platform-support-window.md).

## Remaining inventory decisions

| Inventory key | Evidence to obtain |
| --- | --- |
| `client` | Classify the external caller represented by `user`. Retain it for flow calculations. Establish a deployed software component before attributing a vendor licence to it. |
| `loadbalancer` | Choose the implementation and release of the entry service, then inspect its notice. |
| `signer` | Identify the signing service's own release separately from the artifacts it signs. |
| `builder` | Identify the build service's own release separately from the workloads it builds. |
| `app` | Identify the software represented by each workload and its release. The name recurs across production, development and recovery. |
| `recovery-env` | Resolve the recovery environment to specific deployed software before attributing a notice to the environment. |
| `forgejo` | Obtain a verified supplier notice for a named release and record its byte digest. A deployment selection needs separate evidence. |
