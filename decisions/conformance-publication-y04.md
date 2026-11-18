# Subscriptions signal committed epochs

Source `docs/publication/cases/Y04.yaml#Y04`.

## Deferral

The [manifest contract](../contracts/manifest.yaml) defines which epochs close a manifest. This source requires observation of the event stream after a failed epoch and a committed epoch, including the committed epoch and hash pins. The manifest semantics alone do not establish delivery of one subscription event.

Revisit when the subscription interface can run those two epochs in sequence. Check the size and contents of the event stream and validate the pins against the committed manifest.
