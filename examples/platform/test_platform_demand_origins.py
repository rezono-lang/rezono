"""A demand cites its maker's page or the decision that chose it (decisions/platform-facts-not-conclusions.md,
section 8).

decisions/fact-origin-required.md accepts any origin for a fact row; this test asks the split that section 8 sets.
The platform's own products are those facts/licence-bindings.yaml lists as unknown-implementation. Origins are read
from the compiler's source entries of each fact file that holds demands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parent
REPO = PLATFORM.parents[1]
OWN = "unknown-implementation"
THIS_REPOSITORY = "rezono-lang/rezono"
# The owner's example of a maker's requirement: Keycloak needs a relational database.
MAKERS_REQUIREMENT = ("keycloak", "database")


class MissingDemandOrigin(AssertionError):
    """A demand row lacks the origin its product requires."""


def _decision(source: dict) -> bool:
    """A decision file of this repository, or the proposal that brought the row in."""
    path = str(source.get("position", "")).partition("#")[0]
    return source.get("kind") == "proposal" or (
        source.get("kind") == "git" and path.startswith("decisions/") and (REPO / path).is_file())


def _maker(source: dict) -> bool:
    """A page outside this repository: a document or tool source with its URL, or the maker's own repository."""
    kind, url = source.get("kind"), str(source.get("url", ""))
    if kind in ("document", "tool"):
        return url.startswith("https://") and THIS_REPOSITORY not in url
    return kind == "git" and source.get("name") not in (None, THIS_REPOSITORY)


@pytest.mark.xfail(strict=True, raises=MissingDemandOrigin, reason=(
    "M2: decisions/platform-facts-not-conclusions.md, section 8. Give every demand row of examples/platform/facts/ "
    "the origin its product requires: a decision file (a git source naming decisions/<id>.md) for the platform's own "
    "products, those product_licence_gap lists as unknown-implementation; the maker's page (a document or tool "
    "source with its URL and fragment hash) for a maker's requirement, as Keycloak's database is; a decision file "
    "for the platform's own choice about a third-party product. No demand is synthetic."))
def test_demands_cite_the_vendor_or_a_decision():
    from rezono_compiler import pack, sources

    model = pack.read(PLATFORM)
    gaps = yaml.safe_load((PLATFORM / "facts/licence-bindings.yaml").read_text(encoding="utf-8"))["product_licence_gap"]
    own = {gap["product"] for gap in gaps if gap["reason"] == OWN}
    demands, origins = {}, {}
    for path in sorted((PLATFORM / "facts").glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if "demand" not in data:
            continue
        demands.update({row["id"]: (row["product"], row["function"]) for row in data["demand"]})
        for entry in sources.file_entries(model, path):
            if entry["row"]["relation"].split("__")[0] == "demand":
                origins.setdefault(json.loads(entry["row"]["key"])[0], []).extend(entry["sources"])
    if not demands or not own:
        raise MissingDemandOrigin("no demand rows, or no product of the platform's own, were found")

    wrong = {}
    for ident, (product, function) in sorted(demands.items()):
        found = origins.get(ident, [])
        decided, maker = any(map(_decision, found)), any(map(_maker, found))
        if any(source.get("kind") == "synthetic" for source in found):
            wrong[ident] = "synthetic"
        elif product in own and not decided:
            wrong[ident] = "the platform's own product: cite a decision file"
        elif product not in own and not (maker or decided):
            wrong[ident] = "a third-party product: cite its maker's page or a decision file"
        elif (product, function) == MAKERS_REQUIREMENT and not maker:
            wrong[ident] = "a maker's requirement: cite the maker's page"
    if wrong:
        raise MissingDemandOrigin(f"{len(wrong)} of {len(demands)} demands: "
                                  + "; ".join(f"{ident}: {why}" for ident, why in wrong.items()))
