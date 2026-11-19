"""Admission of completeness receipts: the one shared check of decisions/scoped-completeness.md.

A candidate `CompletenessReceipt` is an archived-file reference (`file`, `uri`, `sha256`) to the canonical
bytes of a receipt. It selects bytes to check and confers no authority over them. The authority is a trusted
context from the verified definition or the protected caller, never from the candidate: a dict with the same
six fields as a receipt body.

- `source`, `issuer`, `scope` and `cut`: what the pack or the protected admission policy allows. The issuer's
  `authorization` is a pinned declaration that names the issuer (`{"issuer": <id>, ...}`).
- `inventory`: an archived-file reference to the expected member keys, enumerated independently of the
  submitted rows (a replayed enumeration or the source's own commitment).
- `content`: an archived-file reference to the authoritative contents keyed by those members, each with its
  rows and its terminal read evidence. A caller that replays the enumeration pins its replay here.

A candidate is admitted only when its bytes, id and pins verify, an authority covers its source, scope, cut
and issuer, its inventory equals the trusted inventory, its contents cover exactly the trusted members, and
every member's rows and terminal evidence equal the trusted contents. Identical retries, in any order,
coalesce; conflicting contents for one key reject the read. Equal counts or a digest over the received subset
never suffice. A trusted empty inventory admits an empty read; a candidate's own empty inventory admits
nothing. Anything missing, unreadable or mismatched leaves coverage unknown: the candidate is not admitted.

Only an admitted receipt supplies a row of the protected relation `verified_receipt`
(Receipt, Source, Scope, Cut, InventoryHash, ContentHash): the receipt id, the source name, the canonical
hashes of scope and cut, and the hashes of the trusted inventory and contents. `admit` gives those rows;
`check` holds the published `verified_receipt` snapshot against them.
"""

import json

from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex

FORMAT = "rezono.completeness-receipt/1"
RELATION = "verified_receipt"
BODY = ("source", "issuer", "scope", "cut", "inventory", "content")


