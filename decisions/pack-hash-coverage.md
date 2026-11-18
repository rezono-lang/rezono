# Definition hash coverage

A published import pins the bytes of its target definition. Check every import under packs and examples. Require a real import and at least one path through an imported pack that imports another pack. A fixed count of edges cannot distinguish repeated references to one target from a dependency chain.

At adoption, six pinned edges included a shared target and an imported pack with an import of its own. Requiring eleven edges would reject that coverage without exercising another hash property.

A second check constructs one file of each documented family, including nested definitions, plus a fact file outside the definition. Compute the expected digest from an explicit map of relative names to SHA-256 digests of chosen bytes. Serialize that map as compact, key-sorted UTF-8 JSON and hash it with SHA-256. This checks file selection and the bytes hashed even if the published examples change.

Keep the documentation check separate so an absent manual cannot hide a stale pin. The public pack manual should list the patterns on its hash coverage line.
