"""Project verified image witnesses to namespaced admission parameters."""

from collections.abc import Iterable

ImageKey = tuple[str, str, str]


def project_images(
    namespace: str, builds: Iterable[ImageKey], signatures: Iterable[ImageKey]
) -> list[dict[str, str]]:
    """Include each image with both witnesses for its namespace and service."""
    verified = set(builds).intersection(signatures)
    return [
        {"service": service, "image": image}
        for owner, service, image in sorted(verified)
        if owner == namespace
    ]
