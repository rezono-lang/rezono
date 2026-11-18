"""Share the genuine module-scoped publication with the second immutable reader in this shard."""

import json
import shutil
import time
from pathlib import Path

import pytest
from rezono_publisher.store import FileStore


def is_world(fixturedef, request, module: Path) -> bool:
    return (fixturedef.argname == "world" and fixturedef.scope == "module"
            and fixturedef.params is None and request.node.path == module)


class PublicationProducer:
    def __init__(self, directory: Path, module: Path):
        self.directory = directory
        self.module = module

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        target = is_world(fixturedef, request, self.module)
        start = time.perf_counter()
        result = yield
        if target:
            built = time.perf_counter()
            store, manifest = result
            if type(store) is not FileStore or set(vars(store)) != {"root", "bucket"}:
                raise ValueError("The publication fixture can no longer be copied as a file-backed store")
            encoded = json.dumps({"bucket": store.bucket, "manifest": manifest}, allow_nan=False)
            if json.loads(encoded)["manifest"] != manifest:
                raise ValueError("The publication fixture manifest cannot be copied losslessly")
            # Keep the producer's own store and teardown. Publish a distinct byte-for-byte
            # copy before either group of readers can modify its own fixture state.
            shutil.copytree(store.root, self.directory / "store")
            staged = self.directory / "writing.json"
            staged.write_text(encoded, encoding="utf-8")
            staged.replace(self.directory / "ready.json")
            timings = {"real_fixture_s": round(built - start, 3), "copy_s": round(time.perf_counter() - built, 3)}
            (self.directory / "producer.json").write_text(json.dumps(timings), encoding="utf-8")
        return result


class PublicationReader:
    def __init__(self, directory: Path, module: Path):
        self.directory = directory
        self.module = module

    @pytest.hookimpl(tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        if not is_world(fixturedef, request, self.module):
            return None
        # Only the current shard owns this temporary directory. A failed producer
        # wakes its peer even when pytest could not collect or set up the first test.
        start = time.perf_counter()
        ready = self.directory / "ready.json"
        while not ready.exists():
            if (self.directory / "producer-finished").exists() and not ready.exists():
                raise RuntimeError("The producer finished without a fresh publication fixture")
            time.sleep(0.05)
        state = json.loads(ready.read_text(encoding="utf-8"))
        result = FileStore(self.directory / "store", bucket=state["bucket"]), state["manifest"]
        wait = {"wait_for_current_fixture_s": round(time.perf_counter() - start, 3)}
        (self.directory / "reader.json").write_text(json.dumps(wait), encoding="utf-8")
        fixturedef.cached_result = (result, fixturedef.cache_key(request), None)
        return result
