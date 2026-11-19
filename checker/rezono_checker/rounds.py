"""The round verifier of decisions/admission-transport.md, section 7.

A candidate round claim is an archived-file reference (`file`, `uri`, `sha256`) to the canonical bytes of a
claim: `run`, `cut`, the chosen `batch` with its `members`, and `subsets`, each a visible boundary with its
`members`, the ordered plan hashes it applies (`effects`), and the archived `variant` and `certificate`.
The claim selects bytes to check and confers no authority over them.

Authority comes only from a retained round context for the claim's run and cut. It pins the `manifest`, the
`cut`, the `definition_sha256`, the compiled `program`, the `invariants`, the `observations`, the certified
`base` and the candidate `domain`: the batch `width` and every step with its integer `priority` and the plan
hashes of its `effects` in their fixed order. The certificate context is built from that context alone.

A round is verified when:

- every visible boundary of the claimed batch has a certificate from the retained base that
  `check_transition_certificate` finds valid. A boundary applies a nonempty prefix of the effects of each
  step in a nonempty subset of the batch, in the domain's step order, so a step with several effects has a
  boundary after each prefix. A certificate binds `effect` to the canonical SHA-256 of the ordered plan
  hashes the boundary applies, never to a step name;
- the deterministic selection of decisions/safe-step-rounds.md replays to the claimed batch: no larger
  candidate batch within the width, and no batch of the same size with a lexicographically lesser ascending
  tuple of priorities, remains unrefuted. An alternative is refuted only by a certificate for one of its
  visible boundaries, bound to the same base and effects, in whose variant the checker itself finds an
  invariant violated. Missing refutation leaves the round unverified.

Archived JSON spells integers as decimal text (rezono_canon), so widths, priorities, delta weights and the
premise strata of snapshot witnesses are decoded before use. Their canonical hashes do not change. The identities of the receipts admitted in the same step are accepted for the scoped
negations a certificate may cite; the current certificate check establishes absence over closed modeled
relations only and refuses open reads itself (`missing_scope_coverage`).
"""

import json
import re
from itertools import combinations, product

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex

from .transition import check_transition_certificate

DECIMAL = re.compile(r"-?(0|[1-9][0-9]*)")


class Unverified(Exception):
    """A round claim that is not verified: `code` names the failed check, `detail` says where."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def verify_round(reference, contexts, receipts, read_bytes) -> tuple:
    """Verify one candidate round claim against the retained round `contexts`.

    Returns (round, run, cut, batch, members): the claim digest, its run, cut and batch, and the member steps
    in claim order. Raises Unverified when the round is not verified. `receipts` holds the identities of the
    receipts admitted in the same step. `read_bytes(uri)` returns the stored bytes (None or KeyError when
    absent), as for snapshots.
    """
    del receipts  # No certificate check reads scope receipts yet; see the module docstring.
    claim = _json(reference, read_bytes, "claim")
    _claim_shape(claim)
    context = _context(claim, contexts)
    certificate_context, base, domain = _retained(context, read_bytes)
    width, steps = _domain(domain)

    members = tuple(claim["members"])
    if len(set(members)) != len(members) or not set(members) <= steps.keys() or not 1 <= len(members) <= width:
        raise Unverified("round_batch_invalid", claim["batch"])

    shown = {}
    for position, subset in enumerate(claim["subsets"]):
        key = (frozenset(subset["members"]), tuple(subset["effects"]))
        if key in shown:
            raise Unverified("round_subset_duplicate", f"subset {position}")
        shown[key] = subset

    def certify(boundary):
        """The findings of the certificate the claim shows for `boundary`, or None when it shows none."""
        stepset, effects = boundary
        subset = shown.get((stepset, effects))
        if subset is None:
            return None
        certificate = _certificate(_json(subset["certificate"], read_bytes, "certificate"))
        if certificate.get("effect") != canonical_sha256(list(effects)):
            raise Unverified("certificate_effect_mismatch", ", ".join(sorted(stepset)))
        variant = _snapshot(_json(subset["variant"], read_bytes, "variant"))
        return check_transition_certificate(certificate, certificate_context, base, variant)["findings"]

    for boundary in _boundaries(members, steps):
        findings = certify(boundary)
        if findings is None:
            raise Unverified("round_boundary_missing", ", ".join(boundary[1]))
        if findings:
            raise Unverified("certificate_invalid", "; ".join(sorted({f["reason"] for f in findings})))

    chosen = _rank(members, steps)
    for size in range(width, 0, -1):
        for alternative in combinations(sorted(steps), size):
            if _rank(alternative, steps) >= chosen:
                continue
            refuted = False
            for boundary in _boundaries(alternative, steps):
                findings = certify(boundary)
                if findings and any(f.get("snapshot") == "variant" and f["reason"] == "invariant_violated"
                                    for f in findings):
                    refuted = True
                    break
            if not refuted:
                raise Unverified("round_preceded", ", ".join(sorted(alternative, key=lambda s: steps[s][0])))
    return reference["sha256"], claim["run"], claim["cut"], claim["batch"], members


def _rank(batch, steps) -> tuple:
    """Selection order: the larger batch first, then the least ascending tuple of priorities."""
    return -len(batch), tuple(sorted(steps[step][0] for step in batch))


def _boundaries(batch, steps):
    """Every visible boundary of `batch`: a nonempty prefix of each step's effects for a nonempty subset."""
    ordered = sorted(batch, key=lambda step: steps[step][0])
    for size in range(1, len(ordered) + 1):
        for subset in combinations(ordered, size):
            for lengths in product(*(range(1, len(steps[step][1]) + 1) for step in subset)):
                effects = tuple(plan for step, n in zip(subset, lengths, strict=True) for plan in steps[step][1][:n])
                yield frozenset(subset), effects


