"""Verify a known integer selection from a server-side retained publication."""

from dataclasses import dataclass
import json
import re
from typing import Protocol

from rezono_canon import sha256_hex
from rezono_checker.canon import INTEGER
from rezono_checker.check import check_epoch
from rezono_checker.evidence import Evidence
from rezono_checker.rules import check_calc_bindings, derived_relations, load_rules, load_seals
from rezono_checker.snapshots import read_rows

from . import pointers


SEGMENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
# Where the protected caller keeps what admission read (decisions/admission-transport.md, section 3): the trusted
# context and what it pins, and the submitted index with its candidates. A replay reads evidence nowhere else.
RETAINED = "observations/retained/"
SUBMITTED = "observations/submitted/"


class StoreReader(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def uri(self, key: str) -> str: ...


@dataclass(frozen=True)
class PinnedSelection:
    """The locator and exact row from a trusted plan, after checking its binding."""

    pack: str
    epoch: int
    manifest_sha256: str
    relation: str
    key: str


@dataclass(frozen=True)
class NativeCostDefinition:
    """Reviewed IR and two binary relations that establish the selection's unit."""

    pack: str
    relation: str
    rules_sha256: str
    calc_sha256: str
    provider_relation: str
    currency_relation: str


def resolve(st: StoreReader, pin: PinnedSelection, *, context_sha256: str | None = None) -> int:
    """Replay one immutable main epoch and return its exact known integer.

    The caller must obtain the pin from a trusted plan. This reads the complete
    checker publication, so the result needs a separate access check before it
    can be returned to any role.

    `context_sha256` is the hash of the trusted context the epoch was admitted with, which the protected
    caller pins beside the selection (decisions/admission-transport.md, section 4). The manifest only names
    that context and confers no authority: a manifest that names a context needs this hash, and the two
    must agree.
    """
    return _resolve(st, pin, context_sha256=context_sha256)


def resolve_native_cost(st: StoreReader, pin: PinnedSelection, *, definition: NativeCostDefinition,
                        provider: str, currency: str, context_sha256: str | None = None) -> int:
    """Resolve a cost from a trusted plan and an independently reviewed definition.

    The caller supplies the definition separately from the plan and archive.
    The result has the same server-only access boundary as resolve, and takes the context hash as it does.
    """
    if (pin.pack, pin.relation) != (definition.pack, definition.relation):
        raise ValueError("selection does not match the native cost definition")
    return _resolve(st, pin, native_cost=(definition, provider, currency), context_sha256=context_sha256)


def _resolve(st: StoreReader, pin: PinnedSelection, *, context_sha256: str | None = None,
             native_cost: tuple[NativeCostDefinition, str, str] | None = None) -> int:
    if (not SEGMENT.fullmatch(pin.pack) or type(pin.epoch) is not int
            or not SHA256.fullmatch(pin.manifest_sha256)):
        raise ValueError("invalid retained publication pin")

    def read(key: str) -> bytes:
        body = st.get(key)
        if body is None:
            raise ValueError(f"retained object missing: {key}")
        return body

    prefix = st.uri(f"{pin.pack}/")

    def read_uri(uri: str) -> bytes:
        if not uri.startswith(prefix):
            raise ValueError("retained URI leaves the pinned store and pack")
        suffix = uri[len(prefix):]
        if not all(SEGMENT.fullmatch(part) for part in suffix.split("/")):
            raise ValueError("invalid retained object key")
        return read(f"{pin.pack}/{suffix}")

    root = st.uri("")

    def evidence_key(uri: str, places=(RETAINED, SUBMITTED)) -> str:
        """The key of an object admission read: in the pinned store, under the retained or submitted
        observations only."""
        key = uri[len(root):] if uri.startswith(root) else ""
        if not key.startswith(places):
            raise ValueError("retained evidence leaves the retained observations")
        if not all(SEGMENT.fullmatch(part) for part in key.split("/")):
            raise ValueError("invalid retained object key")
        return key

    def read_evidence(uri: str) -> bytes:
        return read(evidence_key(uri))

    def verified_bytes(entry: dict) -> bytes:
        body = read_uri(entry["uri"])
        if sha256_hex(body) != entry["sha256"]:
            raise ValueError("retained evidence digest mismatch")
        return body

    head_key = pointers.head_key(pin.pack, pin.epoch)
    mid = f"m-{pin.epoch}"
    body = read(f"{pin.pack}/manifests/{mid}.json")
    if sha256_hex(body) != pin.manifest_sha256:
        raise ValueError("retained manifest digest mismatch")
    manifest = json.loads(body)
    if (manifest["id"] != mid or type(manifest["epoch"]) is not int
            or pointers.head(pin.pack, body) != (head_key, read(head_key))):
        raise ValueError("retained head does not match the pinned main manifest")
    if any(c["status"] not in ("green", "warning") for c in manifest["checks"]):
        raise ValueError("retained manifest is not green")

    compiled = manifest["compiled"]
    [rule_entry] = [entry for entry in compiled if entry["file"] == "ir/rules.json"]
    [calc_entry] = [entry for entry in compiled if entry["file"] == "ir/calc.json"]
    if native_cost is not None:
        definition, provider, currency = native_cost
        if (rule_entry["sha256"], calc_entry["sha256"]) != (definition.rules_sha256, definition.calc_sha256):
            raise ValueError("unreviewed native cost definition")
    rule_doc, calc_doc = json.loads(verified_bytes(rule_entry)), json.loads(verified_bytes(calc_entry))
    if (rule_doc.get("format") != "rezono.rules/1" or calc_doc.get("format") != "rezono.calc-ir/1"
            or rule_doc.get("pack") != pin.pack or calc_doc.get("pack") != pin.pack):
        raise ValueError("retained IR does not match the pinned pack")
    if not any(r["view"] == pin.relation for r in calc_doc["rules"]):
        raise ValueError("retained row is not a calculation selection")

    snapshots = [s for s in manifest["snapshots"] if s["role"] == "checker" and s["complete"] is True]
    if not snapshots or len(snapshots) != len({s["relation"] for s in snapshots}):
        raise ValueError("missing or duplicate complete checker snapshots")
    [entry] = [w for w in manifest["witnesses"] if w["role"] == "checker"]
    proof = json.loads(verified_bytes(entry))
    rules = load_rules(rule_doc)
    check_calc_bindings(rule_doc, rules, calc_doc)
    # The manifest names the trusted context and the index its epoch was admitted with; the authority is the
    # caller's own pin of the context hash. They must agree, and the context must be a retained observation:
    # the checker then admits again from exactly those bytes. Without them nothing is admitted, and a protected
    # row fails.
    named = manifest.get("evidence")
    if named is not None and not (isinstance(named, dict) and isinstance(named.get("context"), dict)
                                  and set(named) <= {"context", "index"}):
        raise ValueError("malformed retained evidence")
    if context_sha256 is not None and not (isinstance(context_sha256, str) and SHA256.fullmatch(context_sha256)):
        raise ValueError("invalid evidence context pin")
    if named is None:
        if context_sha256 is not None:
            raise ValueError("the retained manifest names no evidence context")
        evidence = None
    else:
        if context_sha256 is None:
            raise ValueError("the retained manifest names an evidence context the caller did not pin")
        if named["context"].get("sha256") != context_sha256:
            raise ValueError("the retained evidence context does not match the caller's pin")
        evidence_key(str(named["context"].get("uri")), (RETAINED,))
        evidence = Evidence(named["context"], named.get("index"), read_evidence)
    report = check_epoch(
        proof["witnesses"], {**manifest, "snapshots": snapshots}, rules, read_uri,
        derived=derived_relations(rule_doc, rules), seals=load_seals(rule_doc),
        calc_ir=calc_doc, calc_witnesses=proof["calc_witnesses"], evidence=evidence,
    )
    if not report["valid"]:
        reasons = sorted({f["reason"] for f in report["findings"] if f["severity"] == "error"})
        raise ValueError(f"retained proof failed: {', '.join(reasons)}")
    target = {"relation": pin.relation, "key": pin.key}
    [chosen] = [w for w in proof["calc_witnesses"] if w["conclusion"] == target]
    value = chosen["value"]
    if chosen["state"] != "known" or chosen["reason"] or not INTEGER.fullmatch(value) or value == "-0":
        raise ValueError("retained selection is not a known integer")
    if native_cost is not None:
        subject_key = json.loads(pin.key)[0]
        for relation, subject, expected in ((definition.provider_relation, subject_key, provider),
                                             (definition.currency_relation, provider, currency)):
            entries = [s for s in snapshots if s["relation"] == relation]
            if len(entries) != 1:
                raise ValueError(f"missing complete historical {relation} snapshot")
            snapshot = entries[0]
            rows = read_rows(verified_bytes(snapshot), snapshot["format"])
            matches = [key for key, _ in rows.values() if key[:1] == (subject,)]
            if matches != [(subject, expected)]:
                raise ValueError(f"historical {relation} does not match the bound plan")
    return int(value)
