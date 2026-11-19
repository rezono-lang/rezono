# A provider must enforce the approved amount

An order may be placed only when the provider itself holds the run to the
approved amount, for the whole run and including every surcharge: either a
binding quote that fixes the amount before anything is charged, or a request
the provider refuses at a higher price. Offer selection already ranks only
guarantees of mode `binding_quote` or `reject_above`; an `estimate` cannot win.
This decision records which examined provider can supply such a guarantee.

| Provider | Mechanism before commitment | Verdict |
| --- | --- | --- |
| Vultr | The bare-metal create request carries region, plan, image, boot and tag fields, and no price or bound [V2]. Plans publish hourly and monthly amounts [V3]; charges continue until the server is destroyed [V4]. | `estimate`: ineligible for a paid order. |
| phoenixNAP | Server creation selects a pricing model [P1]. A reservation request names only a SKU and a quantity; the price appears on the created reservation [P2]. | `estimate`: ineligible for a paid order. |
| OVHcloud | Checking out a cart without automatic payment creates an order with its details and prices with and without tax, each as an integer number of microcents [O1]. The order has an expiration date, a status and separate payment operations by order id [O2]. | `binding_quote`, under the conditions below. |

This supersedes the Vultr preference in [the conditional provider choice](run-provider-choice.md).
Vultr and phoenixNAP stay valid sources for the replay fixtures; their offers
carry mode `estimate` until they publish a bound.

## Conditions for the OVHcloud guarantee

- **The order is the quote.** Create a cart for the subsidiary with the plan hash as its description and the guarantee's expiry, assign it, add the plan item, set its configurations in label order, read the checkout, then create the order with `autoPayWithPreferredPaymentMethod: false` [O1]. The read and the created order must have the same total with tax; otherwise nothing is ordered. Whether to waive a retraction period is an input of the request, never a default. The guarantee total is `prices.withTax.priceInUcents` divided by 10^8 in the order's currency, read as an integer and never from the floating-point `value`. The details' `totalPrice` amounts without tax must add up to `prices.withoutTax`; otherwise the order is malformed.
- **Every charge is in the order.** A detail of type `CONSUMPTION` or `OUTPLAN` is billed by usage, so an order containing one gives no guarantee. Setup charges appear as details of the order, so a valid order includes setup.
- **The bound covers the whole run.** The paid period must end after the run's cleanup deadline; the `expiration` date counts from its UTC midnight, and equality blocks. The service must not renew: `renew.automatic` false, `renew.forced` false and `renew.deleteAtExpiration` true. A commitment (`engagedUpTo`) beyond the paid expiration is a further charge [O3]. Any of these, or a missing field, blocks the order.
- **Expiry.** The guarantee expires at the order's `expirationDate`, treated as exclusive, and never later than the next UTC midnight of the approved order day.
- **Correlation.** The commitment is paying one order id, once, with `POST /me/order/{orderId}/pay` and a payment method id [O2]. A lost checkout response costs nothing: an unpaid order is never charged and expires. A lost payment response is resolved by the status of the same order id, never by paying another order. Status `notPaid` is not committed; `checking`, `documentsRequested` and `delivering` are committed and pending; `delivered` is delivered; `cancelled` is a definitive refusal; `cancelling`, `unknown` or anything else is unresolved.
- **Installation.** Install through the reinstall operation with a raw image, its SHA-256 and the machine's Ignition as config-drive user data [O3]. No post-installation script and no SSH key: nothing runs over SSH. The operating-system name is an observation of the compatible templates, not a constant.
- **Cleanup.** The account-wide server list returns service names [O3]. The run is clean when none of the services delivered by the plan's orders appears in a fresh unfiltered list. Termination needs a token that the provider sends by e-mail to the admin contact [O3], so confirming it is an owner action, and a terminated service may stay listed until its expiration.

## Not yet qualified

OVHcloud is the only examined provider that passes this filter. It is not
qualified for a paid order until a recorded unpaid order confirms the shape
above, a trial shows Flatcar consuming the config-drive Ignition after a raw
image install with the second disk untouched, the CPU of the chosen plan runs
a hardware-backed KubeVirt guest, and the termination path is observed. The
same-day cleanup rule then reads the delivered services, not a deleted server,
because the server can stay listed until its paid period ends; the cost is
already bounded by the paid order.

## Maker sources

SHA-256 covers the retrieved response body bytes. O1 to O3 were retrieved on 2026-11-19.

| ID | Source | SHA-256 |
| --- | --- | --- |
| V2 | [Bare metal client](https://raw.githubusercontent.com/vultr/govultr/8e5e0d2f21081aaea710efb2a4bd6c5a1eca7d28/bare_metal_server.go) | `5a6035658a2b9c782900600e928fca7eec312a43f7c11cc7238661af0a171ef2` |
| V3, V4 | As in [the conditional provider choice](run-provider-choice.md). | |
| P1 | [Physical server API](https://raw.githubusercontent.com/phoenixnap/go-sdk-bmc/7c1060e91d834f84035cdc1aa844c75b3d1b5195/bmcapi/api/openapi.yaml) | `0f10e5b5c7d270dd25ca8459c6612fd3444fceed432387c041928c23e9b8b20f` |
| P2 | [Billing API](https://raw.githubusercontent.com/phoenixnap/go-sdk-bmc/7c1060e91d834f84035cdc1aa844c75b3d1b5195/billingapi/api/openapi.yaml) | `cc2660dd1322d0031f8780726909a2ef4fc756e3b315fe4857d6c409fcf5adfb` |
| O1 | [Order API description](https://eu.api.ovh.com/1.0/order.json) | `2448794cf56f5fa2bd02fe4299be5f80e551f8d8a8bb21c14d4fa065b26f5715` |
| O2 | [Account API description](https://eu.api.ovh.com/1.0/me.json) | `92e043ead749c0e2e046e1c2983300356be0da78b0d6ff6328b2e792c52a9385` |
| O3 | [Dedicated server API description](https://eu.api.ovh.com/1.0/dedicated/server.json) | `4ff45c62c6390b92dc34354cc53a766748cb9ef034ee47443bbfeddf34f55416` |
