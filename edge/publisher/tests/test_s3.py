"""The S3 adapter against a real S3 API (moto in CI): conditional put, list, the same publication."""

import os
import uuid

import pytest

from rede_publisher import publish, store
from test_publish import ROLES, Flaky, Interrupted, epoch

ENDPOINT = os.environ.get("REDE_TEST_S3_ENDPOINT")
pytestmark = pytest.mark.skipif(not ENDPOINT, reason="REDE_TEST_S3_ENDPOINT not set (moto runs in CI)")


@pytest.fixture
def s3():
    bucket = f"rede-test-{uuid.uuid4().hex[:8]}"
    s = store.S3Store(bucket, ENDPOINT, "us-east-1")
    s.client.create_bucket(Bucket=bucket)
    return s


def test_conditional_put(s3):
    s3.put_new("a/b.json", b"1")
    s3.put_new("a/b.json", b"1")
    with pytest.raises(store.Conflict):
        s3.put_new("a/b.json", b"2")
    assert s3.get("a/b.json") == b"1" and s3.get("a/missing") is None
    assert s3.list("a/") == ["a/b.json"]


def test_dated_listing_and_delete_for_the_collector(s3):
    """What the collector (collect.py) needs of the store: when each key was written, and delete."""
    s3.put_new("a/b.json", b"1")
    s3.put_new("a/c.json", b"2")
    [(b, when), (c, _)] = s3.dated("a/")
    assert (b, c) == ("a/b.json", "a/c.json") and isinstance(when, float) and when > 0
    s3.delete("a/b.json")
    assert s3.list("a/") == ["a/c.json"] and s3.get("a/b.json") is None


def test_same_publication_as_the_file_store(s3, tmp_path):
    files = store.FileStore(tmp_path, bucket=s3.bucket)
    assert publish.publish(epoch(), s3, ROLES) == publish.publish(epoch(), files, ROLES)
    assert s3.list("") == files.list("")
    assert all(s3.get(k) == files.get(k) for k in files.list(""))


def test_interrupted_publication_resumes(s3):
    with pytest.raises(Interrupted):
        publish.publish(epoch(), Flaky(s3, 3), ROLES)
    assert s3.list("toy/manifests/") == []
    m = publish.publish(epoch(), s3, ROLES)
    assert s3.list("toy/manifests/") == [f"toy/manifests/{m['id']}.json"]
