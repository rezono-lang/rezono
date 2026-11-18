"""One service name in two namespaces never joins evidence across the boundary."""

import pytest


def test_build_and_signature_witnesses_share_the_entire_key():
    from image_projection import project_images

    a, b, c = ["registry.example.org/app@sha256:" + letter * 64 for letter in "abc"]
    builds = [("blue", "web", b), ("blue", "web", a), ("blue", "web", a),
              ("blue", "web", c), ("green", "web", c)]
    signatures = [("green", "web", c), ("blue", "jobs", c),
                  ("blue", "web", b), ("blue", "web", a)]
    assert project_images("blue", builds, signatures) == [
        {"service": "web", "image": a}, {"service": "web", "image": b}]
    assert project_images("green", builds, signatures) == [{"service": "web", "image": c}]
    assert project_images("amber", builds, signatures) == []
