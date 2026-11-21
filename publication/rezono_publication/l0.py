"""A publication 1.0 reader and verifier (docs/publication/l0.md §1): the one validator for admission (LS0).

A **reader** rejects invalid input with an error and never converts: no float, no guessed state, no text that is
not in its normal form. A **verifier** also classifies the change from one schema to its successor (§2.4). Both
need nothing but L0 and Rezono's canonical JSON; this module imports no compiler, publisher or engine (§1).

- `check_schema(doc)`: a schema document (§2, §3.6, §3.7); returns its schema id `s-…`.
  A kind of derived tuples may name its column order in `tuple_key`: every slot once, each derived, single and
  known. A row's `$id` is then the canonical JSON of its typed cells in that order, and is read against them.
- `read_row`, `read_rows`, `read_collection`, `read_jsonl`, `loads`: row JSON (§3) under a schema.
- `check_field`, `check_table_metadata`: the `rezono` metadata of a columnar file (§4.2, §4.4, §4.5).
- `classify(a, b, datasets)`: the change class from schema A to its successor B (§2.4); `read_under` reads rows
  of A under a minor successor B (each added slot in its `backfill` state).
- `admit(schema, delta, reviewed)`: admission of a delta (§3.7, LS0): a dataset read, and for a control kind a
  `decision` that names a reviewed proposal. How a review is checked is Rezono's: `reviewed` is a callable.

Every error is an `L0Error` whose text names the element and the rule.
"""

import datetime
import json
import pickle
import re
from fractions import Fraction
from math import gcd

from rezono_canon import CanonError, canonical_json, canonical_sha256

__all__ = [
    "L0Error",
    "STATES",
    "CORE_REASONS",
    "check_schema",
    "schema_id",
    "storage",
    "read_row",
    "read_rows",
    "read_collection",
    "read_jsonl",
    "loads",
    "check_field",
    "check_table_metadata",
    "classify",
    "read_under",
    "admit",
]


class L0Error(ValueError):
    """Input that the publication 1.0 does not accept."""


STATES = ("known", "not_applicable", "unknown", "invalid")  # code order (§3.3)
_STATE_KEYS = {"$na": "not_applicable", "$unknown": "unknown", "$invalid": "invalid"}
CORE_REASONS = {  # §2.3: always in scope, with the states each may label
    "no_version_applies": ("unknown",),
    "versions_overlap": ("invalid",),
    "exception_conflict": ("invalid",),
    "no_row_applies": ("unknown",),
    "ambiguous_date": ("invalid",),
    "empty": ("not_applicable",),
    "no_value": ("not_applicable", "unknown"),
    "no_match": ("not_applicable", "unknown"),
    "multiple_values": ("invalid",),
    "added_later": ("not_applicable", "unknown", "invalid"),
}
CORE_TYPES = {"Text", "Bool", "Integer", "Ratio", "Date", "DateTime", "Quantity", "Money", "Period", "Enum"}
_TYPE_MEMBERS = {
    "Text": {"pattern", "normalize", "fields"},
    "Bool": set(),
    "Integer": {"min", "max"},
    "Ratio": {"min", "max"},
    "Date": set(),
    "DateTime": set(),
    "Quantity": {"dimension", "unit", "storage_unit", "factor", "scale", "min", "max"},
    "Money": {"currency", "scale", "per"},
    "Period": {"over", "range"},
    "Enum": {"enum"},
}
_KIND_MEMBERS = {"world", "id", "slots", "iri", "parent", "versioned", "applies", "plane", "owner", "tuple_key"}
_SLOT_MEMBERS = {"type", "ref", "card", "states", "world", "derived", "inverse", "min", "max", "backfill",
                 "versions", "expr"}
_TOP_MEMBERS = {"rezono", "pack", "base", "kinds", "types", "enums", "imports", "map", "reasons", "follows"}
LEGACY_SCHEMA_KEY = "reckon"  # pre-rename sealed publications (rezono_publication.statement)
_ROW_MEMBERS = {"$kind", "$id", "$schema", "$why", "$src", "$valid", "$known"}
_NORMALIZE = ("uppercase", "lowercase", "strip spaces", "trim")

_PACK = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
_KIND = re.compile(r"[A-Z][A-Za-z0-9]*")
_CODE = re.compile(r"[a-z][a-z0-9_]*")
_SID = re.compile(r"s-[0-9a-f]{64}")
_DID = re.compile(r"d-[0-9a-f]{64}")
# A manifest id `m-<epoch>`, `<epoch>` a natural number in its decimal spelling (§1): `m-01` names no epoch.
_EPOCH = r"m-(?:0|[1-9][0-9]*)"
_MID = re.compile(_EPOCH)
_INT = re.compile(r"0|-?[1-9][0-9]*")
_DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?")  # shortest: no trailing zero
_RATIO = re.compile(r"(-?(0|[1-9][0-9]*))(/([1-9][0-9]*))?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATETIME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]{0,5}[1-9])?Z")
_MONEY = re.compile(r"(?P<cur>\S+) (?P<num>-?(0|[1-9][0-9]*)(\.(?P<dec>[0-9]+))?)(/(?P<per>\S+))?")
_PACK_REF = re.compile(
    r"(?P<pack>[a-z][a-z0-9]*(-[a-z0-9]+)*)@(?P<schema>s-[0-9a-f]{64})(@(?P<manifest>m-[0-9]+))?"
    r"(@(?P<dataset>d-[0-9a-f]{64}))?:(?P<kind>[A-Z][A-Za-z0-9]*)/(?P<id>.+)",
    re.DOTALL,
)
_IRI = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:\S+")  # an absolute IRI, also an opaque proof URI (`rezono:w/…`)
_LANG = re.compile(r"[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*")  # a BCP 47 tag, by shape
_SAFE = 2**53 - 1
_INT64 = (-(2**63), 2**63 - 1)
_DEC38 = 10**38 - 1
# Money literals (§3.2, Q18): the ISO 4217 code, or the one Unicode currency sign that names only that code.
# A sign shared by several currencies (`$`, `¥`, `kr`) is not a literal of any of them.
_CURRENCY_SIGN = {"EUR": "€", "GBP": "£", "INR": "₹", "KRW": "₩", "ILS": "₪", "NGN": "₦", "PHP": "₱",
                  "RUB": "₽", "TRY": "₺", "UAH": "₴", "VND": "₫", "KZT": "₸", "GEL": "₾", "AZN": "₼"}
# contracts/source.yaml `Source`, restated (as checker/rezono_checker/sources.py does) so the reader imports no
# contract code (§1).
_SOURCE_KINDS = {"git", "pack", "scenario", "proposal", "query", "tool", "person", "document", "synthetic"}
_SOURCE_FIELDS = {"kind", "name", "revision", "position", "url", "retrieved_at", "fragment_sha256", "ownership",
                  "licence", "attribution"}
_URL = re.compile(r"https?://[^\s/?#]+([/?#][^\s]*)?")
_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z")
_TRIMMED = re.compile(r"\S(.*\S)?", re.S)
_EPOCH_PIN = re.compile(r"m-[0-9]+(?P<hash>@d-[0-9a-f]{64})?")


def _is_text(value) -> bool:
    return isinstance(value, str)


def chain(schema: dict, kind: str) -> list:
    """The kind and the kinds above it, nearest first (§2.1 `parent`). It ends at a parent that is no kind or
    that came before, so it also ends on a document `check_schema` refuses."""
    out = []
    while isinstance(kind, str) and kind in schema["kinds"] and kind not in out:
        out.append(kind)
        kind = schema["kinds"][kind].get("parent")
    return out


def root(schema: dict, kind: str) -> str:
    """The kind at the top of the kind's tree: the kind itself when it has no `parent`. One id names one element
    in a tree (§3.1), and the tree's elements share the root's IRI space (§3.4)."""
    return chain(schema, kind)[-1]


def declaring(schema: dict, kind: str, slot: str) -> str:
    """The kind that declares a slot: the highest kind of the chain that has it. A kind below restates it."""
    return [k for k in chain(schema, kind) if slot in schema["kinds"][k]["slots"]][-1]


def _exact(text) -> bool:
    """Exact decimal text or `n/d` (bounds of a Ratio or Quantity, a factor)."""
    return _is_text(text) and bool(_DECIMAL.fullmatch(text) or _RATIO.fullmatch(text))


def _fail(where: str, what: str):
    raise L0Error(f"{where}: {what}")


def _cj(value) -> str:
    try:
        return canonical_json(value)
    except CanonError as e:
        raise L0Error(str(e)) from e


_SCHEMA_IDS: dict[bytes, str] = {}  # pickle of a schema document -> its id; see `schema_id`
_SCHEMA_IDS_MAX = 16