class Unverified(Exception):
    """A receipt that is not admitted: `code` names the failed check, `detail` says where."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def receipt_id(body: dict) -> str:
    """The id of a receipt body: SHA-256 of the canonical ["rezono.completeness-receipt/1", body]."""
    return canonical_sha256([FORMAT, body])


def verify(reference, authorities, read_bytes) -> tuple[str, ...]:
    """Admit one candidate receipt reference against the trusted `authorities`.

    Returns the key parts of its `verified_receipt` row. Raises Unverified when it is not admitted.
    `read_bytes(uri)` returns the stored bytes (None or KeyError when absent), as for snapshots.
    """
    receipt = _read(reference, read_bytes, "receipt")
    if not (isinstance(receipt, dict) and set(receipt) == {"id", *BODY}):
        raise Unverified("receipt_malformed", "a receipt has exactly id, " + ", ".join(BODY))
    body = {field: receipt[field] for field in BODY}
    if receipt["id"] != receipt_id(body):
        raise Unverified("receipt_id_mismatch", str(receipt["id"]))
    _shape(body, "receipt")

    authority = _authority(body, authorities)
    declaration = _read(authority["issuer"]["authorization"], read_bytes, "authorization")
    if not (isinstance(declaration, dict) and declaration.get("issuer") == body["issuer"]["id"]):
        raise Unverified("receipt_issuer_unauthorized", "the pinned declaration does not name the issuer")
    _read(authority["scope"]["definition"], read_bytes, "scope_definition")

    # The expected population comes from the trusted context alone, never from the candidate.
    expected = _inventory(_read(authority["inventory"], read_bytes, "authority_inventory"), "authority_inventory")
    trusted = _members(_read(authority["content"], read_bytes, "authority_content"), "authority_content")
    if set(trusted) != expected:
        raise Unverified("authority_content_mismatch", "the trusted contents do not cover the trusted inventory")

    covered = _inventory(_read(body["inventory"], read_bytes, "inventory"), "inventory")
    if covered != expected:
        raise Unverified("receipt_inventory_mismatch", _difference(expected, covered))
    submitted = _members(_read(body["content"], read_bytes, "content"), "content")
    if set(submitted) != expected:
        raise Unverified("receipt_member_mismatch", _difference(expected, set(submitted)))
    changed = sorted(key for key in expected if submitted[key] != trusted[key])
    if changed:
        raise Unverified("receipt_content_mismatch", "members " + ", ".join(changed))
    # The scope and cut as the trusted context binds them: a candidate's own references confer nothing.
    return (receipt["id"], body["source"]["name"], canonical_sha256(authority["scope"]),
            canonical_sha256(authority["cut"]), authority["inventory"]["sha256"], authority["content"]["sha256"])


def admit(references, authorities, read_bytes) -> tuple[dict, list]:
    """Every candidate of a manifest's `completeness_receipts`: ({canonical row key: key parts} of the
    admitted ones, [(index, Unverified)] of the rest)."""
    if not isinstance(references, list):
        return {}, [(None, Unverified("receipts_malformed", "completeness_receipts is a list"))]
    authorities = list(authorities or ())
    admitted, rejected = {}, []
    for index, reference in enumerate(references):
        try:
            parts = verify(reference, authorities, read_bytes)
        except Unverified as e:
            rejected.append((index, e))
        else:
            admitted[canonical_json(list(parts))] = parts
    return admitted, rejected


def check(manifest: dict, read_bytes, authorities, protected_rows) -> list:
    """Checker findings for one complete epoch. Each row of `verified_receipt` (`protected_rows`, the
    snapshot as read_rows gives it) must be a row an admitted receipt supplies (`receipt_not_admitted`).
    A candidate that is not admitted is reported (`receipt_unverified`): its coverage stays unknown."""
    references = manifest.get("completeness_receipts", [])
    if not references and not protected_rows:
        return []
    admitted, rejected = admit(references, authorities, read_bytes)
    findings = [{"reason": "receipt_unverified", "detail": f"{'' if i is None else f'receipt {i}: '}{e}"}
                for i, e in rejected]
    for key in sorted(protected_rows or {}):
        if key not in admitted:
            findings.append({"reason": "receipt_not_admitted", "relation": RELATION, "key": key})
    return findings


def _read(reference, read_bytes, what):
    """The canonical JSON value an archived-file reference pins."""
    if not (isinstance(reference, dict) and all(isinstance(reference.get(f), str) for f in ("file", "uri", "sha256"))):
        raise Unverified(f"{what}_reference_malformed", "an archived file has file, uri and sha256")
    try:
        data = read_bytes(reference["uri"])
    except (LookupError, OSError, ValueError):
        data = None
    if data is None:
        raise Unverified(f"{what}_unreadable", reference["file"])
    if sha256_hex(data) != reference["sha256"]:
        raise Unverified(f"{what}_hash_mismatch", reference["file"])
    try:
        value = json.loads(data)
        canonical = canonical_bytes(value) == data
    except (ValueError, RecursionError):  # bad UTF-8, bad JSON and CanonError are ValueErrors
        canonical = False
    if not canonical:
        raise Unverified(f"{what}_not_canonical", reference["file"])
    return value


def _text(value) -> bool:
    return isinstance(value, str) and value != ""


def _source(value) -> bool:
    """A Source locator with its position: where a read or its terminal evidence stands."""
    return isinstance(value, dict) and all(_text(value.get(f)) for f in ("kind", "name", "position"))


def _reference(value) -> bool:
    return isinstance(value, dict) and set(value) == {"file", "uri", "sha256"} and all(
        isinstance(v, str) for v in value.values())


def _shape(body, what) -> None:
    """The fields of a receipt body or a trusted context, as the decision fixes them."""
    source, issuer, scope, cut = (body.get(f) for f in ("source", "issuer", "scope", "cut"))
    bindings = scope.get("bindings") if isinstance(scope, dict) else None
    frontier = cut.get("frontier") if isinstance(cut, dict) else None
    problems = [
        ("source", _source(source)),
        ("issuer", isinstance(issuer, dict) and set(issuer) == {"id", "authorization"} and _text(issuer["id"])
         and _reference(issuer["authorization"])),
        ("scope", isinstance(scope, dict) and set(scope) == {"definition", "query", "bindings"}
         and _reference(scope["definition"]) and _text(scope["query"]) and isinstance(bindings, list)
         and all(isinstance(b, dict) and set(b) == {"name", "type", "value"} and _text(b["name"]) and _text(b["type"])
                 for b in bindings)
         and len({b["name"] for b in bindings}) == len(bindings)),
        ("cut", isinstance(frontier, dict) and set(frontier) == {"source_id", "position"}
         and all(_text(v) for v in frontier.values())),
        ("inventory", _reference(body.get("inventory"))),
        ("content", _reference(body.get("content"))),
    ]
    bad = [field for field, ok in problems if not ok]
    if bad:
        raise Unverified(f"{what}_malformed", ", ".join(bad))


# The archived-file references inside the bound fields, by field and key: the only places a candidate and its
# trusted context may cite different stored copies of the same bytes. Everything else compares exactly.
PINNED = {"issuer": "authorization", "scope": "definition"}


def _by_hash(field, value):
    """The bound `field` with its one fixed archived-file reference (`PINNED`) reduced to the hash of the bytes
    it pins. The candidate and the trusted context each cite their own stored copy
    (decisions/admission-transport.md, section 3); where a copy is stored does not change what it pins, and only
    the trusted context's copy is read. `_shape` has made sure the reference is one."""
    key = PINNED.get(field)
    if key is None:
        return value
    return value | {key: value[key]["sha256"]}


