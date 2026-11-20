"""Render an OVHcloud dedicated-server reinstall body with config-drive Ignition, per decisions/run-price-enforcement.md, Installation."""

from collections.abc import Mapping
import json
import re
from urllib.parse import urlsplit

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _nonempty_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _reject_constant(token: str) -> object:
    raise ValueError(f"invalid JSON constant: {token}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate ignition JSON key: {key!r}")
        result[key] = value
    return result


def _validate_image_url(image_url: object) -> str:
    url = _nonempty_text(image_url, "image_url")
    if any(ch.isspace() for ch in url):
        raise ValueError("image_url must not contain whitespace")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("image_url must be an https URL with a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("image_url must not contain credentials")
    return url


def _validate_sha256(image_sha256: object) -> str:
    if not isinstance(image_sha256, str) or _SHA256_RE.fullmatch(image_sha256) is None:
        raise ValueError("image_sha256 must be 64 lowercase hexadecimal characters")
    return image_sha256


def _validate_ignition(ignition: object) -> str:
    if not isinstance(ignition, str):
        raise ValueError("ignition must be a string")
    try:
        document = json.loads(
            ignition,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except ValueError as exc:
        raise ValueError("ignition must be valid JSON") from exc
    if not isinstance(document, Mapping):
        raise ValueError("ignition must be a JSON object")
    header = document.get("ignition")
    if not isinstance(header, Mapping):
        raise ValueError("ignition requires an ignition object")
    _nonempty_text(header.get("version"), "ignition.version")
    return ignition


def body(
    operating_system: str,
    image_url: str,
    image_sha256: str,
    ignition: str,
    hostname: str,
) -> dict[str, object]:
    """Render the reinstall request body without SSH keys or post-installation scripts."""
    template = _nonempty_text(operating_system, "operating_system")
    host = _nonempty_text(hostname, "hostname")
    if any(ch.isspace() for ch in host):
        raise ValueError("hostname must not contain whitespace")
    url = _validate_image_url(image_url)
    digest = _validate_sha256(image_sha256)
    user_data = _validate_ignition(ignition)
    return {
        "operatingSystem": template,
        "customizations": {
            # Pass Ignition verbatim so the provider receives the exact bytes.
            "configDriveUserData": user_data,
            "hostname": host,
            "imageCheckSum": digest,
            "imageCheckSumType": "sha256",
            "imageType": "raw",
            "imageURL": url,
        },
    }
