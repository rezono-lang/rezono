"""Builds that example tests share instead of each making them again: an epoch of a committed pack, and its
publication for a set of roles. Each is built once per directory of shared builds (`SHARED`); every caller
gets its own copy, an epoch unpickled afresh or a publication copied into the caller's store, so no test can
change what another reads. The directory lives only as long as one run: the shard's worker processes share
it in CI (scripts/components.py), and a plain pytest run gets one of its own (examples/conftest.py). Only
committed packs are shared: their files do not change during a run, and the key names the pack, the epoch
arguments and the roles, which is everything the build reads besides the code of that same run."""

import hashlib
import json
import os
import pickle
import shutil
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = "REZONO_SHARED_BUILDS"
# A peer that died while building leaves its lock; the job's own timeout is longer than this wait.
PATIENCE_S = 900


def _directory() -> Path:
    value = os.environ.get(SHARED)
    if not value:
        raise RuntimeError(f"{SHARED} is not set: examples/conftest.py sets it for every run")
    return Path(value)


def _committed(pack_dir) -> str:
    pack = Path(pack_dir).resolve()
    if not pack.is_relative_to(ROOT / "examples") or not (pack / "pack.yaml").is_file():
        raise ValueError(f"{pack_dir}: only a committed example pack is shared")
    return pack.relative_to(ROOT).as_posix()


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def _built(key: str, build) -> Path:
    """The directory that `build(path)` fills, made by the first process that asks and read by the others."""
    root = _directory()
    done, lock, failed = root / key, root / f"{key}.lock", root / f"{key}.failed"
    if done.is_dir():
        return done
    try:
        lock.open("x").close()
    except FileExistsError:
        start = time.monotonic()
        while not done.is_dir():
            if failed.exists() or time.monotonic() - start > PATIENCE_S:
                # The builder failed: build here as well, so this test reports the failure itself.
                private = Path(tempfile.mkdtemp(prefix=f"{key}-", dir=root))
                build(private / "build")
                return private / "build"
            time.sleep(0.05)
        return done
    work = root / f"{key}.writing"
    try:
        build(work)
    except BaseException:
        failed.touch()
        raise
    work.rename(done)
    return done


def epoch(pack_dir, **arguments):
    """`rezono_publisher.batch.epoch` of a committed pack, built once; each call returns a fresh copy."""
    from rezono_publisher import batch

    def build(path: Path) -> None:
        path.mkdir(parents=True)
        made = batch.epoch(pack_dir, **arguments)
        data = pickle.dumps(made, protocol=pickle.HIGHEST_PROTOCOL)
        if pickle.loads(data) != made:
            raise ValueError("the epoch cannot be copied losslessly")
        (path / "epoch.pickle").write_bytes(data)

    pack = _committed(pack_dir)
    found = _built(_key("epoch", pack, arguments), build)
    return pickle.loads((found / "epoch.pickle").read_bytes())


def publication(pack_dir, root, roles: dict[str, str], **arguments):
    """`publish.publish(epoch(pack_dir, **arguments), FileStore(root), roles)`, built once and copied into
    `root`: the caller's store holds the same objects as one it published itself. Returns (store, manifest)."""
    from rezono_publisher import publish, store

    def build(path: Path) -> None:
        bucket = store.FileStore(path / "store")
        manifest = publish.publish(epoch(pack_dir, **arguments), bucket, roles)
        encoded = json.dumps({"bucket": bucket.bucket, "manifest": manifest}, allow_nan=False)
        if json.loads(encoded)["manifest"] != manifest:
            raise ValueError("the manifest cannot be copied losslessly")
        (path / "publication.json").write_text(encoded, encoding="utf-8")

    pack = _committed(pack_dir)
    found = _built(_key("publication", pack, arguments, roles), build)
    state = json.loads((found / "publication.json").read_text(encoding="utf-8"))
    shutil.copytree(found / "store", root, dirs_exist_ok=True)
    return store.FileStore(root, bucket=state["bucket"]), state["manifest"]
