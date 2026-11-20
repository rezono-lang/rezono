"""Render the reinstall request that hands one machine its Ignition, per decisions/run-price-enforcement.md."""

import pytest

from offline_cases import implementation

IMAGE = "https://images.example.org/flatcar_production_openstack_image.img"
DIGEST = "0123456789abcdef" * 4
IGNITION = '{"ignition": {"version": "3.4.0"},\n "passwd": {}}\n'


def test_ovh_reinstall():
    body = implementation("ovh_reinstall.py", "body")

    assert body("observed-template", IMAGE, DIGEST, IGNITION, "m-a") == {
        "operatingSystem": "observed-template",
        "customizations": {
            # The Ignition text is passed as written, never re-serialized.
            "configDriveUserData": IGNITION,
            "hostname": "m-a",
            "imageCheckSum": DIGEST,
            "imageCheckSumType": "sha256",
            "imageType": "raw",
            "imageURL": IMAGE,
        },
    }
    for args in [
        ("", IMAGE, DIGEST, IGNITION, "m-a"),
        ("observed-template", "http://images.example.org/flatcar.img", DIGEST, IGNITION, "m-a"),
        ("observed-template", IMAGE, DIGEST.upper(), IGNITION, "m-a"),
        ("observed-template", IMAGE, DIGEST[:-1], IGNITION, "m-a"),
        ("observed-template", IMAGE, DIGEST, "#cloud-config\n", "m-a"),
        ("observed-template", IMAGE, DIGEST, '{"passwd": {}}', "m-a"),
        ("observed-template", IMAGE, DIGEST, '{"ignition": {}}', "m-a"),
        ("observed-template", IMAGE, DIGEST, IGNITION, ""),
    ]:
        with pytest.raises(ValueError):
            body(*args)


def test_ovh_reinstall_rejects_duplicate_keys_and_malformed_image_url():
    body = implementation("ovh_reinstall.py", "body")

    for bad_ignition in [
        '{"ignition": {"version": "3.4.0"}, "ignition": {"version": "3.3.0"}}',
        '{"ignition": {"version": "3.4.0", "version": "3.3.0"}}',
    ]:
        with pytest.raises(ValueError):
            body("observed-template", IMAGE, DIGEST, bad_ignition, "m-a")

    for bad_url in [
        "https://:443/flatcar.img",
        "https://user:pass@images.example.org/flatcar.img",
        "https://user@images.example.org/flatcar.img",
        "https://:pass@images.example.org/flatcar.img",
        "https://@images.example.org/flatcar.img",
    ]:
        with pytest.raises(ValueError):
            body("observed-template", bad_url, DIGEST, IGNITION, "m-a")
