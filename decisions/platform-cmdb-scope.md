# An inventory export is a scoped reference

The CMDB import reads external JSON through a declared mapping and writes observations and completeness declarations in the cmdb_reference module. The command takes --pack, --mapping and --source. Its placement_fields maps service and cluster to the export's field names. Renaming the source cluster field leaves the domain unchanged. The source companion records the input filename, SHA-256 revision and JSON pointer for every observation and scope entry. This fixture deliberately uses a non-authoritative inventory.

The platform's ordinary cluster_service_placement rule supplies the comparison. For one export lb is on the wrong cluster, idp is absent from an explicitly complete scope, dns is outside that scope, and user matches. Dropping idp from the scope turns its absence into unknown. Completeness in another export cannot certify this one. Correcting lb removes only its mismatch. Compare the complete set of platform placements before and after each import and check the independent sources of both findings.

Run `python -m pytest -q examples/platform/proof_cases/test_cmdb_scope.py`. Implement under `examples/platform/reference`, `portal`, `schema/cmdb_reference` and `rules`, using the repository's fact source companions.
