"""The check metadata against the schema (docs/compiler.md#design-checks-as-data-e11).

The engine reads which slot has which integrity check from the tables `rezono__*`. Those rows come only from the
compiled definition; a fact, scenario or delta can never write them, so a change of data can never switch a
check off. The checker holds the rows the engine loaded against the rows that follow from the schema bundle
of the publication, the bundle stored under its `definition_sha256`: every facet is in its kinds, arrows and
attributes. A difference blocks.

Derived here from the bundle alone, as plain data, without the compiler: an independent reading.
"""

from collections import Counter

# Table -> columns, as the engine has them; every value is compared as canonical text.
TABLES = {
    "rezono__is_a": ("kind", "parent"),
    "rezono__required": ("kind", "slot"),
    "rezono__single": ("kind", "slot"),
    "rezono__arrow": ("kind", "slot", "target"),
    "rezono__enum": ("kind", "slot", "enumeration"),
    "rezono__minimum": ("kind", "slot", "v"),
    "rezono__maximum": ("kind", "slot", "v"),
    "rezono__constant": ("kind", "slot", "v"),
    "rezono__minimum_cardinality": ("kind", "slot", "v"),
    "rezono__maximum_cardinality": ("kind", "slot", "v"),
}
PREFIX = "rezono__"


def compiled(bundle: dict) -> bool:
    """A bundle the compiler wrote: it lists its checks (possibly none) and its kinds."""
    return isinstance(bundle, dict) and "checks" in bundle and isinstance(bundle.get("kinds"), list)


def expected(bundle: dict) -> dict[str, list[tuple]]:
    """The metadata rows the bundle's schema gives, per table. A pack without kinds has no metadata."""
    kinds = bundle.get("kinds") or []
    if not kinds:
        return {}
    table = {k["id"]: k.get("table", k["id"]) for k in kinds}
    out: dict[str, list[tuple]] = {t: [] for t in TABLES}
    for k in kinds:
        if k.get("parent"):
            out["rezono__is_a"].append((table[k["id"]], table[k["parent"]]))
    for s in (bundle.get("arrows") or []) + (bundle.get("attributes") or []):
        key = (table[s["kind"]], s["name"])
        if s.get("required"):
            out["rezono__required"].append(key)
        if not s.get("multivalued"):
            out["rezono__single"].append(key)
        if "target" in s:
            out["rezono__arrow"].append(key + (table[s["target"]],))
        if s.get("enum") is not None:
            out["rezono__enum"].append(key + (s["enum"],))
        for facet in ("minimum", "maximum", "constant", "minimum_cardinality", "maximum_cardinality"):
            if s.get(facet) is not None:
                out[PREFIX + facet].append(key + (str(s[facet]),))
    return {t: sorted(rows) for t, rows in out.items()}


def shaped(table, rows) -> bool:
    """A metadata table by name, with rows of text or whole numbers of its width."""
    return (isinstance(table, str) and table in TABLES and isinstance(rows, (list, tuple))
            and all(isinstance(r, (list, tuple)) and len(r) == len(TABLES[table])
                    and all(isinstance(v, str) or (isinstance(v, int) and not isinstance(v, bool)) for v in r)
                    for r in rows))


def check(bundle, loaded) -> list[dict]:
    """Findings when the loaded metadata (table -> rows of canonical text, duplicates kept) is not exactly
    what the bundle gives: `check_metadata_mismatch` per table that differs, `malformed_check_metadata` when
    either side cannot be read. Fail closed: a compiled bundle with kinds needs the loaded rows."""
    if not compiled(bundle):
        return [{"reason": "malformed_check_metadata", "detail": "no compiled schema bundle to compare with"}]
    if not isinstance(loaded, dict):
        return [{"reason": "malformed_check_metadata", "detail": "no loaded check metadata"}]
    bad = sorted(str(t) for t, rs in loaded.items() if not shaped(t, rs))
    if bad:
        return [{"reason": "malformed_check_metadata", "relation": t, "detail": "not a metadata table of rows"}
                for t in bad]
    try:
        want = expected(bundle)
    except (KeyError, TypeError, AttributeError) as e:
        return [{"reason": "malformed_check_metadata", "detail": f"the bundle does not name {e}"}]
    findings = []
    for t in sorted(set(want) | set(loaded)):
        got = Counter(tuple(str(v) for v in r) for r in loaded.get(t, []))
        should = Counter(want.get(t, []))
        if t not in loaded or t not in want or got != should:
            missing, extra = sorted((should - got).elements()), sorted((got - should).elements())
            findings.append({"reason": "check_metadata_mismatch", "relation": t,
                             "detail": f"missing {missing[:3]}, extra {extra[:3]}"
                             + ("" if t in loaded else ", table not loaded") + ("" if t in want else ", no kinds")})
    return findings
