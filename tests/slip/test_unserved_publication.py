"""After one changed byte in the witness set the role reads, the page shows no line and says that the reader
could not serve the publication (decisions/viewer-slip.md, "The seal"). The local reader itself refuses the
object whose hash fails; that is held here as well, so the page is not the one that decides."""

import pytest
from slip_support import PACK, MissingSlipPage, ask, publish_main, render, row_query


@pytest.mark.xfail(
    strict=True,
    raises=(MissingSlipPage, AssertionError),
    reason=(
        "Waits for tests/slip/test_role_part_of_bundle.py--test_role_part_of_bundle, "
        "tests/slip/test_head_status_and_hash.py--test_head_status_and_hash, "
        "tests/slip/test_message_filled.py--test_message_filled and, for the page itself, "
        "tests/slip/test_slip_rule_row.py--test_slip_rule_row. "
        "Then show [data-part=unserved] and no line in viewer/slip/ when the reader answers no request the slip "
        "needs (decisions/viewer-slip.md, The seal); the seal shows the reader's hashes and the publisher's "
        "record only for a publication it served. Expectation: one byte changed in the stored witness set."
    ),
)
def test_unserved_publication(tmp_path):
    from rezono_publisher import publish
    from rezono_publisher import store as stores

    store, manifest = publish_main(tmp_path)
    served = render(store, "reader")
    seal = served["doc"].one(data_part="seal")
    assert {check.attrs["data-check"] for check in seal.all(data_check=True)} == {"reader-hashes", "publisher-record"}

    key = publish.role_objects(stores.FileStore(store), PACK, manifest["id"], "reader")["witnesses.json"]
    path = store / key
    data = bytearray(path.read_bytes())
    at = data.index(b"item-a")
    data[at] = ord("j")  # item-a becomes jtem-a: still JSON, another hash
    path.write_bytes(bytes(data))
    [answer] = ask(store, "reader", f"/{PACK}/{manifest['id']}/ask/grounds?{row_query('flagged', 'item-a', '12')}")
    assert answer["status"] != 200, "the local reader serves no object whose hash fails"

    page = render(store, "reader")
    doc = page["doc"]
    assert doc.all(data_part="unserved")
    assert not doc.all("tr", data_line=True)
