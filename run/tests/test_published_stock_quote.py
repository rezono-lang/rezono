"""One observed stock change must reach the offer and payable amount read by the orderer."""

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from offline_cases import RUN
from rezono_compiler import writer
from rezono_publisher import batch, publish, store
from rezono_publisher.views import key_of


def publication(directory, destination):
    epoch = batch.epoch(directory, epoch=1, knowledge_time="2032-01-01T00:00:00Z",
                        sources=[("facts", "recorded-stock")])
    bucket = store.FileStore(destination)
    manifest = publish.publish(epoch, bucket, {"checker": "complete"})
    saved = json.loads(bucket.get(f"{epoch.pack}/manifests/{manifest['id']}.json"))
    return bucket, saved


def rows(publication, name):
    bucket, manifest = publication
    entry, = [item for item in manifest["snapshots"] if item["role"] == "checker" and item["relation"] == name]
    raw = bucket.get(key_of(entry["uri"]))
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    return {tuple(item["key"]) for item in json.loads(raw)}


def test_stock_changes_published_quote(tmp_path):
    source = RUN / "packs" / "offer-selection"
    baseline = publication(source, tmp_path / "baseline")
    assert any(item["relation"] == "payable_minor" for item in baseline[1]["snapshots"]), (
        "The checked offer publication lacks the payable amount for each demand and offer")
    # Use the shared two-period fixture. One stock observation changes; billing terms stay fixed.
    first = Fraction(499) * 2 + 300
    second = Fraction(600) * 2 + 100

    def change(directory, slot, value):
        delta = {"op": "set", "kind": "offer", "key": "amber", "slot": slot, "value": value}
        texts, _ = writer.apply_delta(directory, {"format": writer.FORMAT, "changes": [delta]})
        writer.write_files(directory, texts)

    with TemporaryDirectory(prefix=writer.WORK_PREFIX) as work:
        directory = writer.checkout(source, Path(work))
        change(directory, "period_price_minor", 499)
        for label, winner, payable in (("available", "amber", first), ("withdrawn", "blue", second)):
            if label == "withdrawn":
                change(directory, "stock", 0)
            result = publication(directory, tmp_path / label)
            assert {r for r in rows(result, "selected") if r[0] == "pair"} == {("pair", winner)}
            totals = {(offer, int(amount)) for demand, offer, amount in rows(result, "payable_minor")
                      if demand == "pair" and offer in {winner, "blue"}}
            assert totals == {(winner, payable), ("blue", second)}
