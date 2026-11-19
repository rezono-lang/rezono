"""The default listening transport of chrony, from one pinned page of a named release.

Expectation source: https://gitlab.com/chrony/chrony/-/raw/4.6/doc/chrony.conf.adoc
SHA-256 of the complete response: 09051963c6a2d5ab4ed4fe816ac480bb9c5bf87009839c19d796f00065672d3f. The port directive states the default NTP server port; the same page names NTP requests as UDP.
"""

import pytest

from transport_support import check_vendor_transport

EXPECTED = [("chrony", "4.6", "UDP", 123,
             "https://gitlab.com/chrony/chrony/-/raw/4.6/doc/chrony.conf.adoc",
             "09051963c6a2d5ab4ed4fe816ac480bb9c5bf87009839c19d796f00065672d3f")]


def test_chrony_transport():
    check_vendor_transport("chrony_transport", EXPECTED, revision="4.6", line=1840,
                           fragment_sha256="5358e031b8bcd603bbd7ed2279e0e7c8da3f09a8148f109a5a1b46422fb8337b")
