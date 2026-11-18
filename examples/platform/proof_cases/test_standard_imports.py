import pytest

from case_support import ROOT, engine, imported


def test_standard_imports():
    import re
    import yaml
    entries = yaml.safe_load((ROOT / "pack.yaml").read_text())["imports"]
    by_name = {entry["name"]: entry for entry in entries}
    for name in ("std-order", "std-part", "std-identity", "std-time", "std-access"):
        imported(name)
        assert re.fullmatch(r"[0-9a-f]{64}", by_name[name]["sha256"])
        assert (ROOT / by_name[name]["path"]).resolve() == ROOT.parents[1] / "packs" / name
    engine()
