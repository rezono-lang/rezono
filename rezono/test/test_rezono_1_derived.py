"""Unified `derived` syntax in rezono 1: single-key properties in kind/extend, multi-key declarations
with `over <domain>`, `.one()`, method-form `.where(...)` / `.count(predicate)` / bare relation columns,
and `means` / `@` on derivations (decisions/language-rezono-1.md, sections 1, 2 and 3.4)."""

import json

import pytest
from reader_probe import read_modules

UNIFIED_DERIVED = """\
rezono 1
pack sample
kind Group world closed
kind Item world closed
  group: Group
  parent: Item?
kind Link world closed
  src: Item
  dst: Item
kind Choice world closed
  item: Item
  group: Group
  target: Item
extend s: Item
  derived in_group: Group = s.group
  derived out_links: Int = Link.count(src = s)
derived asks(a: Item, g: Group): Bool = a.group = g
derived chosen(a: Item, g: Group): Item?
  over asks(a, g)
  = Choice.where(item = a and group = g).target.one()
derived needs(a: Item, g: Group): Item
  over asks(a, g)
  = Item.where(group = g).one()
  unless not (chosen(a, g) is n/a) then chosen(a, g)
  means "{$a} uses {$result} for {$g}." @ policy#art-3
derived within(part: Item, whole: Item): Bool = part.parent = whole or within(part.parent, whole)
"""

MISSING_DOMAIN = """\
rezono 1
pack sample
kind Group world closed
kind Item world closed
derived needs(a: Item, g: Group): Item = Item.where(it = a).one()
"""

LEADING_DOT_REFUSED = """\
rezono 1
pack sample
kind Edge world closed
  pred: Text
kind Item world closed
  tag: Text
  derived matches: Int = Edge.count(.pred = tag)
"""


class MissingRezono1DerivedSyntax(AssertionError):
    """The reader did not parse, round-trip, or enforce domain/leading-dot rules for rezono 1 derived syntax."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingRezono1DerivedSyntax,
    reason="M3: decisions/language-rezono-1.md: Waits for rezono/test/test_rezono_1_version_switch.py. "
           "Implement rezono 1 unified `derived` syntax in rezono/src/ (named `extend s: K`, multi-key module-level "
           "`derived` with mandatory `over <domain>` for functional values, `.one()`, method-form `.where(...)` and "
           "`.count(pred)` with bare relation column names, and `means`/`@` on `derived`), rejecting multi-key "
           "functional derivations without `over` and rejecting leading-dot `.pred`. Read sections 1, 2 and 3.4.",
)
def test_rezono_1_unified_derived_reader():
    unified, missing_domain, leading_dot = read_modules(
        UNIFIED_DERIVED,
        MISSING_DOMAIN,
        LEADING_DOT_REFUSED,
    )
    problems = []
    if unified["diagnostics"] or unified["format"] != "rezono.module/5" or unified["module"] is None:
        problems.append({"unified": unified})
    else:
        decls = unified["module"]["decls"]
        module_derived = {d["derived"]: d for d in decls if isinstance(d.get("derived"), str)}
        if set(module_derived) != {"asks", "chosen", "needs", "within"}:
            problems.append({"module_derived_names": sorted(module_derived)})
        else:
            needs = module_derived["needs"]
            if needs.get("means") != "{$a} uses {$result} for {$g}." or needs.get("source") != "policy#art-3":
                problems.append({"needs_means_source": needs})
            if not needs.get("over"):
                problems.append({"needs_missing_over": needs})
        if unified["printed"] is None:
            problems.append({"unified_printed": None})
        else:
            [reparsed] = read_modules(unified["printed"])
            if reparsed["diagnostics"] or reparsed["module"] != unified["module"]:
                problems.append({"roundtrip_mismatch": reparsed})

    if missing_domain["module"] is not None or not missing_domain["diagnostics"]:
        problems.append({"missing_domain_not_refused": missing_domain})

    if leading_dot["module"] is not None or "R000" not in [d["code"] for d in leading_dot["diagnostics"]]:
        problems.append({"leading_dot_not_refused": leading_dot})

    if problems:
        raise MissingRezono1DerivedSyntax(json.dumps(problems, indent=2))
