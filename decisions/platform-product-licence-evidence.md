# Licence evidence in the reference platform

Publish the supplier's declaration for a named source release beside each service. Join the service's selected release to a notice for the same product. An explicit binding says whether that notice describes the exact scenario release or one example patch of the selected series. A component without a selected version can show a reference source release with that scope. A selected release without matching evidence stays unknown. The example does not establish the licensing of a built image or all of its dependencies.

Each product file records the original notice URL and SHA-256 of the complete response. Its source sidecar records the inspection of that notice, anchored by the hash of its first nonempty line including the line ending. The product's declaration is a separate field. A path-specific notice and a published licence text with an unspecified grant variant each retain their scope. These rows provide information and never generate a policy finding.

The Keycloak binding uses the release in `examples/platform/acceptance/product-evidence.json`. The PostgreSQL bindings associate the platform's selected major series with their initial source releases. Products without a named implementation or verified notice remain visible in the component licence state.

The `platform-catalogue` reader can inspect the public component inventory, release selections, notices and evidence gaps. This role has no grant for tenants' requests or quotas.
