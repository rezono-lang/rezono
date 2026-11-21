"""Replay a billing close against the exact price publication and intake receipt it names.

A close publishes its lines and rational total only on a completeness receipt that the shared admission of
`rezono_checker.completeness` verifies against the trusted intake context, at this close's cutoff, and whose
certified rows equal the replayed timely observations. Otherwise coverage is unknown: the close stays pending
with no lines and no total. A certified empty intake closes at zero.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import json
import re
from typing import Literal, NotRequired, Protocol, TypedDict

from rezono_canon import canonical_sha256
from rezono_checker.completeness import admit, scope_digest

from run.effective_quote import pack_currencies


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SUBMICROSECOND = re.compile(r"[.,][0-9]{6}([0-9]+)$")
_OFFSET_FRACTION = re.compile(r"[.,]([0-9]+)$")


class PublicationReader(Protocol):
    def get(self, key: str) -> bytes | None: ...


class PublicationWriter(Protocol):
    def put_new(self, key: str, data: bytes) -> None: ...


class CloseDecision(TypedDict):
    id: str
    month: str
    closed_at: str
    publication_sha256: str
    # Candidate completeness receipts for the billing intake at `closed_at`, as archived-file references.
    # They select bytes to check and confer no authority: the trusted context comes from the caller.
    completeness_receipts: NotRequired[list[dict[str, str]]]


class Receipt(TypedDict):
    id: str
    plan_hash: str
    item: str
    received_at: str


class PeriodReceipt(Receipt):
    kind: Literal["period"]
    start: str
    stop: str


class SetupReceipt(Receipt):
    kind: Literal["once"]
    event_at: str


Observation = PeriodReceipt | SetupReceipt


class Coverage(TypedDict, total=False):
    # Verified: the `verified_receipt` row (receipt id, source name, scope and cut hashes, inventory and
    # content hashes) and the aggregate witness of the total (contributing rows and the hash over them).
    verified_receipt: list[str]
    count: int
    contributors_sha256: str
    # Unknown: why the close stays pending.
    unknown: list[str]


class CloseReport(TypedDict):
    publication_sha256: str
    total_eur: list[int] | None
    lines: dict[str, list[int]] | None
    late: list[tuple[str, str, Literal["arrived_after_cutoff"]]]
    coverage: Coverage


def retain(store: PublicationWriter, body: bytes) -> str:
    """Write the edition under its immutable digest and return the digest."""
    digest = sha256(body).hexdigest()
    store.put_new(digest, body)
    return digest


def _rates(store: PublicationReader, digest: str) -> dict[str, Fraction]:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid price publication digest")
    body = store.get(digest)
    if body is None or sha256(body).hexdigest() != digest:
        raise ValueError("price publication unavailable or digest mismatch")

    _, publication_currency, _ = pack_currencies()
    publication = json.loads(body)
    if not isinstance(publication, dict) or publication.get("currency") != publication_currency:
        raise ValueError(f"the price publication must be in {publication_currency}")
    raw_rates = publication.get("rates")
    if not isinstance(raw_rates, dict):
        raise ValueError("the price publication must have line rates")

    rates = {}
    for item, pair in raw_rates.items():
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(value) is not int for value in pair) or pair[1] == 0):
            raise ValueError(f"invalid rational price for {item}")
        rates[item] = Fraction(*pair)
    return rates


def _seconds(delta: timedelta) -> Fraction:
    return delta.days * 86400 + delta.seconds + Fraction(delta.microseconds, 1_000_000)


def _utc(value: str) -> Fraction:
    """Return exact seconds from the UTC epoch without truncating the input fraction."""
    instant = datetime.fromisoformat(value)
    offset = instant.utcoffset()
    if offset is None:
        raise ValueError("billing instants require a UTC offset")

    if value.endswith("Z"):
        local, zone = value[:-1], ""
    else:
        boundary = max(value.rfind("+"), value.rfind("-"))
        local, zone = value[:boundary], value[boundary:]

    seconds = _seconds(instant.replace(tzinfo=timezone.utc) - _EPOCH)
    if remainder := _SUBMICROSECOND.search(local):
        seconds += Fraction(Decimal("0.000000" + remainder[1]))

    offset_seconds = _seconds(offset)
    if fraction := _OFFSET_FRACTION.search(zone):
        # datetime can discard the full fraction of a subsecond-only offset.
        whole = abs(offset) // timedelta(seconds=1)
        magnitude = whole + Fraction(Decimal("0." + fraction[1]))
        offset_seconds = -magnitude if zone.startswith("-") else magnitude
    return seconds - offset_seconds


def _month_window(month: str) -> tuple[Fraction, Fraction]:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
        raise ValueError("the close month must have the format YYYY-MM")
    year, number = map(int, month.split("-"))
    start = datetime(year, number, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if number == 12 else start.replace(month=number + 1)
    return _seconds(start - _EPOCH), _seconds(end - _EPOCH)


def _allocation(observation: Observation, month_start: Fraction, month_end: Fraction) -> Fraction:
    if observation["kind"] == "once":
        return Fraction(month_start <= _utc(observation["event_at"]) < month_end)
    if observation["kind"] != "period":
        raise ValueError("unknown billing observation kind")

    begin, end = _utc(observation["start"]), _utc(observation["stop"])
    if end <= begin:
        raise ValueError("a billing period must end after it starts")
    overlap = min(end, month_end) - max(begin, month_start)
    return max(Fraction(), overlap) / (end - begin)


def _ratio(amount: Fraction) -> list[int]:
    return [amount.numerator, amount.denominator]


def _reader(store: PublicationReader):
    """Resolve an archived-file URI through the same store that holds the publication."""
    uri = getattr(store, "uri", None)
    prefix = uri("") if callable(uri) else None

    def read(location: str) -> bytes | None:
        if prefix is None or not isinstance(location, str) or not location.startswith(prefix):
            return None
        return store.get(location[len(prefix):])

    return read


def _binds_close(scope: dict, cutoff: Fraction) -> bool:
    """The trusted intake scope is bound to exactly this close's cutoff."""
    bound = [binding for binding in scope["bindings"] if binding["name"] == "closed_at"]
    if len(bound) != 1 or bound[0]["type"] != "datetime" or not isinstance(bound[0]["value"], str):
        return False
    try:
        return _utc(bound[0]["value"]) == cutoff
    except ValueError:
        return False


