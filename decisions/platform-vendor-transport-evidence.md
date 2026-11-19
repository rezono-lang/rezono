# Vendor transport evidence per product

Each product in the reference platform gets its default listening transport from one page of a named release. The page belongs to the product's maker. The [PostgreSQL transport](platform-source-and-scenario-cases.md) is the first case. Every further product follows the same form and adds no rule.

## What is recorded

A product task adds one fact file. `facts/<product>_transport_source.yaml` holds the pinned `vendor_default_transport_source` statement: the product, series, protocol, port, page URL and the SHA-256 of the complete response. The rule publishes a transport when the product is registered and that statement exists. Product identifiers are fact values, so the rule names no product.

The source file has a sidecar. Its default is a `tool` source named `Vendor transport inspection`. It carries the release ref from the URL as revision, the cited line as position (`L<n>`), the URL, and the SHA-256 of that line's exact bytes including its terminator. This is the inspection form the licence notices already use. The repository stores the address and the hashes, never the page.

## Which pages qualify

- The page is pinned to a release tag or a release branch of the maker's own repository. A raw file at a tag gives stable bytes and the hash can be checked again later.
- One line states the port as a default. A sample configuration or a `docker run` example is not a statement of a default.
- The protocol is stated on the page, or follows from the application protocol the page names: HTTPS, HTTP and gRPC run over TCP, and the page's NTP requests are UDP. Ceph's network reference opens its monitor ports as TCP in its own firewall example. A product whose page leaves the protocol open gets no row yet. CoreDNS states port 53 apart from its protocols, and DNS uses both UDP and TCP. It waits for a page that states both together.
- One line may state several default ports, as Ceph's monitor line does. Each port is its own row, citing the same line.
- The series is the release named in the URL: the tag, or the release branch.

## What the evidence proves

The published row rests on one source: the cited vendor line, pinned by URL, release ref, line and hashes. It proves that a named release of the maker's page stated this default when it was read, and that the bytes can be checked again. It does not prove that a running deployment listens there, nor that a second party read the page the same way. An acceptance test that states the same values from the same page catches a typing slip, not a misreading.

Earlier the task also added `facts/<product>_transport.yaml`, a `vendor_default_transport` observation with the same values, URL and hash, and the rule published only when both rows agreed. Both rows came from the same page, the same reading and the same change, so their agreement suggested a confirmation that was not there. The observation file is gone and the rule reads only the pinned statement.

A second relation returns only with an independent observation: another source than the vendor page, such as a recorded scan of a running deployment, that can disagree with the statement. A rule that requires agreement is then a real cross-check.

## Considered

Keeping both relations and adding an independent observation for each product would keep the cross-check meaningful. No such record exists for these products, and the example works offline from pinned evidence. One pinned statement with its sidecar is the smallest form that claims no more than the evidence holds.

A `document` source would also carry the page's licence and attribution. That needs a second fetch per product for the documentation licence. It does not make the transport claim stronger. The `tool` inspection with a line hash is enough to find the claim again, and the licence notices already use it.

One shared test with a parameter per product would make every worker edit the same file. One test file per product keeps the tasks independent. The PostgreSQL test now reads only PostgreSQL's rows, so a new product cannot break it.

## Acceptance

`examples/platform/acceptance/test_<product>_transport.py` states the expected rows, the line and its hash, all read from the vendor page. `transport_support.py` checks that exactly those rows are published for the product and that every source entry cites that line. The expected standalone violations of the fact file are written in advance. They hold only the reference to the product, which `facts/core.yaml` declares.
