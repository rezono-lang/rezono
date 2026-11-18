# Withhold a published total without full read evidence

Source `docs/semantics/value-cases.yaml#withheld-total`.

## Adopted behavior

A published total based on an aggregate is withheld from a role lacking full read access to the relation it inspects. The role receives neither a total row nor a proof for that total. The ordinary publication uses the access meaning of the aggregate's complete proof.

Include two worlds that differ only in hidden rows and compare the role's bytes. A role with full read evidence must receive the total and its proof. The [manifest contract](../contracts/manifest.yaml) and [publisher access tests](../edge/publisher/tests/test_publish.py) give both controls.
