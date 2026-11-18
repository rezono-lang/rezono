# Conditional bare-metal provider choice

Prefer Vultr for further qualification of the bounded run. Its bare-metal
provisioning guide documents both a remote iPXE boot and a disk mode that
leaves extra drives unformatted. Two priced offers have two physical drives.
Keep phoenixNAP as an alternative. Neither provider qualifies for a paid
order on the evidence below. Compare total payable amounts only among offers
that meet every requirement; this preference does not establish the cheapest
eligible offer.

| Requirement | Vultr | phoenixNAP |
| --- | --- | --- |
| Flatcar and per-machine Ignition | Bare Metal accepts an iPXE chain URL [V1, V2]. Flatcar's iPXE guide specifies the kernel, initramfs and per-machine Ignition URL [F]. RAM boot is the default. | ServerCreate supports the ipxe OS and a custom boot-script URL [P1]. The same Flatcar path applies [F]. |
| Exclusive Ceph disk | The two captured SKUs advertise two drives [V3]. Select the no-RAID option that leaves extra disks unformatted [V1]. Bind the installer to one boot drive and verify the second by stable identity before assigning it to Ceph. | The order schema exposes root partition RAID configuration [P1]. It does not establish a selected two-drive SKU with one independently exposed, unused drive under custom boot. |
| KubeVirt host | Physical CPU models are published [V3]. The dedicated-server description [V4] does not attest that firmware enables virtualization for either offer or that Flatcar exposes a working KVM device. | The server and pricing schemas [P1, P2] do not attest enabled hardware virtualization for a particular configuration. |
| Payable amount | The captured rows include hourly and monthly amounts and a monthly invoice type [V3]. Stopping preserves charges until destruction [V4]. | Product plans expose price, price unit and pricing model [P2]. An example hourly plan is a schema illustration, not a quote. |
| Lost order response and cleanup | Include the plan digest in creation tags, then independently list bare-metal servers, following inventory pagination [V2]. | Assign the digest using an existing tag name during creation. The independent account-wide server list returns server observations and supports an optional tag filter [P1]. |

For either provider, retain public terms and an exact quote for the intended
SKU covering minimum charge, partial-unit rounding, monthly cap or commitment,
setup, network and other applicable fees and taxes before approving a ceiling.
The two-row replay arithmetic supplies no missing billing term. Require a
supported disk-install path for the pinned image, with first boot consuming
the machine's Ignition and the spare drive untouched. Require SKU-specific
evidence for enabled hardware virtualization before ordering. Host acceptance
still requires the observed boot, disk identities and hardware-backed guest.

Creation tags permit positive correlation. Neither cited API establishes
exactly-once creation or that a just-submitted server is immediately visible.
Reconcile the original operation only. A missing or ambiguous result leaves
the order unresolved. Cleanup requires a fresh complete sweep independent of
the journal, covering every resource type the adapter can create, including
separately billed attachments if any. Document visibility and completeness
before enabling the adapter; a server-only list proves only server absence.

## Maker sources

SHA-256 covers the retrieved response body bytes.

| ID | Source | SHA-256 |
| --- | --- | --- |
| V1 | [Bare Metal provisioning](https://docs.vultr.com/products/compute/bare-metal/provisioning) | `563cfae290dc4766cfdd5872a1e9ea4c18da1afa7a7947666363b4e94deb3914` |
| V2 | [Bare metal client](https://raw.githubusercontent.com/vultr/govultr/master/bare_metal_server.go) | `5a6035658a2b9c782900600e928fca7eec312a43f7c11cc7238661af0a171ef2` |
| V3 | [Two public plan rows](https://api.vultr.com/v2/plans-metal?per_page=2) | `4e592b33e7855de0ef463d447254686044edb00b2f770c0104a179a88331343e` |
| V4 | [Bare Metal FAQ](https://docs.vultr.com/products/compute/bare-metal/faq) | `ece0ca0d753f4fb0537c4ac1516beaa3a39a0470e7653a9f02e3ccb13cd037e8` |
| F | [Flatcar iPXE guide](https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/installing/bare-metal/booting-with-ipxe.md) | `d119f8f483752d57e2274659a213eb2181f515de7117f04e6a2169d56ce3e20d` |
| P1 | [Physical server API](https://raw.githubusercontent.com/phoenixnap/go-sdk-bmc/7c1060e91d834f84035cdc1aa844c75b3d1b5195/bmcapi/api/openapi.yaml) | `0f10e5b5c7d270dd25ca8459c6612fd3444fceed432387c041928c23e9b8b20f` |
| P2 | [Billing API](https://raw.githubusercontent.com/phoenixnap/go-sdk-bmc/7c1060e91d834f84035cdc1aa844c75b3d1b5195/billingapi/api/openapi.yaml) | `cc2660dd1322d0031f8780726909a2ef4fc756e3b315fe4857d6c409fcf5adfb` |
