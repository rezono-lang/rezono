"""The storage port (S3 API): get, put with conditional put, list (docs/contracts.md, Poorten), and delete for the
collector alone (collect.py).

Every object is written once. `put_new` writes only if the key is free; if the key is taken, the bytes
must be the same (publishing an epoch again is a no-op), otherwise it is a conflict. That is S3's
conditional put (`If-None-Match: *`), which R2, MinIO and Ceph RGW support.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse


WRITERS = 16  # puts in flight at once: a put waits on the round trip to the store, not on this process


def put_all(st, files) -> None:
    """`put_new` for every (key, bytes), WRITERS at a time. Returns once all are written; the first error is
    raised after the others in flight end. What the store holds afterwards does not depend on the order, since
    every key is written once with fixed bytes. So whatever must come after them (a manifest, an index that
    names them) is written by the caller after this returns."""
    files = list(files)
    if len(files) < 2:
        for key, data in files:
            st.put_new(key, data)
        return
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(WRITERS, len(files))) as pool:
        for f in [pool.submit(st.put_new, key, data) for key, data in files]:
            f.result()


def get_all(st, keys) -> list:
    """`get` for every key, WRITERS at a time: the bytes (or None) in the order of the keys. A get waits on the
    round trip to the store, as a put does, and what it returns does not depend on who asked first: a published
    object never changes. So reading a role's snapshots costs the slowest round trips, not their sum."""
    keys = list(keys)
    if len(keys) < 2:
        return [st.get(key) for key in keys]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(WRITERS, len(keys))) as pool:
        return list(pool.map(st.get, keys))


class Conflict(Exception):
    """A key that already holds other bytes. A published object never changes."""


class FileStore:
    """A directory as a bucket: for tests, CI and a single VM without object storage."""

    def __init__(self, root: str | Path, bucket: str = "rezono"):
        self.root = Path(root)
        self.bucket = bucket

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"bad key {key!r}")
        return self.root / key

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def put_new(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".put-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            try:
                os.link(tmp, path)  # atomic and fails if the key exists: a conditional put
            except FileExistsError:
                if path.read_bytes() != data:
                    raise Conflict(key) from None
        finally:
            os.unlink(tmp)

    def list(self, prefix: str) -> list[str]:
        return [k for k, _ in self.dated(prefix)]

    def dated(self, prefix: str) -> list[tuple[str, float]]:
        """(key, when it was written, in seconds since 1970) of every key under the prefix, sorted by key."""
        base = self.root
        out = []
        for p in base.rglob("*"):
            key = p.relative_to(base).as_posix()
            if p.is_file() and key.startswith(prefix) and not p.name.startswith(".put-"):
                out.append((key, p.stat().st_mtime))
        return sorted(out)

    def delete(self, key: str) -> None:
        """Only the collector deletes (collect.py): an object no retained manifest names."""
        self._path(key).unlink(missing_ok=True)


class S3Store:
    """Any S3-compatible store: Cloudflare R2, MinIO or Ceph RGW. Credentials come from the
    environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY), never from a file in the repository."""

    def __init__(self, bucket: str, endpoint: str | None = None, region: str | None = None):
        import boto3  # optional dependency: pip install 'rezono-publisher[s3]'
        from botocore.config import Config

        self.bucket = bucket
        # Path-style addressing works on every S3-compatible store, also on an endpoint without DNS per bucket.
        self.client = boto3.client("s3", endpoint_url=endpoint or None, region_name=region or "auto",
                                   config=Config(s3={"addressing_style": "path"}, max_pool_connections=WRITERS))

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def put_new(self, key: str, data: bytes) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, IfNoneMatch="*")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") not in ("PreconditionFailed", "412"):
                raise
            if self.get(key) != data:
                raise Conflict(key) from None

    def list(self, prefix: str) -> list[str]:
        return [k for k, _ in self.dated(prefix)]

    def dated(self, prefix: str) -> list[tuple[str, float]]:
        """(key, when it was written, in seconds since 1970) of every key under the prefix, sorted by key."""
        out = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            out += [(o["Key"], o["LastModified"].timestamp()) for o in page.get("Contents", [])]
        return sorted(out)

    def delete(self, key: str) -> None:
        """Only the collector deletes (collect.py): an object no retained manifest names."""
        self.client.delete_object(Bucket=self.bucket, Key=key)


def open_store(url: str, endpoint: str | None = None):
    """`file:///path?bucket=name` or `s3://bucket`."""
    u = urlparse(url)
    if u.scheme == "file":
        bucket = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p).get("bucket", "rezono")
        return FileStore(u.path, bucket)
    if u.scheme == "s3":
        return S3Store(u.netloc, endpoint)
    raise ValueError(f"unknown store {url!r}: use file:///path or s3://bucket")