def _context(claim, contexts) -> dict:
    found = [context for context in contexts if isinstance(context, dict) and context.get("run") == claim["run"]
             and isinstance(context.get("cut"), dict) and context["cut"].get("id") == claim["cut"]]
    if not found:
        raise Unverified("round_context_missing", f"{claim['run']} at {claim['cut']}")
    if len(found) > 1:
        raise Unverified("round_context_ambiguous", f"{claim['run']} at {claim['cut']}")
    return found[0]


def _retained(context, read_bytes) -> tuple[dict, dict, dict]:
    """The certificate context, the certified base and the domain, from the retained context alone."""
    try:
        fields = ("manifest", "definition_sha256", "invariants", "observations", "program", "base", "domain")
        manifest, definition, invariants, observations, *_ = (context[field] for field in fields)
        if context["cut"].get("run") != context["run"] or not isinstance(observations, dict):
            raise Unverified("round_context_malformed", "the cut belongs to the context's run")
        certificate_context = {
            "manifest": manifest, "cut": context["cut"], "definition_sha256": definition, "invariants": invariants,
            "program": _json(context["program"], read_bytes, "program"),
            "observations": {name: _bytes(pin, read_bytes, "observation") for name, pin in observations.items()},
        }
    except (KeyError, TypeError, AttributeError):
        raise Unverified("round_context_malformed", "a round context pins its fields") from None
    base = _snapshot(_json(context["base"], read_bytes, "base"))
    return certificate_context, base, _json(context["domain"], read_bytes, "domain")


def _domain(domain) -> tuple[int, dict]:
    """The batch width and {step: (priority, effects)} of a retained domain."""
    try:
        width = _integer(domain["width"])
        steps = {}
        for entry in domain["steps"]:
            step, effects = entry["step"], entry["effects"]
            if (not _text(step) or step in steps or not isinstance(effects, list) or not effects
                    or not all(map(_text, effects)) or len(set(effects)) != len(effects)):
                raise ValueError(step)
            steps[step] = (_integer(entry["priority"]), tuple(effects))
    except (KeyError, TypeError, ValueError):
        raise Unverified("round_domain_malformed", "a domain has a width and steps with priorities and effects") \
            from None
    if width < 1 or len({priority for priority, _ in steps.values()}) != len(steps):
        raise Unverified("round_domain_malformed", "a positive width and distinct priorities")
    return width, steps


def _claim_shape(claim) -> None:
    def subset(value) -> bool:
        return (isinstance(value, dict) and set(value) == {"members", "effects", "variant", "certificate"}
                and _texts(value["members"]) and _texts(value["effects"])
                and _reference(value["variant"]) and _reference(value["certificate"]))

    if not (isinstance(claim, dict) and set(claim) == {"run", "cut", "batch", "members", "subsets"}
            and all(_text(claim[field]) for field in ("run", "cut", "batch")) and _texts(claim["members"])
            and isinstance(claim["subsets"], list) and all(map(subset, claim["subsets"]))):
        raise Unverified("claim_malformed", "a claim has run, cut, batch, members and subsets")


def _certificate(certificate):
    """The certificate with its archived delta weights decoded from text."""
    if not isinstance(certificate, dict) or not isinstance(certificate.get("delta"), list):
        return certificate
    delta = [[*change[:2], _integer(change[2])] if isinstance(change, list) and len(change) == 3
             and isinstance(change[2], str) and DECIMAL.fullmatch(change[2]) else change
             for change in certificate["delta"]]
    return certificate | {"delta": delta}


def _snapshot(state):
    """The snapshot with the premise strata of its archived witnesses decoded from text."""
    def premise(value):
        if isinstance(value, dict) and isinstance(value.get("stratum"), str) and DECIMAL.fullmatch(value["stratum"]):
            return value | {"stratum": int(value["stratum"])}
        return value

    def witness(value):
        if isinstance(value, dict) and isinstance(value.get("premises"), list):
            return value | {"premises": [premise(item) for item in value["premises"]]}
        return value

    if not isinstance(state, dict) or not isinstance(state.get("witnesses"), list):
        return state
    return state | {"witnesses": [witness(item) for item in state["witnesses"]]}


def _integer(value) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and DECIMAL.fullmatch(value):
        return int(value)
    raise ValueError(value)


def _bytes(reference, read_bytes, what) -> bytes:
    """The stored bytes an archived-file reference pins."""
    if not _reference(reference):
        raise Unverified(f"{what}_reference_malformed", "an archived file has file, uri and sha256")
    try:
        data = read_bytes(reference["uri"])
    except (LookupError, OSError, ValueError):
        data = None
    if not isinstance(data, bytes):
        raise Unverified(f"{what}_unreadable", reference["file"])
    if sha256_hex(data) != reference["sha256"]:
        raise Unverified(f"{what}_hash_mismatch", reference["file"])
    return data


def _json(reference, read_bytes, what):
    """The canonical JSON value an archived-file reference pins."""
    data = _bytes(reference, read_bytes, what)
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


def _texts(value) -> bool:
    return isinstance(value, list) and bool(value) and all(map(_text, value))


def _reference(value) -> bool:
    return isinstance(value, dict) and set(value) == {"file", "uri", "sha256"} and all(
        isinstance(v, str) for v in value.values())
