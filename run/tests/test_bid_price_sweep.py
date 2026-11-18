from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from offline_cases import RUN


def test_bid_price_sweep_reference():
    from rezono_publisher.sweep import grid

    threshold = (2 * Fraction(600) + 100 - 300) / 2
    assert threshold == 500
    values = grid({"min": 499, "step": 1, "count": 3})
    assert [2 * price + 300 - 1300 for price in values] == [-2, 0, 2]
    assert [min((2 * price + 300, 0, "amber"), (1300, 1, "blue"))[2] for price in values] == [
        "amber", "amber", "blue"]


@pytest.mark.xfail(strict=True, reason="Read decisions/run-bid-price-sweep.md. Extend run/packs/offer-selection with whole-order guarantee eligibility, payable costs and a price sweep. Waits for test_offer_selection.")
def test_bid_price_sweep():
    from rezono_compiler import pack, writer
    from rezono_publisher import batch, sweep

    source = RUN / "packs/offer-selection"
    assert (source / "sweeps.yaml").is_file(), "missing price exploration in the production offer-selection pack"

    def read_epoch(directory):
        epoch = batch.epoch(directory, epoch=1, knowledge_time="2032-01-01T00:00:00Z", sources=[("fixture", "bids")])
        assert all(c["status"] != "red" for c in epoch.checks), epoch.checks
        return epoch.rows

    def apply(directory, key, slot, value):
        delta = {"op": "set", "kind": "offer", "key": key, "slot": slot, "value": value}
        texts, _ = writer.apply_delta(directory, {"format": writer.FORMAT, "changes": [delta]})
        writer.write_files(directory, texts)

    spec, = pack.read(source).sweeps
    assert (spec["kind"], spec["key"], spec["slot"]) == ("offer", "amber", "period_price_minor")
    assert sweep.grid(spec) == [499, 500, 501]
    for price, amber_total, winner in [(499, 1298, "amber"), (500, 1300, "amber"), (501, 1302, "blue")]:
        with TemporaryDirectory(prefix=writer.WORK_PREFIX) as work:
            directory = writer.checkout(source, Path(work))
            apply(directory, spec["key"], spec["slot"], price)
            rows = read_epoch(directory)
            assert set(rows["selected"]) == {("pair", winner)}
            assert {row for row in rows["payable_minor"] if row[1] in {"amber", "blue"}} == {
                ("pair", "amber", str(amber_total)), ("pair", "blue", "1300")}
            assert set(rows["offer__guarantee_mode"]) == {
                ("amber", "binding_quote"), ("blue", "reject_above"), ("clear", "estimate")}
            apply(directory, "clear", "guarantee_mode", "binding_quote")
            assert set(read_epoch(directory)["selected"]) == {("pair", "clear")}
