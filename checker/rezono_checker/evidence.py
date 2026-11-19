"""The one admission step at the batch boundary: decisions/admission-transport.md.

A protected caller passes an `Evidence`: an archived-file reference to the trusted context
(`observations/retained/context.json`), an archived-file reference to the submitted index
(`observations/submitted/index.json`, or None when nothing was submitted) and the storage resolver.

Authority comes only from the pinned context. Admission reads the context by its pinned hash, then reads only
what the context and the index reference; it never lists or searches the archive. A context or an index that is
unreadable, mispinned, not canonical or malformed is refused with a ValueError: the caller's own input is
broken. A candidate that fails verification gives no row and a warning finding, and stays listed.

Receipts are admitted first; the round verifier receives the identities of the admitted receipts and nothing
else. `admit` gives the rows of the protected relations `verified_receipt`, `verified_member`, `verified_round`
and `verified_round_member`, the findings and the candidate references the complete manifest lists. `check`
admits again on the complete side of a publication and holds the protected snapshots against those rows.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

from rezono_canon import canonical_json

from . import completeness
from .canon import encode_key

RECEIPT = completeness.RELATION
MEMBER = "verified_member"
ROUND = "verified_round"
ROUND_MEMBER = "verified_round_member"
CONTEXT_FIELDS = ("completeness", "rounds")
INDEX_FIELDS = ("completeness_receipts", "rounds")
PROTECTED = (RECEIPT, MEMBER, ROUND, ROUND_MEMBER)
NOT_ADMITTED = {RECEIPT: "receipt_not_admitted", MEMBER: "receipt_not_admitted",
                ROUND: "round_not_admitted", ROUND_MEMBER: "round_not_admitted"}


@dataclass(frozen=True)
class Evidence:
    context: dict  # archived-file reference {file, uri, sha256} to the trusted context
    candidates: dict | None  # archived-file reference to the submitted index; None: nothing submitted
    read_bytes: Callable  # uri -> bytes, the storage resolver of the snapshots


@dataclass(frozen=True)
class Admitted:
    rows: dict  # {protected relation: [row]}, each in a fixed order
    findings: list  # warnings for candidates that are not admitted
    references: dict  # {"completeness_receipts": [reference], "rounds": [reference]} as submitted


def admit(evidence: Evidence) -> Admitted:
    """Admit the submitted candidates against the pinned trusted context."""
    context = _pinned(evidence.context, evidence.read_bytes, "context", CONTEXT_FIELDS)
    if evidence.candidates is None:
        return Admitted(rows={RECEIPT: [], MEMBER: [], ROUND: [], ROUND_MEMBER: []}, findings=[],
                        references={field: [] for field in INDEX_FIELDS})
    index = _pinned(evidence.candidates, evidence.read_bytes, "index", INDEX_FIELDS)

    authorities = context["completeness"]
    admitted, rejected = completeness.admit(index["completeness_receipts"], authorities, evidence.read_bytes)
    findings = [{"reason": "receipt_unverified", "detail": f"{'' if i is None else f'receipt {i}: '}{e}"}
                for i, e in rejected]
    receipts = [admitted[key] for key in sorted(admitted)]
    members = sorted({row for parts in receipts
                      for row in _members(parts, authorities, evidence.read_bytes)})
    rounds, round_members = [], set()
    if index["rounds"]:
        # The round verifier is needed only when rounds are submitted.
        from .rounds import Unverified as RoundUnverified
        from .rounds import verify_round
        identities = {parts[0] for parts in receipts}
        verified = {}
        for i, reference in enumerate(index["rounds"]):
            try:
                identity, run, cut, batch, steps = verify_round(reference, context["rounds"], identities,
                                                                evidence.read_bytes)
            except RoundUnverified as e:
                findings.append({"reason": "round_unverified", "detail": f"round {i}: {e}"})
            else:
                verified[identity] = (identity, run, cut, batch)
                round_members.update((identity, step) for step in steps)
        rounds = [verified[key] for key in sorted(verified)]
    return Admitted(rows={RECEIPT: receipts, MEMBER: members, ROUND: rounds, ROUND_MEMBER: sorted(round_members)},
                    findings=findings, references={field: list(index[field]) for field in INDEX_FIELDS})


def check(evidence: Evidence | None, snapshots: dict, relations=PROTECTED) -> list:
    """Checker findings for the protected snapshots of one complete epoch (decisions/admission-transport.md,
    section 5). Admission runs again; without evidence nothing is admitted. A snapshot row of a protected
    relation that admission did not produce is `receipt_not_admitted` or `round_not_admitted`, an error; an
    admitted row that a protected snapshot lacks is `admitted_row_missing`, an error too: the snapshot must be
    exactly what admission gives. A relation without a snapshot is one the pack does not declare: nothing
    enters it. A candidate that is not admitted stays a warning. `snapshots` are {relation: {key: row}}."""
    if evidence is None:
        rows, findings = {}, []
    else:
        try:
            admitted = admit(evidence)
        except ValueError as e:
            return [{"reason": "evidence_refused", "detail": str(e)}]
        rows, findings = admitted.rows, list(admitted.findings)
    for relation in relations:
        if relation not in snapshots:
            continue
        expected = {encode_key([v if isinstance(v, str) else str(v) for v in row])  # a part as decimal text
                    for row in rows.get(relation, ())}
        present = set(snapshots[relation] or ())
        findings += [{"reason": NOT_ADMITTED[relation], "relation": relation, "key": key}
                     for key in sorted(present - expected)]
        findings += [{"reason": "admitted_row_missing", "relation": relation, "key": key}
                     for key in sorted(expected - present)]
    return findings


def _pinned(reference, read_bytes, what, fields) -> dict:
    """The canonical object a context or an index reference pins, with exactly its list fields."""
    try:
        value = completeness._read(reference, read_bytes, what)
    except completeness.Unverified as e:
        raise ValueError(f"{what}: {e}") from e
    if not (isinstance(value, dict) and set(value) == set(fields)
            and all(isinstance(value[field], list) for field in fields)):
        raise ValueError(f"{what}: {what}_malformed: the {what} has exactly the lists " + ", ".join(fields))
    return value


def _members(parts, authorities, read_bytes):
    """The `verified_member` rows of one admitted receipt: one row per part of each trusted member key."""
    inventory = next(a["inventory"] for a in authorities if a["inventory"]["sha256"] == parts[4])
    keys = completeness._inventory(completeness._read(inventory, read_bytes, "authority_inventory"),
                                   "authority_inventory")
    for member in sorted(keys):
        for part, value in enumerate(json.loads(member)):
            yield parts[0], member, part, value if isinstance(value, str) else canonical_json(value)