def schema_id(document: dict) -> str:
    """`"s-" + H(document)` (§2.2).

    A publication asks for the id of one schema once per typed literal and per table, and hashing the whole
    document each time cost most of a forms publication. The id is remembered by the document's content, never
    by the object: the key is the document's pickle, which a change to any member, key or type changes (`True`
    and `1` pickle apart, where `==` would hold them equal). Equal pickles unpickle to equal documents, so they
    have one canonical JSON and one id. Pickling is a C-speed walk; a document that does not pickle is hashed
    every time, as before.
    """
    try:
        key = pickle.dumps(document, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:  # noqa: BLE001 - not picklable: no fingerprint, hash it as before
        key = None
    if key is not None and (sid := _SCHEMA_IDS.get(key)) is not None:
        return sid
    try:
        sid = "s-" + canonical_sha256(document)
    except CanonError as e:
        raise L0Error(f"schema: {e}") from e
    if key is not None:
        if len(_SCHEMA_IDS) >= _SCHEMA_IDS_MAX:
            _SCHEMA_IDS.pop(next(iter(_SCHEMA_IDS)))
        _SCHEMA_IDS[key] = sid
    return sid


# ---------------------------------------------------------------------------------------------------------------
# §2: the schema document


def _no_numbers(value, path: str):
    """§2.2: every integer is decimal text; no JSON number, no `null`. A boolean only where a member is one."""
    if value is None:
        _fail(path, "null in a schema document")
    if isinstance(value, bool):
        if not path.endswith(".derived"):
            _fail(path, "a boolean where text is required")
        return
    if isinstance(value, (int, float)):
        _fail(path, "integer must be text (a JSON number in a schema document)")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                _fail(path, f"key {k!r} is not text")
            _no_numbers(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _no_numbers(v, f"{path}[{i}]")


def _ordered_states(states, where: str, *, need_known: bool):
    if not isinstance(states, list) or not states or len(set(states)) != len(states):
        _fail(where, "states must be a list of distinct states")
    if any(s not in STATES for s in states):
        _fail(where, f"unknown state in {states}")
    if need_known and "known" not in states:
        _fail(where, "states must include `known`")
    if states != sorted(states, key=STATES.index):
        _fail(where, f"states {states} are not in code order")


def _local_type(schema: dict, name: str):
    """The type a slot names: a local type, a core type, or `None` for an imported `prefix.Type`."""
    if not _is_text(name):
        _fail(f"type {name!r}", "a type name is text")
    if "." in name:
        prefix = name.split(".", 1)[0]
        if prefix not in schema.get("imports", {}):
            _fail(f"type {name}", f"prefix `{prefix}` is not imported")
        return None
    if name in schema.get("types", {}):
        return schema["types"][name]
    if name in CORE_TYPES:
        return {"of": name}
    _fail(f"type {name}", "not a core type and not declared in `types`")


def _check_type(schema: dict, name: str, t: dict):
    where = f"types.{name}"
    if not _KIND.fullmatch(name) or name in CORE_TYPES:
        _fail(where, "a local type name is PascalCase and not a core type")
    if not isinstance(t, dict):
        _fail(where, "a type is an object")
    of = t.get("of")
    if of not in CORE_TYPES:
        _fail(where, f"`of` must be a core type, not {of!r}")
    extra = set(t) - _TYPE_MEMBERS[of] - {"of", "storage"}
    if extra:
        _fail(where, f"members {sorted(extra)} are not members of a {of} type")
    for bound in ("min", "max"):
        if bound in t and not (_INT.fullmatch(t[bound]) if of == "Integer" and _is_text(t[bound])
                               else _exact(t[bound])):
            _fail(where, f"`{bound}` is not " + ("integer text" if of == "Integer" else "exact decimal text"))
    if "factor" in t and not _exact(t["factor"]):
        _fail(where, "`factor` is not exact")
    if "scale" in t and not (_is_text(t["scale"]) and re.fullmatch(r"0|[1-9][0-9]*", t["scale"])):
        _fail(where, "`scale` is not a natural number")
    for member in ("pattern", "currency", "per", "unit", "storage_unit", "dimension", "enum", "over", "range"):
        if member in t and not _is_text(t[member]):
            _fail(where, f"`{member}` is text")
    if of == "Text":
        if not isinstance(t.get("normalize", []), list):
            _fail(where, "`normalize` is a list")
        for n in t.get("normalize", []):
            if n not in _NORMALIZE:
                _fail(where, f"normalize {n!r} is not one of {list(_NORMALIZE)}")
        if "pattern" in t:
            try:
                re.compile(t["pattern"])
            except re.error as e:
                _fail(where, f"pattern does not compile: {e}")
    if of == "Enum" and t.get("enum") not in schema.get("enums", {}):
        _fail(where, f"enum {t.get('enum')!r} is not declared in `enums`")
    if of == "Money" and not re.fullmatch(r"[A-Z]{3}", t.get("currency", "")):
        _fail(where, "`currency` is an ISO 4217 code")
    if of == "Period":
        if t.get("range") not in ("closed", "half_open"):
            _fail(where, "`range` is `closed` or `half_open`")
        over = _local_type(schema, t.get("over", ""))
        if over is not None and over["of"] in ("Period", "Bool", "Text", "Enum"):
            _fail(where, "`over` must be an ordered type")
    if of == "Quantity":
        for m in ("unit", "storage_unit"):
            if not isinstance(t.get(m), str) or not t[m]:
                _fail(where, f"`{m}` is required")
    if "storage" in t and not isinstance(t["storage"], str):
        _fail(where, "`storage` is an Arrow type name")


def _check_slot(schema: dict, kind_name: str, slot_name: str, slot: dict):
    where = f"{kind_name}.{slot_name}"
    if not isinstance(slot, dict):
        _fail(where, "a slot is an object")
    extra = set(slot) - _SLOT_MEMBERS
    if extra:
        _fail(where, f"members {sorted(extra)} are not slot members")
    if ("type" in slot) == ("ref" in slot):
        _fail(where, "a slot has exactly one of `type` and `ref`")
    if slot.get("card") not in ("1", "?", "*", "+"):
        _fail(where, "`card` is `1`, `?`, `*` or `+`")
    _ordered_states(slot.get("states"), where, need_known=True)
    if "type" in slot:
        _local_type(schema, slot["type"])
    else:
        ref = slot["ref"]
        if not _is_text(ref):
            _fail(where, "`ref` is text")
        if "." in ref:
            prefix, target = ref.split(".", 1)
            if prefix not in schema.get("imports", {}) or not _KIND.fullmatch(target):
                _fail(where, f"`ref` {ref!r} names no imported kind")
        elif ref not in schema["kinds"]:
            _fail(where, f"`ref` {ref!r} is not a kind of this schema")
    if "world" in slot and slot["world"] not in ("open", "closed"):
        _fail(where, "`world` is `open` or `closed`")
    if "derived" in slot and not isinstance(slot["derived"], bool):
        _fail(where, "`derived` is a boolean")
    for bound in ("min", "max"):
        if bound in slot and not _exact(slot[bound]):
            _fail(where, f"`{bound}` is not exact decimal text")
    for member in ("inverse", "expr"):
        if member in slot and not (_is_text(slot[member]) and slot[member]):
            _fail(where, f"`{member}` is text")
    if "backfill" in slot:
        _check_state_object(schema, slot, slot["backfill"], where + ".backfill")
    if "versions" in slot:
        _check_versions(slot, where + ".versions")


def _check_versions(slot: dict, where: str):
    """§3.6: a derived slot's definition versions, `{"version", "valid", "known"}` in version order."""
    versions = slot["versions"]
    if slot.get("derived") is not True:
        _fail(where, "only a derived slot lists `versions`")
    if not isinstance(versions, list) or not versions:
        _fail(where, "`versions` is a non-empty list")
    last = 0
    for i, v in enumerate(versions):
        w = f"{where}[{i}]"
        if not isinstance(v, dict) or set(v) != {"version", "valid", "known"}:
            _fail(w, "a version is `{\"version\", \"valid\", \"known\"}`")
        if not (_is_text(v["version"]) and re.fullmatch(r"[1-9][0-9]*", v["version"])) or int(v["version"]) <= last:
            _fail(w, "`version` is a natural number above the one before (version order)")
        last = int(v["version"])
        known = v["known"]
        (_datetime if _is_text(known) and "T" in known else _date)(known, w + ".known")
        valid = v["valid"]
        if not isinstance(valid, dict):
            _fail(w, "`valid` is a `$valid` object")
        axes = {"at": "DateTime" if "T" in str(valid.get("at", "")) else "Date", "during": "", "in": ""}
        _valid(None, {"versioned": {a: axes[a] for a in valid if a in axes}}, valid, w + ".valid")


def _check_versioned(schema: dict, name: str, kind: dict):
    v = kind["versioned"]
    where = f"{name}.versioned"
    if not isinstance(v, dict) or not v or set(v) - {"at", "during", "in", "known"}:
        _fail(where, "members are `at`, `during`, `in` and `known`")
    for axis in ("at", "known"):
        if axis in v and v[axis] not in ("Date", "DateTime"):
            _fail(where, f"`{axis}` is `Date` or `DateTime`")
    for axis in ("during", "in"):
        if axis not in v:
            continue
        target = v[axis]
        if not _is_text(target):
            _fail(where, f"`{axis}` names no kind")
        if "." in target:
            prefix, other = target.split(".", 1)
            if prefix not in schema.get("imports", {}) or not _KIND.fullmatch(other):
                _fail(where, f"`{axis}` {target!r} names no imported kind")
        elif target not in schema["kinds"]:
            _fail(where, f"`{axis}` names no kind")
    applies = kind.get("applies", {})
    if "applies" in kind and (not isinstance(applies, dict) or not applies):
        _fail(f"{name}.applies", "`applies` maps axes to slots")
    for axis, slot_name in applies.items():
        slot = kind["slots"].get(slot_name) if _is_text(slot_name) else None
        if axis not in ("at", "during", "in") or slot is None:
            _fail(f"{name}.applies", f"`{axis}` names no slot of the kind")
        if axis == "at" and slot.get("type") not in ("Date", "DateTime"):
            _fail(f"{name}.applies", "the `at` slot is a Date or a DateTime")
        if axis in ("during", "in") and slot.get("ref") != v.get(axis):
            _fail(f"{name}.applies", f"the `{axis}` slot is a reference to the `{axis}` kind {v.get(axis)!r}")


def check_schema(doc: dict, *, versioned: bool = True, allow_legacy: bool = False) -> str:
    """Validate a schema document (§2.1–§2.3, §3.6, §3.7) and return its schema id.

    `versioned=False` is a reader that does not implement versioned kinds: it rejects the schema, never ignores
    the member (V07). `allow_legacy=True` accepts a pre-rename sealed publication's legacy schema key (`LEGACY_SCHEMA_KEY`).
    """
    if not isinstance(doc, dict):
        _fail("schema", "a schema document is an object")
    _no_numbers(doc, "schema")
    top_members = _TOP_MEMBERS | ({LEGACY_SCHEMA_KEY} if allow_legacy else set())
    extra = set(doc) - top_members
    if extra:
        _fail("schema", f"members {sorted(extra)} are not schema members")
    for member in ("kinds", "types", "enums", "imports", "map", "reasons"):
        if member in doc and not isinstance(doc[member], dict):
            _fail("schema", f"`{member}` is an object")
    version_key = LEGACY_SCHEMA_KEY if (allow_legacy and LEGACY_SCHEMA_KEY in doc and "rezono" not in doc) else "rezono"
    if doc.get(version_key) != "1.0":
        _fail("schema", "`rezono` must be \"1.0\"")
    if not isinstance(doc.get("pack"), str) or not _PACK.fullmatch(doc["pack"]):
        _fail("schema", "`pack` is not a pack name")
    base = doc.get("base")
    if not isinstance(base, str) or not re.fullmatch(r"[a-z][a-z0-9+.-]*://\S+/", base):
        _fail("schema", "`base` is an absolute IRI ending in `/`")
    if not isinstance(doc.get("kinds"), dict):
        _fail("schema", "`kinds` is required")
    if "follows" in doc and not _SID.fullmatch(doc["follows"]):
        _fail("schema", "`follows` is a full schema id")
    for prefix, imp in doc.get("imports", {}).items():
        where = f"imports.{prefix}"
        if not isinstance(imp, dict) or set(imp) - {"pack", "schema", "manifest", "dataset"}:
            _fail(where, "members are `pack`, `schema`, `manifest`, `dataset`")
        if not _PACK.fullmatch(imp.get("pack", "")):
            _fail(where, "`pack` is not a pack name")
        if not _SID.fullmatch(imp.get("schema", "")):
            _fail(where, "`schema` must pin the pack with a full schema id `s-<64 hex>`")
        if "manifest" in imp and "dataset" not in imp:
            _fail(where, "epoch pin without hash pin: `manifest` needs `dataset`")
        if "manifest" in imp and not _MID.fullmatch(imp["manifest"]):
            _fail(where, "`manifest` is a manifest id `m-<epoch>`")
        if "dataset" in imp and not _DID.fullmatch(imp["dataset"]):
            _fail(where, "`dataset` is a full dataset hash `d-<64 hex>`")
    for name, e in doc.get("enums", {}).items():
        values = e["values"] if isinstance(e, dict) and e.get("world") == "open" else e
        if isinstance(e, dict) and set(e) != {"world", "values"}:
            _fail(f"enums.{name}", "an open enum is `{\"world\": \"open\", \"values\": [...]}`")
        if not isinstance(values, list) or len(set(values)) != len(values):
            _fail(f"enums.{name}", "values are distinct element ids")
    for code, r in doc.get("reasons", {}).items():
        where = f"reasons.{code}"
        if not _CODE.fullmatch(code):
            _fail(where, "not a reason code")
        if (not isinstance(r, dict) or set(r) != {"label", "states"} or not isinstance(r["label"], dict)
                or "en" not in r["label"]):
            _fail(where, "a reason has `label` (with `en`) and `states`")
        for tag, label in r["label"].items():
            if not _LANG.fullmatch(tag) or not _is_text(label) or not label:
                _fail(where, f"label `{tag}`: a language tag maps to text")
        _ordered_states(r["states"], where, need_known=False)
        if "known" in r["states"]:
            _fail(where, "a reason labels a state other than `known`")
        if code in CORE_REASONS and not set(r["states"]) <= set(CORE_REASONS[code]):
            _fail(where, f"the core code `{code}` labels only {list(CORE_REASONS[code])}")
    for name, t in doc.get("types", {}).items():
        _check_type(doc, name, t)
    for name, kind in doc["kinds"].items():
        if not _KIND.fullmatch(name):
            _fail(f"kinds.{name}", "a kind name is PascalCase")
        if not isinstance(kind, dict):
            _fail(name, "a kind is an object")
        extra = set(kind) - _KIND_MEMBERS
        if extra:
            _fail(name, f"members {sorted(extra)} are not kind members")
        if kind.get("world") not in ("open", "closed"):
            _fail(name, "`world` is `open` or `closed`, with no default")
        if not isinstance(kind.get("id"), dict) or set(kind["id"]) != {"type"}:
            _fail(name, "`id` is `{\"type\": …}`")
        id_type = _local_type(doc, kind["id"]["type"])
        if id_type is not None and id_type["of"] == "Bool":
            _fail(name, "an id is text: a Bool is no id type")
        if "iri" in kind and not (_is_text(kind["iri"]) and _IRI.fullmatch(kind["iri"])):
            _fail(name, "`iri` is an absolute IRI")
        # Its slots hang under it as `#<slot>` and its elements as `/<id>` (§3.4, §5), so it ends in neither.
        if "iri" in kind and (set("#?") & set(kind["iri"]) or kind["iri"].endswith("/")):
            _fail(name, "`iri` has no `#` or `?` and does not end in `/`")
        if "iri" in kind and (
            kind["iri"] == f"{base}witness"
            or kind["iri"].startswith(f"{base}witness/")
            or kind["iri"].startswith(f"{base}m-")
        ):
            _fail(name, "`iri` cannot use reserved `<base>witness` or `<base>m-` space")
        if not isinstance(kind.get("slots"), dict):
            _fail(name, "`slots` is required (maybe `{}`)")
        for slot_name, slot in kind["slots"].items():
            if slot_name.startswith(("$", "@")):
                _fail(f"{name}.{slot_name}", "a slot name cannot start with `$` or `@`")
            _check_slot(doc, name, slot_name, slot)
        if "versioned" in kind:
            if not versioned:
                _fail(name, "`versioned` not supported by this reader")
            _check_versioned(doc, name, kind)
        elif "applies" in kind:
            _fail(name, "`applies` needs a versioned kind")
        if "plane" in kind:
            if kind["plane"] != "control":
                _fail(name, "`plane` is only ever \"control\"; a data-plane kind omits it")
            if not isinstance(kind.get("owner"), str) or not kind["owner"]:
                _fail(name, "a control kind declares `owner`")
            d = kind["slots"].get("decision") or {}
            if d != {**d, "card": "1", "states": ["known"]} or not (d.get("type") == "Text" or "ref" in d):
                _fail(name, "a control kind has a slot `decision`: Text or a reference, card 1, states [known]")
        elif "owner" in kind:
            _fail(name, "`owner` is a member of a control kind only")
        if "tuple_key" in kind:
            _check_tuple_key(doc, name, kind)
    for name, kind in doc["kinds"].items():
        if "parent" in kind:
            _check_parent(doc, name, kind)
    spaces: dict[str, str] = {}
    for name in sorted(doc["kinds"]):
        space = doc["kinds"][name].get("iri") or f"{doc['base']}{name}"
        if space in spaces:
            _fail(name, f"shares its IRI with `{spaces[space]}`: an element's IRI names one kind (§3.4)")
        spaces[space] = name
    for key, iri in doc.get("map", {}).items():
        kind_name, _, slot_name = key.partition(".")
        if (kind_name not in doc["kinds"] or slot_name and slot_name not in doc["kinds"][kind_name]["slots"]
                or not (_is_text(iri) and _IRI.fullmatch(iri))):
            _fail(f"map.{key}", "maps a kind or `Kind.slot` of the schema to an absolute IRI")
        if slot_name and declaring(doc, kind_name, slot_name) != kind_name:
            _fail(f"map.{key}", "a restated slot is one property: map it on the kind that declares it")
    return schema_id(doc)


def _check_tuple_key(doc: dict, name: str, kind: dict):
    """A derived tuple's column order: its element id is the canonical JSON of its cells in this order."""
    where = f"{name}.tuple_key"
    key = kind["tuple_key"]
    if (not isinstance(key, list) or not key or not all(_is_text(c) for c in key) or len(set(key)) != len(key)
            or set(key) != set(kind["slots"])):
        _fail(where, "names every slot of the kind exactly once")
    if any(m in kind for m in ("parent", "versioned", "plane")):
        _fail(where, "a derived tuple has no `parent`, `versioned` or `plane`")
    id_type = _local_type(doc, kind["id"]["type"])
    if id_type is None or id_type["of"] != "Text" or set(id_type) != {"of"}:
        _fail(where, "a derived tuple's id is plain `Text`")
    for column in key:
        slot = kind["slots"][column]
        if (slot.get("derived") is not True or slot["card"] != "1" or slot["states"] != ["known"]
                or set(slot) & {"inverse", "versions", "backfill", "expr"}):
            _fail(f"{name}.{column}", "a tuple column is derived, card `1`, states `[known]`")


def _tuple_id(kind: dict, row: dict, payloads: dict, where: str):
    """A derived tuple's `$id` is the canonical JSON of its typed cells in `tuple_key` order."""
    parts = []
    for column in kind["tuple_key"]:
        part = row[column]["$ref"] if "ref" in kind["slots"][column] else payloads[column]
        if isinstance(part, bool):
            part = "true" if part else "false"
        if not isinstance(part, str):
            _fail(f"{where}.{column}", "a tuple cell is text in the row key")
        parts.append(part)
    if row["$id"] != _cj(parts):
        _fail(where + ".$id", "is not the canonical JSON of its cells in `tuple_key` order")


def _check_parent(doc: dict, name: str, kind: dict):
    """A subkind (§2.1 `parent`): its parent is a kind of the document, no kind is above itself, and it restates
    its parent's id type and every slot of its parent, so each kind's `slots` are all the slots of its rows."""
    parent = doc["kinds"].get(kind["parent"]) if _is_text(kind["parent"]) else None
    if parent is None:
        _fail(name, f"`parent` {kind['parent']!r} is not a kind of this schema")
    above = chain(doc, kind["parent"])
    if name in above or "parent" in doc["kinds"][above[-1]]:
        _fail(name, "a kind is not above itself: `parent` makes a tree")
    if "versioned" in kind or "versioned" in parent:
        _fail(name, "a subkind or its parent is not versioned")
    if kind["id"] != parent["id"]:
        _fail(name, f"a subkind has the id type of its parent `{kind['parent']}`: its elements are elements of it")
    for slot_name, slot in parent["slots"].items():
        mine = kind["slots"].get(slot_name)
        if mine is None:
            _fail(f"{name}.{slot_name}", f"absent; a subkind restates every slot of its parent `{kind['parent']}`")
        # `world` is stated against the kind's own world, so it is the one member the two may spell differently.
        if {k: v for k, v in mine.items() if k != "world"} != {k: v for k, v in slot.items() if k != "world"}:
            _fail(f"{name}.{slot_name}", f"differs from the slot of its parent `{kind['parent']}` that it restates")


# ---------------------------------------------------------------------------------------------------------------
# §4.4: storage


def _bounds(t: dict):
    lo = Fraction(t["min"]) if "min" in t else None
    hi = Fraction(t["max"]) if "max" in t else None
    return lo, hi


def _number_spelling(t: dict) -> bool:
    """LD2: an `Integer` with declared `min` and `max` within ±(2⁵³ − 1) is a JSON number."""
    lo, hi = _bounds(t)
    return t["of"] == "Integer" and lo is not None and hi is not None and -_SAFE <= lo and hi <= _SAFE


def _integer_storage(lo, hi) -> str:
    if lo is None or hi is None:
        return "utf8"
    if _INT64[0] <= lo and hi <= _INT64[1]:
        return "int64"
    if -_DEC38 <= lo and hi <= _DEC38:
        return "decimal128(38,0)"
    return "utf8"


def storage(schema: dict, slot: dict) -> str:
    """The Arrow storage of a slot's value column (§4.4), spelled without spaces (`decimal128(38,2)`)."""
    if "ref" in slot:
        return "utf8"
    t = _local_type(schema, slot["type"])
    if t is None:
        return "utf8"
    if "storage" in t:
        return t["storage"].replace(" ", "")
    of = t["of"]
    if of == "Integer":
        return _integer_storage(*_bounds(t))
    if of == "Quantity":
        lo, hi = _bounds(t)
        f = Fraction(t.get("factor", "1")) * 10 ** int(t.get("scale", "0"))
        if lo is None or hi is None:
            return "decimal128(38,0)"
        return "int64" if _integer_storage(lo * f, hi * f) == "int64" else "decimal128(38,0)"
    if of == "Money":
        return f"decimal128(38,{int(t.get('scale', '0'))})"
    if of == "Bool":
        return "bool"
    if of == "Date":
        return "date32"
    if of == "DateTime":
        return 'timestamp(us,"UTC")'
    if of == "Ratio":
        return "struct<numerator:decimal128(38,0),denominator:decimal128(38,0)>"
    if of == "Period":
        end = storage(schema, {"type": t["over"]})
        return f"struct<from:{end},to:{end}>"
    return "utf8"  # Text, Enum


# ---------------------------------------------------------------------------------------------------------------
# §3: row JSON


def _date(text, where: str):
    if not isinstance(text, str) or not _DATE.fullmatch(text):
        _fail(where, f"{text!r} is not a date `YYYY-MM-DD`")
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        _fail(where, f"{text!r} is not a calendar date")


def _datetime(text, where: str):
    m = _DATETIME.fullmatch(text) if isinstance(text, str) else None
    if not m:
        _fail(where, f"{text!r} is not a UTC time `YYYY-MM-DDTHH:MM:SS[.f]Z` in normal form")
    try:
        return datetime.datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        _fail(where, f"{text!r} is not a calendar time")


def _reason(schema: dict, state: str, reason, where: str):
    if not isinstance(reason, str):
        _fail(where, f"the reason {reason!r} is not text")
    if reason == "":
        return
    if not _CODE.fullmatch(reason):
        _fail(where, f"{reason!r} is not a reason code")
    if reason in CORE_REASONS and state not in CORE_REASONS[reason]:
        _fail(where, f"`{reason}` may not label `{state}`")
    reasons = schema.get("reasons")
    if reasons is None or reason in CORE_REASONS and reason not in reasons:
        return
    if reason not in reasons:
        _fail(where, f"reason code `{reason}` not declared")
    if state not in reasons[reason]["states"]:
        _fail(where, f"`{reason}` may not label `{state}`")


def _state_of(value):
    """`(state, reason)` for a state object, `None` for anything else."""
    if isinstance(value, dict) and any(k in _STATE_KEYS for k in value):
        if len(value) != 1:
            return ("", None)
        (k, reason), = value.items()
        return _STATE_KEYS[k], reason
    return None


def _check_state_object(schema: dict, slot: dict, value, where: str):
    state = _state_of(value)
    if state is None:
        _fail(where, "not a state object")
    if state[0] == "":
        _fail(where, "a state object has exactly one member")
    if state[0] not in slot["states"]:
        _fail(where, f"state `{state[0]}` not allowed; `states` is {slot['states']}")
    _reason(schema, state[0], state[1], where)


def _integer_text(value, where: str) -> int:
    if not isinstance(value, str) or not _INT.fullmatch(value):
        _fail(where, f"{value!r} is not an integer in normal form")
    return int(value)


def _in_bounds(number, t: dict, slot: dict, where: str):
    for src in (t, slot):
        lo, hi = _bounds(src)
        if lo is not None and number < lo or hi is not None and number > hi:
            _fail(where, f"{number} is outside [{src.get('min', '')}, {src.get('max', '')}]")


def _known(schema: dict, slot: dict, value, where: str):
    """Check one known value against its type's normal form (§3.2); return its payload."""
    if value is None:
        _fail(where, "null")
    if isinstance(value, float):
        _fail(where, f"{value!r} is a float")
    if "ref" in slot:
        return _reference(schema, slot["ref"], value, where)
    t = _local_type(schema, slot["type"])
    if t is None:
        _imported(slot["type"], where)
    return _typed(schema, t, slot, value, where)


def _imported(name: str, where: str):
    """A known value of an imported type: its normal form is in the pinned schema of the other pack, which this
    reader does not hold. Refused rather than read as any text (Q19)."""
    _fail(where, f"a value of the imported type `{name}` cannot be checked without its schema (Q19); refused")


def _typed(schema: dict, t: dict, slot: dict, value, where: str):
    of = t["of"]
    if of == "Bool":
        if not isinstance(value, bool):
            _fail(where, f"{value!r} is not a boolean")
        return value
    if isinstance(value, bool):
        _fail(where, f"{value!r}: a boolean for a {of}")
    if of == "Integer":
        if _number_spelling(t):
            if not isinstance(value, int):
                _fail(where, f"{value!r}: an integer within ±(2^53 − 1) is a JSON number (LD2)")
            number = value
        else:
            if isinstance(value, int):
                _fail(where, f"{value!r}: this integer is text (LD2)")
            number = _integer_text(value, where)
        _in_bounds(number, t, slot, where)
        return str(number)
    if not isinstance(value, str):
        _fail(where, f"{value!r}: a {of} is text")
    if of == "Text":
        normal = value
        for n in t.get("normalize", []):
            normal = {"uppercase": str.upper, "lowercase": str.lower, "trim": str.strip,
                      "strip spaces": lambda s: s.replace(" ", "")}[n](normal)
        if normal != value:
            _fail(where, f"{value!r} is not in normal form ({', '.join(t['normalize'])})")
        if "pattern" in t and not re.fullmatch(t["pattern"], value):
            _fail(where, f"{value!r} does not match the pattern")
        return value
    if of == "Ratio":
        m = _RATIO.fullmatch(value)
        if not m or value == "-0" or (m[4] and (int(m[4]) == 1 or gcd(int(m[1]), int(m[4])) != 1)):
            _fail(where, f"{value!r} is not a ratio `n/d` in lowest terms")
        _in_bounds(Fraction(value), t, slot, where)
        return value
    if of == "Date":
        _date(value, where)
        return value
    if of == "DateTime":
        _datetime(value, where)
        return value
    if of == "Enum":
        e = schema["enums"][t["enum"]]
        if isinstance(e, list) and value not in e:
            _fail(where, f"{value!r} is not a value of the closed enum {t['enum']}")
        return value
    if of == "Quantity":
        number, _, unit = value.partition(" ")
        if unit != t["unit"]:
            _fail(where, f"{value!r}: the unit is not {t['unit']}")
        if _DECIMAL.fullmatch(number) and number != "-0":
            n = Fraction(number)
        else:
            m = _RATIO.fullmatch(number)
            if not m or not m[4] or gcd(int(m[1]), int(m[4])) != 1 or _terminates(int(m[4])):
                _fail(where, f"{value!r}: not the shortest exact decimal (or n/d) in {t['unit']}")
            n = Fraction(number)
        _in_bounds(n, t, slot, where)
        stored = n * Fraction(t.get("factor", "1")) * 10 ** int(t.get("scale", "0"))
        if stored.denominator != 1:
            _fail(where, f"{value!r}: the stored integer is not whole")
        return str(stored.numerator)
    if of == "Money":
        m = _MONEY.fullmatch(value)
        scale = int(t.get("scale", "0"))
        if not m or len(m["dec"] or "") != scale or m["per"] != t.get("per"):
            _fail(where, f"{value!r} is not a money literal with {scale} decimals")
        if m["cur"] not in (t["currency"], _CURRENCY_SIGN.get(t["currency"])):
            _fail(where, f"{value!r}: the currency is not {t['currency']}")
        amount = Fraction(m["num"])
        if m["num"].startswith("-") and amount == 0:
            _fail(where, f"{value!r}: no negative zero")
        _in_bounds(amount, t, slot, where)
        return str((amount * 10**scale).numerator)
    if of == "Period":
        sep = "..<" if t["range"] == "half_open" else ".."
        a, found, b = value.partition(sep)
        if not found or (sep == ".." and b.startswith("<")) or not a or not b:
            _fail(where, f"{value!r} is not a {t['range'].replace('_', '-')} period `a{sep}b`")
        over = _local_type(schema, t["over"])
        if over is None:
            _imported(t["over"], where)

        def end(x):  # the ends are text inside the period, also for an Integer with the LD2 number spelling
            if over["of"] == "Integer":
                n = _integer_text(x, where)
                _in_bounds(n, over, {}, where)
                return str(n)
            return _typed(schema, over, {}, x, where)

        pa, pb = end(a), end(b)
        if over["of"] in ("Date", "DateTime", "Integer", "Ratio") and _order(over, a) > _order(over, b):
            _fail(where, f"{value!r}: the period ends before it starts")
        return {"from": pa, "to": pb}
    _fail(where, f"type {of} cannot be read")


def _terminates(d: int) -> bool:
    while d % 2 == 0:
        d //= 2
    while d % 5 == 0:
        d //= 5
    return d == 1


def _order(t: dict, text):
    if t["of"] == "Date":
        return datetime.date.fromisoformat(text)
    if t["of"] == "DateTime":
        return datetime.datetime.fromisoformat(text[:-1] + "+00:00")
    return Fraction(text)


def _reference(schema: dict, ref: str, value, where: str) -> str:
    if not isinstance(value, dict) or set(value) != {"$ref"} or not isinstance(value["$ref"], str):
        _fail(where, f"{value!r} is not a reference `{{\"$ref\": …}}`")
    target = value["$ref"]
    if "." not in ref:
        if not target:
            _fail(where, "an empty reference")
        return target
    prefix, kind = ref.split(".", 1)
    imp = schema["imports"][prefix]
    m = _PACK_REF.fullmatch(target)
    if not m:
        _fail(where, f"{target!r} is not `<pack>@s-…[@m-…]@d-…:<Kind>/<id>`")
    if m["manifest"] and not m["dataset"]:
        _fail(where, f"{target!r}: epoch pin without hash pin")
    if m["pack"] != imp["pack"] or m["schema"] != imp["schema"]:
        _fail(where, f"{target!r}: pack and schema differ from the import `{prefix}`")
    if m["kind"] != kind:
        _fail(where, f"{target!r}: the kind is not {kind}")
    if m["dataset"] != imp.get("dataset"):
        _fail(where, f"{target!r}: hash pin differs from the import")
    if m["manifest"] != imp.get("manifest"):
        _fail(where, f"{target!r}: epoch pin differs from the import")
    return m["id"]


def _valid(schema: dict, kind: dict, valid, where: str):
    axes = kind["versioned"]
    if not isinstance(valid, dict):
        _fail(where, "`$valid` is an object")
    if not valid:
        _fail(where, "empty `$valid` must be omitted")
    for axis, v in valid.items():
        if axis not in ("at", "during", "in") or axis not in axes:
            _fail(where, f"axis `{axis}` not declared")
        if axis == "at":
            parse = _date if axes["at"] == "Date" else _datetime
            if not isinstance(v, str):
                _fail(where, "`$valid.at` is text")
            a, found, b = v.partition("..<")
            if found and not b:
                _fail(where, f"`$valid.at` {v!r}: `..<` needs an end; an open end is `a..`")
            if not found:
                a, found, b = v.partition("..")
                if not found or b:
                    _fail(where, f"closed range in `$valid.at`: {v!r}" if found else f"{v!r} is not a range")
            if parse(a, where) >= (parse(b, where) if b else parse(a, where)) and b:
                _fail(where, f"`$valid.at` {v!r} is empty")
        elif axis == "during":
            if not isinstance(v, str) or not v:
                _fail(where, "`$valid.during` is a stage or a half-open stage range")
            a, found, b = v.partition("..<")
            if found and not b:
                _fail(where, f"`$valid.during` {v!r}: `..<` needs an end; an open end is `s1..`")
            if not found:
                a, found, b = v.partition("..")
                if found and b:
                    _fail(where, f"closed range in `$valid.during`: {v!r}")
            if not a:
                _fail(where, f"{v!r} has no first stage")
        else:
            if not isinstance(v, list) or not v or not all(isinstance(s, str) and s for s in v):
                _fail(where, "`$valid.in` is a list of setup ids")
            if [_cj(s) for s in v] != sorted({_cj(s) for s in v}, key=lambda s: s.encode("utf-8")):
                _fail(where, "`$valid.in` is distinct and in hash order")


def read_row(schema: dict, row: dict) -> tuple:
    """Read one row (§3.1–§3.6) under an accepted schema; return its key `(kind, id, $valid, $known)`.

    This is a dataset reader: text not in its normal form is rejected (the delta profile, §7, is not read here).
    """
    if not isinstance(row, dict):
        _fail("row", "a row is an object")
    _strict(row, "row")
    if "@context" in row:
        _context(row["@context"], "row.@context")
    name, rid = row.get("$kind"), row.get("$id")
    if not isinstance(name, str) or not isinstance(rid, str) or not rid:
        _fail("row", "a row has `$kind` and `$id` as text")
    where = f"{name}/{rid}"
    kind = schema["kinds"].get(name)
    if kind is None:
        _fail(where, f"`{name}` is not a kind of the schema")
    for member in row:
        if member.startswith("$") and member not in _ROW_MEMBERS:
            _fail(where, f"undefined $-member `{member}`")
        if member.startswith("@") and member != "@context":
            _fail(where, f"undefined @-member `{member}`")
        if not member.startswith(("$", "@")) and member not in kind["slots"]:
            _fail(where, f"`{member}` is not a slot of {name}")
    if "$schema" in row and not (isinstance(row["$schema"], str) and _SID.fullmatch(row["$schema"])):
        _fail(where, "`$schema` is a full schema id")
    if "$schema" in row and row["$schema"] != schema_id(schema):
        _fail(where, "`$schema` is not the id of the schema read under")
    _id_value(schema, kind, rid, where)
    versioned = kind.get("versioned")
    if versioned is None:
        for m in ("$valid", "$known"):
            if m in row:
                _fail(where, f"`{name}` is not versioned: `{m}` is not allowed")
    else:
        if "$valid" in row:
            _valid(schema, kind, row["$valid"], where)
        if "known" in versioned:
            if "$known" not in row:
                _fail(where, "`$known` missing; `known` is declared")
            (_date if versioned["known"] == "Date" else _datetime)(row["$known"], where + ".$known")
        elif "$known" in row:
            _fail(where, "`$known` present; `known` is not declared")

    payloads = {}
    for slot_name, slot in kind["slots"].items():
        sw = f"{where}.{slot_name}"
        if "inverse" in slot:
            if slot_name in row:
                _fail(sw, "an inverse slot is not written as data (§3.4)")
            continue
        if slot_name not in row:
            _fail(sw, "absent; every slot is present (absence is a state, written explicitly)")
        value = row[slot_name]
        if _state_of(value) is not None:
            _check_state_object(schema, slot, value, sw)
            continue
        if slot["card"] in ("1", "?"):
            payloads[slot_name] = _known(schema, slot, value, sw)
            continue
        if not isinstance(value, list):
            _fail(sw, "a many-valued slot is a list or a state object")
        if slot["card"] == "+" and not value:
            _fail(sw, "card `+` needs at least one member")
        seen = set()
        for i, member in enumerate(value):
            payload = _known(schema, slot, member, f"{sw}[{i}]")
            key = payload if isinstance(payload, str) else _cj(payload)
            if key in seen:
                _fail(sw, f"duplicate member {key!r}")
            seen.add(key)

    if "tuple_key" in kind:
        _tuple_id(kind, row, payloads, where)
    _side(schema, kind, row, where)
    valid = _cj(row.get("$valid", {})) if versioned is not None else ""
    return (name, rid, valid, row.get("$known", ""))


def _id_value(schema: dict, kind: dict, rid: str, where: str):
    """`$id` is text in its id type's normal form (an Integer id is always text: LD2 is for slots)."""
    t = _local_type(schema, kind["id"]["type"])
    if t is None:
        _imported(kind["id"]["type"], where + ".$id")
    if t["of"] == "Integer":
        _in_bounds(_integer_text(rid, where + ".$id"), t, {}, where + ".$id")
    else:
        _typed(schema, t, {}, rid, where + ".$id")


def _context(value, where: str):
    """`@context` (§5) is read by the RDF form; here it holds no JSON number (§3.2: only an LD2 slot has one)."""
    if isinstance(value, int) and not isinstance(value, bool):
        _fail(where, f"{value!r}: a JSON number outside an LD2 slot")
    if isinstance(value, dict):
        for v in value.values():
            _context(v, where)
    elif isinstance(value, list):
        for v in value:
            _context(v, where)


def _source_problem(s) -> str:
    """Which rule of `Source` (contracts/source.yaml) or of the epoch pin (§6.4) a source breaks, or ''."""
    if not isinstance(s, dict) or set(s) - _SOURCE_FIELDS or not all(_is_text(v) for v in s.values()):
        return "its members are those of a Source, each text"
    if not {"kind", "name", "position"} <= set(s) or s["kind"] not in _SOURCE_KINDS:
        return "a Source has `kind`, `name` and `position`"
    if s["kind"] in ("git", "proposal") and "revision" not in s:
        return f"a {s['kind']} Source pins its `revision`"
    pin = _EPOCH_PIN.fullmatch(s.get("revision", ""))
    if pin and not pin["hash"]:
        return "epoch pin without hash pin: a cited manifest is `m-<epoch>@d-<64 hex>` (§6.4)"
    if "url" in s and not _URL.fullmatch(s["url"]):
        return "`url` is an absolute HTTP(S) URL"
    if "retrieved_at" in s:
        if not _INSTANT.fullmatch(s["retrieved_at"]):
            return "`retrieved_at` is a UTC instant"
        try:
            datetime.datetime.fromisoformat(s["retrieved_at"].replace("Z", "+00:00"))
        except ValueError:
            return "`retrieved_at` is a UTC instant"
    if "fragment_sha256" in s and not re.fullmatch(r"[0-9a-f]{64}", s["fragment_sha256"]):
        return "`fragment_sha256` is 64 hex"
    if "ownership" in s and s["ownership"] not in ("first_party", "third_party"):
        return "`ownership` is `first_party` or `third_party`"
    if any(f in s and not _TRIMMED.fullmatch(s[f]) for f in ("licence", "attribution")):
        return "`licence` and `attribution` are trimmed text"
    if s["kind"] == "document" and (
            not _TRIMMED.fullmatch(s["position"]) or not {"url", "fragment_sha256", "licence", "attribution"} <= set(s)
            or "revision" in s and not _TRIMMED.fullmatch(s["revision"]) or not {"revision", "retrieved_at"} & set(s)):
        return "a document Source has a position, `url`, `fragment_sha256`, `licence`, `attribution` and a version"
    if s.get("ownership") == "third_party" and not {"licence", "attribution"} <= set(s):
        return "a third-party Source has `licence` and `attribution`"
    return ""


def _side(schema: dict, kind: dict, row: dict, where: str):
    """`$why` and `$src` (§3.5): their shape. What they may hold for a role is the publisher's (may_read)."""
    if "$why" in row:
        why = row["$why"]
        if not isinstance(why, dict):
            _fail(where, "`$why` is an object")
        for slot_name, proof in why.items():
            slot = kind["slots"].get(slot_name)
            if slot_name != "$id" and slot is None:
                _fail(where, f"`$why` names `{slot_name}`, not a slot")
            if slot is not None and slot["card"] in ("*", "+"):
                if not isinstance(proof, dict) or not all(_is_text(u) and _IRI.fullmatch(u) for u in proof.values()):
                    _fail(where, f"`$why.{slot_name}` maps member payloads to proof URIs")
            elif not _is_text(proof) or not _IRI.fullmatch(proof):
                _fail(where, f"`$why.{slot_name}` is a proof URI")
    if "$src" in row:
        src = row["$src"]
        if not isinstance(src, dict):
            _fail(where, "`$src` is an object")
        for slot_name, sources in src.items():
            if slot_name != "$id" and slot_name not in kind["slots"]:
                _fail(where, f"`$src` names `{slot_name}`, not a slot")
            if not isinstance(sources, list) or not sources:
                _fail(where, f"`$src.{slot_name}` is an array of Source objects")
            for i, s in enumerate(sources):
                problem = _source_problem(s)
                if problem:
                    _fail(f"{where}.$src.{slot_name}[{i}]", problem)
            texts = [_cj(s) for s in sources]
            if texts != sorted(set(texts)):
                _fail(where, f"`$src.{slot_name}` is distinct and sorted by canonical JSON")


def read_rows(schema: dict, rows: list) -> list:
    """Read the rows of one dataset: each row, and no two rows with one key (§3.1). Returns the rows."""
    if not isinstance(rows, list):
        _fail("rows", "rows are a list")
    seen, elements = set(), {}
    for row in rows:
        key = read_row(schema, row)
        if key in seen:
            _fail(f"{key[0]}/{key[1]}", "two rows with one `$kind` and `$id`" +
                  (" (and one `$valid` and `$known`)" if key[2] else ""))
        seen.add(key)
        # One id names one element in a kind tree, written once, at its most specific kind (§3.1).
        tree = root(schema, key[0])
        if elements.setdefault((tree, key[1]), key[0]) != key[0]:
            _fail(f"{key[0]}/{key[1]}", f"also a row of `{elements[tree, key[1]]}`: an element of the tree of "
                  f"`{tree}` is written once, at its most specific kind")
    return rows


def read_collection(schema: dict, doc: dict) -> list:
    """A collection `{"$schema": "s-…", "$rows": [...]}` (§3.1). Returns the rows."""
    if not isinstance(doc, dict) or "$rows" not in doc or "$schema" not in doc:
        _fail("collection", "a collection is `{\"$schema\": \"s-…\", \"$rows\": [...]}`")
    extra = set(doc) - {"$schema", "$rows", "@context"}
    if extra:
        _fail("collection", f"undefined members {sorted(extra)}")
    _strict({k: v for k, v in doc.items() if k != "$rows"}, "collection")
    if "@context" in doc:
        _context(doc["@context"], "collection.@context")
    sid = doc["$schema"]
    if not isinstance(sid, str) or not _SID.fullmatch(sid):
        _fail("collection", "`$schema` is a full schema id `s-<64 hex>`")
    if sid != schema_id(schema):
        _fail("collection", "`$schema` is not the id of the schema read under")
    return read_rows(schema, doc["$rows"])


def _strict(value, where: str = "$"):
    """I-JSON (RFC 7493) as Rezono reads it: no null, no float, no lone surrogate."""
    if value is None:
        _fail(where, "null")
    if isinstance(value, float):
        _fail(where, f"{value!r} is a float")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            _fail(where, "a lone surrogate")
    elif isinstance(value, dict):
        for k, v in value.items():
            _strict(k, where)
            _strict(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _strict(v, f"{where}[{i}]")


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            _fail("json", f"duplicate key {k!r}")
        out[k] = v
    return out


def _no_float(text):
    _fail("json", f"{text} is not an integer (no float, also not 1.0 or 1e1)")


def loads(text: str):
    """Parse JSON text as a reader must (§3.1): duplicate keys, floats, `null` and lone surrogates refused."""
    if text.startswith("﻿"):
        _fail("json", "a byte order mark")
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_float=_no_float, parse_constant=_no_float)
    except json.JSONDecodeError as e:
        raise L0Error(f"json: {e}") from e
    _strict(value)
    if _has_negative_zero(text):
        _fail("json", "-0 is not an integer in normal form")
    return value


def _has_negative_zero(text: str) -> bool:
    """`-0` as a JSON number: `json` reads it as 0, so look at the tokens outside strings."""
    out, in_string, escape = [], False, False
    for ch in text:
        if in_string:
            if escape:
                escape = False  # the character after a backslash never ends the string
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            out.append(" ")
        else:
            out.append(ch)
    return re.search(r"(?<![0-9])-0(?![0-9])", "".join(out)) is not None


def read_jsonl(schema: dict, text: str) -> list:
    """JSON Lines: a header `{"$schema": "s-…", "rezono": "1.0"}`, then one row per line (§3.1)."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        _fail("jsonl", "no header line")
    header = loads(lines[0])
    if header != {"$schema": schema_id(schema), "rezono": "1.0"}:
        _fail("jsonl", "the header is not `{\"$schema\": <id of the schema>, \"rezono\": \"1.0\"}`")
    return read_rows(schema, [loads(line) for line in lines[1:]])


# ---------------------------------------------------------------------------------------------------------------
# §4.2, §4.4, §4.5: columnar metadata


def _norm_type(t: str) -> str:
    """An Arrow type as L0 spells it (§4.4): pyarrow's `str(type)` or L0's own spelling, without spaces."""
    t = re.sub(r"(?<![a-z_])string(?![a-z_])", "utf8", t.replace(" ", ""))
    t = t.replace("date32[day]", "date32").replace("timestamp[us,tz=UTC]", 'timestamp(us,"UTC")')
    return "utf8" if t.startswith("dictionary<values=utf8,") else t


def _expected_extension(schema: dict, slot: dict):
    if "ref" in slot:
        ref = slot["ref"]
        if "." not in ref:
            return "rezono.ref", {"kind": ref}
        prefix, kind = ref.split(".", 1)
        imp = schema["imports"][prefix]
        meta = {"kind": kind, "pack": imp["pack"], "schema": imp["schema"]}
        meta.update({k: imp[k] for k in ("manifest", "dataset") if k in imp})
        return "rezono.ref", meta
    t = _local_type(schema, slot["type"])
    if t is None:
        return None
    if t["of"] == "Quantity":
        return "rezono.quantity", {"type": slot["type"], "unit": t["unit"], "storage_unit": t["storage_unit"],
                                   "factor": t.get("factor", "1"), "scale": t.get("scale", "0")}
    if t["of"] == "Money":
        meta = {"type": slot["type"], "currency": t["currency"], "scale": t.get("scale", "0")}
        if "per" in t:
            meta["per"] = t["per"]
        return "rezono.money", meta
    return None


def check_field(schema: dict, kind_name: str, field: dict):
    """One value column of a kind table: its storage and its extension restate the schema exactly (§4.4, §4.5).

    `field` is `{"name", "storage", "extension": {"name", "metadata"}}`: the storage type as Arrow prints it, and
    the extension name and metadata (decoded) when the column carries one.
    """
    slot = schema["kinds"][kind_name]["slots"].get(field["name"])
    where = f"{kind_name}.{field['name']}"
    if slot is None:
        _fail(where, "not a slot of the kind")
    want, got = storage(schema, slot), _norm_type(field["storage"])
    if "float" in got or "double" in got or "halffloat" in got:
        _fail(where, f"{field['storage']}: floating-point types MUST NOT occur")
    dw, dg = re.fullmatch(r"decimal128\((\d+),(\d+)\)", want), re.fullmatch(r"decimal(?:128)?\((\d+),(\d+)\)", got)
    if dw and dg:
        if dg[2] != dw[2]:
            _fail(where, f"storage scale {dg[2]} differs from the schema's scale {dw[2]}")
        if int(dg[1]) > 38 or (want.endswith(",0)") and int(dg[1]) != 38):
            _fail(where, f"storage {field['storage']} is not {want}")
    elif got != want:  # a dictionary of utf8 is utf8 (`_norm_type`); any other dictionary differs
        _fail(where, f"storage {field['storage']} differs from the schema's {want}")
    expected = _expected_extension(schema, slot)
    ext = field.get("extension")
    if expected is None:
        if ext:
            _fail(where, f"extension {ext.get('name')} on a column that takes none")
        return
    if not ext or ext.get("name") != expected[0]:
        _fail(where, f"the column needs the extension `{expected[0]}`")
    meta = ext.get("metadata", {})
    if not isinstance(meta, dict):
        _fail(where, "extension metadata is an object")
    for member in sorted(set(meta) | set(expected[1])):
        if member not in meta or member not in expected[1] or meta[member] != expected[1][member]:
            _fail(where, f"extension metadata `{member}` differs from the schema")


def check_table_metadata(schema: dict, meta: dict):
    """The `rezono` member of Arrow schema or Parquet file metadata (§4.2)."""
    where = "metadata.rezono"
    if not isinstance(meta, dict):
        _fail(where, "`rezono` is the canonical JSON of an object")
    allowed = {"rezono", "schema", "table", "role", "plane", "dataset", "table_hash", "manifest"}
    if set(meta) - allowed:
        _fail(where, f"undefined members {sorted(set(meta) - allowed)}")
    if meta.get("rezono") != "1.0":
        _fail(where, "`rezono` must be \"1.0\"")
    if meta.get("schema") != schema_id(schema):
        _fail(where, "`schema` is not the id of the schema read under")
    if meta.get("role") not in ("kind", "relation", "why", "src"):
        _fail(where, "`role` is `kind`, `relation`, `why` or `src`")
    if "manifest" in meta and "dataset" not in meta:
        _fail(where, "`manifest` without `dataset`: an epoch pin needs its hash pin")
    if "dataset" in meta and not (_is_text(meta["dataset"]) and _DID.fullmatch(meta["dataset"])):
        _fail(where, "`dataset` is a full dataset hash")
    if "manifest" in meta and not (_is_text(meta["manifest"]) and _MID.fullmatch(meta["manifest"])):
        _fail(where, "`manifest` is a Rezono manifest id `m-<epoch>`")
    if "table_hash" in meta and not (_is_text(meta["table_hash"]) and re.fullmatch(r"[0-9a-f]{64}", meta["table_hash"])):
        _fail(where, "`table_hash` is a table hash, 64 hex (§6.2 step 4)")
    table = meta.get("table")
    owner = table.split("__", 1)[0] if isinstance(table, str) else None
    kind = schema["kinds"].get(owner)
    if meta["role"] in ("kind", "relation"):
        if kind is None or (meta["role"] == "kind") != ("__" not in table):
            _fail(where, f"`table` {table!r} is not a {meta['role']} table of the schema")
        if meta["role"] == "relation":
            slot = kind["slots"].get(table.split("__", 1)[1])
            if slot is None or slot["card"] not in ("*", "+") or "inverse" in slot:
                _fail(where, f"`table` {table!r} is not a relation table of the schema")
        if ("plane" in meta) != (kind.get("plane") == "control") or meta.get("plane", "control") != "control":
            _fail(where, "`plane` is \"control\" exactly for a table of a control kind")
    elif table != f"${meta['role']}" or "plane" in meta:
        _fail(where, f"a side table is `${meta['role']}`, without `plane`")


# ---------------------------------------------------------------------------------------------------------------
# §2.4: change classes

_RANK = {"patch": 0, "minor": 1, "major": 2, "invalid_successor": 3}


def _codes_used(datasets) -> set:
    used = set()
    for rows in datasets:
        for row in rows:
            for v in row.values():
                state = _state_of(v)
                if state and state[1] and state[1] not in CORE_REASONS:
                    used.add((state[1], state[0]))
    return used


def _bounds_widened(a: dict, b: dict) -> bool:
    """Only `min` lowered or `max` raised (or kept): the rest of the object unchanged."""
    def rest(t):
        return {k: v for k, v in t.items() if k not in ("min", "max")}

    if rest(a) != rest(b):
        return False
    if ("min" in a) != ("min" in b) and "min" in b or ("max" in a) != ("max" in b) and "max" in b:
        return False  # a bound introduced narrows
    return (("min" not in b or Fraction(b["min"]) <= Fraction(a["min"]))
            and ("max" not in b or Fraction(b["max"]) >= Fraction(a["max"])))


def classify(a: dict, b: dict, datasets=()) -> tuple:
    """The change class from schema A to its successor B (§2.4): `(class, reasons)`.

    `class` is `patch`, `minor`, `major` or `invalid_successor` (a slot added without `backfill`); `reasons` names
    each change that set it. `datasets` are the row lists published under the lineage, for introducing `reasons`.
    """
    check_schema(a)
    check_schema(b)
    found = []  # (class, why)

    def note(cls, why):
        found.append((cls, why))

    for member in sorted(_TOP_MEMBERS | set(a) | set(b)):
        va, vb = a.get(member), b.get(member)
        if va == vb or member in ("kinds", "types", "reasons", "map", "enums", "imports"):
            continue
        if member == "follows":
            note("patch", "`follows`")
        else:
            note("major", f"`{member}` changed")

    for name in sorted(set(a.get("map", {})) | set(b.get("map", {}))):
        ma, mb = a.get("map", {}).get(name), b.get("map", {}).get(name)
        if ma != mb:
            note("patch" if ma is None else "major", f"map `{name}` " + ("added" if ma is None else "changed"))

    for name in sorted(set(a.get("imports", {})) | set(b.get("imports", {}))):
        ia, ib = a.get("imports", {}).get(name), b.get("imports", {}).get(name)
        if ia != ib:
            note("minor" if ia is None else "major", f"import `{name}` " + ("added" if ia is None else "changed"))

    for name in sorted(set(a.get("enums", {})) | set(b.get("enums", {}))):
        ea, eb = a.get("enums", {}).get(name), b.get("enums", {}).get(name)
        if ea == eb:
            continue
        if ea is None:
            note("minor", f"enum `{name}` added")
        elif (isinstance(ea, dict) and isinstance(eb, dict) and set(ea["values"]) < set(eb["values"])
              and eb["values"][:len(ea["values"])] == ea["values"]):
            note("minor", f"a value added to the open enum `{name}`")
        else:
            note("major", f"enum `{name}` changed or removed")

    for name in sorted(set(a.get("types", {})) | set(b.get("types", {}))):
        ta, tb = a.get("types", {}).get(name), b.get("types", {}).get(name)
        if ta == tb:
            continue
        if ta is None:
            note("minor", f"type `{name}` added")
            continue
        if tb is None:
            note("major", f"type `{name}` removed")
            continue
        slot = {"type": name}
        same_storage = storage(a, slot) == storage(b, slot)
        same_spelling = _number_spelling(ta) == _number_spelling(tb)
        if _bounds_widened(ta, tb) and same_storage and same_spelling:
            note("minor", f"type `{name}`: a bound widened")
        elif _bounds_widened(ta, tb):
            note("major", f"type `{name}`: storage and LD2 spelling change" if not (same_storage or same_spelling)
                 else f"type `{name}`: " + ("storage change" if not same_storage else "LD2 spelling change"))
        else:
            note("major", f"type `{name}` changed")

    ra, rb = a.get("reasons"), b.get("reasons")
    if ra != rb:
        if ra is None:
            missing = sorted(f"{c} ({s})" for c, s in _codes_used(datasets)
                             if c not in rb or s not in rb[c]["states"])
            note("major" if missing else "minor",
                 f"`reasons` introduced without {', '.join(missing)}" if missing
                 else "`reasons` introduced, listing every code the datasets use")
        elif rb is None:
            note("major", "`reasons` removed")
        else:
            for code in sorted(set(ra) | set(rb)):
                ca, cb = ra.get(code), rb.get(code)
                if ca == cb:
                    continue
                if ca is None:
                    note("minor", f"reason code `{code}` added")
                elif cb is None:
                    note("major", f"reason code `{code}` removed")
                elif ca["states"] != cb["states"]:
                    note("major", f"reason code `{code}`: states changed")
                else:
                    note("patch", f"reason code `{code}`: label")

    for name in sorted(set(a["kinds"]) | set(b["kinds"])):
        ka, kb = a["kinds"].get(name), b["kinds"].get(name)
        if ka == kb:
            continue
        if ka is None:
            note("minor", f"kind `{name}` added")
            continue
        if kb is None:
            note("major", f"kind `{name}` removed")
            continue
        for member in sorted((set(ka) | set(kb)) - {"slots"}):
            if ka.get(member) != kb.get(member):
                note("patch" if member == "owner" and "owner" in ka and "owner" in kb else "major",
                     f"`{name}.{member}` changed")
        for slot_name in sorted(set(ka["slots"]) | set(kb["slots"])):
            sa, sb = ka["slots"].get(slot_name), kb["slots"].get(slot_name)
            if sa == sb:
                continue
            where = f"{name}.{slot_name}"
            if sa is None:
                if "backfill" in sb:
                    note("minor", f"slot `{where}` added with `backfill`")
                else:
                    note("invalid_successor", f"added slot without `backfill`: `{where}`")
            elif sb is None:
                note("major", f"slot `{where}` removed")
            else:
                rest_a = {k: v for k, v in sa.items() if k != "versions"}
                rest_b = {k: v for k, v in sb.items() if k != "versions"}
                va, vb = sa.get("versions", []), sb.get("versions", [])
                appended = len(vb) > len(va) and vb[:len(va)] == va
                if rest_a == rest_b and appended:
                    note("minor", f"slot `{where}`: a version appended")
                elif rest_a != rest_b and (va == vb or appended) and _bounds_widened(rest_a, rest_b):
                    note("minor", f"slot `{where}`: a bound widened")  # slot bounds never set storage
                else:
                    note("major", f"slot `{where}` changed")

    if not found:
        return "patch", []
    top = max((cls for cls, _ in found), key=_RANK.get)
    return top, [why for cls, why in found if cls == top]


def read_under(a: dict, b: dict, rows: list) -> list:
    """Rows of a dataset of A read under a minor (or patch) successor B: each added slot in its `backfill` state."""
    cls, why = classify(a, b, [rows])
    if _RANK[cls] > _RANK["minor"]:
        _fail("read_under", f"B is not a minor successor of A ({cls}: {'; '.join(why)})")
    read_rows(a, rows)
    out = []
    for row in rows:
        new = dict(row)
        for slot_name, slot in b["kinds"][row["$kind"]]["slots"].items():
            if slot_name not in a["kinds"][row["$kind"]]["slots"] and "inverse" not in slot:
                new[slot_name] = dict(slot["backfill"])
        out.append(new)
    read_rows(b, out)
    return out


# ---------------------------------------------------------------------------------------------------------------
# §3.7: admission (LS0)


def admit(schema: dict, delta: list, reviewed) -> list:
    """Admission of a delta under the epoch's schema (§3.7, LS0): one validator for batch, service and outside.

    The schema is checked here (`check_schema`), never trusted: admission is a reader, and a reader rejects a
    control kind without its marker, owner or `decision` slot (§3.7). The delta is then read as a dataset
    (`read_rows`). A row of a control kind is refused unless `reviewed(decision)` returns the boolean `True`: its
    `decision` (its text, or the id a reference names) must name a reviewed proposal or owner decision (DV1); an
    empty `decision` names none. A
    data-plane row never needs the compiler or a review. Returns the delta.
    """
    check_schema(schema)
    read_rows(schema, delta)
    for row in delta:
        kind = schema["kinds"][row["$kind"]]
        if kind.get("plane") != "control":
            continue
        where = f"{row['$kind']}/{row['$id']}"
        slot = kind["slots"]["decision"]
        decision = (_reference(schema, slot["ref"], row["decision"], f"{where}.decision") if "ref" in slot
                    else row["decision"])  # a reference's target id (§3.4), never the text of a pinned `$ref`
        if decision == "":
            _fail(where, "an empty `decision` names no reviewed proposal (DV1); refused")
        if reviewed(decision) is not True:
            _fail(where, f"`decision` {decision!r} names no reviewed proposal (DV1); refused")
    return delta
