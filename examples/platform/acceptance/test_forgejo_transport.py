"""The default listening transport of Forgejo, from one pinned page of a named release.

Expectation source: https://codeberg.org/forgejo/docs/raw/branch/v9.0/docs/admin/config-cheat-sheet.md
SHA-256 of the complete response: 77859c2080ca14c3193b8cf4a5fb161ac95cdc1a299cd83883d5c938af6d0157. The configuration cheat sheet states the default HTTP listen port; HTTP runs over TCP.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("forgejo", "9.0", "TCP", 3000,
             "https://codeberg.org/forgejo/docs/raw/branch/v9.0/docs/admin/config-cheat-sheet.md",
             "77859c2080ca14c3193b8cf4a5fb161ac95cdc1a299cd83883d5c938af6d0157")]


def test_forgejo_transport():
    check_vendor_transport("forgejo_transport", EXPECTED, revision="v9.0", line=308,
                           fragment_sha256="6a03dc8ee68c3de7024f081998d97f3662e2dac4726b8e73925e635842caede1")