def _certified_rows(read, authority: dict) -> dict[str, dict]:
    """The intake rows of the trusted contents that the admitted receipt equals, as observations by id."""
    body = read(authority["content"]["uri"])
    if body is None or sha256(body).hexdigest() != authority["content"]["sha256"]:
        raise LookupError("certified_content_unreadable")
    rows: dict[str, dict] = {}
    for member in json.loads(body):
        for row in member["rows"]:
            key = row["key"]
            if not (len(key) == 1 and isinstance(key[0], str)) or "id" in row["values"]:
                raise LookupError("certified_row_malformed")
            observation = {"id": key[0], **row["values"]}
            if rows.setdefault(key[0], observation) != observation:
                raise LookupError(f"certified_row_conflict: {key[0]}")
    return rows


def _coverage(store: PublicationReader, decision: CloseDecision, authorities, cutoff: Fraction,
              timely: dict[str, Observation]) -> dict:
    """The verified receipt row that covers exactly the timely intake of this close, or why coverage is unknown."""
    references = decision.get("completeness_receipts")
    if not references:
        return {"unknown": ["receipt_missing"]}
    read = _reader(store)
    trusted = [authority for authority in authorities or () if isinstance(authority, dict)]
    admitted, rejected = admit(references, trusted, read)
    reasons = [str(error) for _, error in rejected]
    at_close = []
    for parts in admitted.values():
        receipt, source, scope, cut, inventory, content = parts
        # The admitted row names its trusted context; the receipt counts only for this close's cutoff.
        matches = [a for a in trusted if a["source"]["name"] == source and scope_digest(a["scope"]) == scope
                   and canonical_sha256(a["cut"]) == cut and a["inventory"]["sha256"] == inventory
                   and a["content"]["sha256"] == content]
        if matches and _binds_close(matches[0]["scope"], cutoff):
            at_close.append((parts, matches[0]))
        else:
            reasons.append(f"receipt_not_at_close: {receipt}")
    if len(at_close) != 1:
        return {"unknown": ["receipt_ambiguous"] if at_close else reasons}
    (parts, authority), = at_close

    try:
        certified = _certified_rows(read, authority)
    except LookupError as error:
        return {"unknown": [error.args[0]]}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"unknown": ["certified_content_malformed"]}
    # Replay the exact receipt identities, plan hashes and contents: the timely set is the certified set.
    differences = [f"missing {identity}" for identity in sorted(certified.keys() - timely.keys())]
    differences += [f"unexpected {identity}" for identity in sorted(timely.keys() - certified.keys())]
    differences += [f"changed {identity}" for identity in sorted(certified.keys() & timely.keys())
                    if certified[identity] != timely[identity]]
    if differences:
        return {"unknown": ["receipt_replay_mismatch: " + ", ".join(differences)]}
    return {"verified_receipt": list(parts)}


def report(store: PublicationReader, decision: CloseDecision, observations: Iterable[Observation],
           authorities: Iterable[dict] = ()) -> CloseReport:
    """Allocate recorded charges by UTC service time, using only pre-close receipts.

    `authorities` is the trusted intake context of the protected caller, never taken from the candidates.
    Lines and a total are published only on verified coverage of the whole timely intake.
    """
    digest = decision["publication_sha256"]
    rates = _rates(store, digest)
    month_start, month_end = _month_window(decision["month"])
    cutoff = _utc(decision["closed_at"])

    by_id: dict[str, Observation] = {}
    for observation in observations:
        identity = observation["id"]
        plan_hash = observation.get("plan_hash")
        if not isinstance(plan_hash, str) or re.fullmatch(r"[0-9a-f]{64}", plan_hash) is None:
            raise ValueError(f"missing or invalid plan hash for billing observation {identity}")
        existing = by_id.setdefault(identity, observation)
        if existing != observation:
            raise ValueError(f"conflicting billing observations for {identity}")

    timely: dict[str, Observation] = {}
    parts: dict[str, Fraction] = {}
    late: list[tuple[str, str, Literal["arrived_after_cutoff"]]] = []
    for identity, observation in sorted(by_id.items()):
        part = _allocation(observation, month_start, month_end)
        if _utc(observation["received_at"]) >= cutoff:
            if part:
                late.append((identity, decision["id"], "arrived_after_cutoff"))
            continue
        timely[identity] = observation
        if part:
            parts[identity] = part

    coverage = _coverage(store, decision, authorities, cutoff, timely)
    if "unknown" in coverage:
        return {"publication_sha256": digest, "total_eur": None, "lines": None, "late": late, "coverage": coverage}

    total = Fraction()
    lines = {}
    for identity, part in parts.items():
        item = timely[identity]["item"]
        if item not in rates:
            raise ValueError(f"price publication has no rate for {item}")
        amount = rates[item] * part
        lines[identity] = _ratio(amount)
        total += amount
    # The aggregate witness: the contributing certified rows, sorted by id, and the hash over them.
    coverage["count"] = len(parts)
    coverage["contributors_sha256"] = canonical_sha256([timely[identity] for identity in parts])
    return {"publication_sha256": digest, "total_eur": _ratio(total), "lines": lines, "late": late,
            "coverage": coverage}
