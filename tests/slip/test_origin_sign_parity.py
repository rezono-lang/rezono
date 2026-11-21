"""Pin every restated copy of OriginSign (contract, checker, publication, gate) to contracts/source.yaml."""

from pathlib import Path
import re

import yaml
from rezono_checker import sources as checker_sources
from rezono_publication import l0

ROOT = Path(__file__).resolve().parents[2]


def test_origin_sign_enum_matches_contract_everywhere():
    doc = yaml.safe_load((ROOT / "contracts" / "source.yaml").read_text(encoding="utf-8"))
    expected = set(doc["enums"]["OriginSign"]["permissible_values"])
    assert expected == {"origin_decision", "origin_vendor", "origin_design", "origin_observation"}

    assert checker_sources.ORIGIN_SIGNS == expected
    assert l0._ORIGIN_SIGNS == expected

    local_ts = (ROOT / "edge" / "gate" / "src" / "local.ts").read_text(encoding="utf-8")
    m = re.search(r"const\s+ORIGIN_SIGNS\s*=\s*new\s+Set\(\[([^\]]+)\]\)", local_ts)
    assert m is not None, "ORIGIN_SIGNS Set declaration missing from edge/gate/src/local.ts"
    gate_signs = set(re.findall(r"['\"]([a-z_]+)['\"]", m.group(1)))
    assert gate_signs == expected