def _authority(body, authorities) -> dict:
    """The one trusted context that allows this source, scope, cut and issuer."""
    for authority in authorities:
        if not isinstance(authority, dict):
            raise Unverified("authority_malformed", "a trusted context is a dict")
        _shape(authority, "authority")

    def same(authority, *fields):
        return all(canonical_json(_by_hash(f, authority[f])) == canonical_json(_by_hash(f, body[f])) for f in fields)

    scoped = [a for a in authorities if same(a, "source", "scope")]
    if not scoped:
        raise Unverified("receipt_scope_unauthorized", "no trusted context for this source and scope")
    at_cut = [a for a in scoped if same(a, "cut")]
    if not at_cut:
        raise Unverified("receipt_cut_mismatch", "no trusted context at this cut")
    allowed = {canonical_json(a): a for a in at_cut if same(a, "issuer")}
    if not allowed:
        raise Unverified("receipt_issuer_unauthorized", "the issuer is not allowed for this scope")
    if len(allowed) != 1:
        raise Unverified("authority_conflict", "trusted contexts disagree for one scope and cut")
    (authority,) = allowed.values()
    return authority


def _inventory(value, what) -> set:
    """The canonical member keys of an inventory; an identical retry of a key coalesces."""
    if not (isinstance(value, list) and all(isinstance(key, list) and key for key in value)):
        raise Unverified(f"{what}_malformed", "an inventory is a list of member keys")
    return {canonical_json(key) for key in value}


def _members(value, what) -> dict:
    """{canonical member key: canonical text of its rows and terminal evidence}. Identical retries of a member
    or a row coalesce, in any order; conflicting contents for one key reject the read."""
    if not isinstance(value, list):
        raise Unverified(f"{what}_malformed", "contents are a list of members")
    members = {}
    for member in value:
        if not (isinstance(member, dict) and set(member) == {"key", "rows", "terminal"}
                and isinstance(member["key"], list) and member["key"] and isinstance(member["rows"], list)
                and _source(member["terminal"])):
            raise Unverified(f"{what}_malformed", "a member has key, rows and terminal source evidence")
        rows = {}
        for row in member["rows"]:
            if not (isinstance(row, dict) and set(row) == {"key", "values", "source"} and isinstance(row["key"], list)
                    and row["key"] and isinstance(row["values"], dict) and _source(row["source"])):
                raise Unverified(f"{what}_malformed", "a row has key, values and source")
            key = canonical_json(row["key"])
            if rows.setdefault(key, canonical_json(row)) != canonical_json(row):
                raise Unverified(f"{what}_conflict", f"row {key}")
        key = canonical_json(member["key"])
        text = canonical_json({"rows": [rows[k] for k in sorted(rows)], "terminal": member["terminal"]})
        if members.setdefault(key, text) != text:
            raise Unverified(f"{what}_conflict", f"member {key}")
    return members


def _difference(expected: set, got: set) -> str:
    missing, extra = sorted(expected - got), sorted(got - expected)
    return "; ".join(part for part in (missing and "missing " + ", ".join(missing),
                                       extra and "unexpected " + ", ".join(extra)) if part)
