# Render network policies from the checked listener publication

The platform policy consumer accepts a namespace, an object store, the checked manifest and the reading role. Its entry point is `network_policy.render_published_network_policies(namespace, store, manifest, role)`. Read the `listener_case_decision` snapshot for that role using the URI and digest in the manifest. Pass each allowed source, destination, transport and port to the existing NetworkPolicy renderer. A firewall denial or service-isolation decision supplies no grant.

The reference fixture grants service A access to X and Y. B shares its source range and has no service grant. Z has no firewall grant. Moving only X's listener from TCP 443 to TCP 9443 therefore moves both policies for A and X. The two policies for A and Y stay on TCP 443. The namespace retains its default denial.

This route connects the checked role publication to the generated objects. Accepting caller-provided flow dictionaries alone leaves the selection of allowed rows and ports outside the platform renderer.
