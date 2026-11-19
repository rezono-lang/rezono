"""The default listening transport of OpenBao, from one pinned page of a named release.

Expectation source: https://raw.githubusercontent.com/openbao/openbao/v2.3.0/website/content/docs/configuration/listener/tcp.mdx
SHA-256 of the complete response: bfd0a0e12714f0ed76736051907b458d77187f444e4413e1637a64e9042f7b80. The TCP listener page states the default bind address and port.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("openbao", "2.3.0", "TCP", 8200,
             "https://raw.githubusercontent.com/openbao/openbao/v2.3.0/website/content/docs/configuration/listener/tcp.mdx",
             "bfd0a0e12714f0ed76736051907b458d77187f444e4413e1637a64e9042f7b80")]


def test_openbao_transport():
    check_vendor_transport("openbao_transport", EXPECTED, revision="v2.3.0", line=50,
                           fragment_sha256="6df1d88d9b8f39c172bfa12d18f84bba515e0fc14500b95e0b48d3d9d2405b93")
