"""Admit recorded observations and evaluate the pinned loop theory at each sweep boundary."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from itertools import chain
from math import lcm
from pathlib import Path
from typing import TYPE_CHECKING

from loop.replay import Snapshot

if TYPE_CHECKING:
    from rezono_compiler.pack import Pack
    from rezono_compiler.rules import Program


RELATIONS = ("declared", "needed", "known", "waiting", "unblocked", "done", "stuck", "drift")
INSTANT = re.compile(r"(\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d)(?:\.(\d+))?([Zz]|[+-]\d\d:\d\d)")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
ARCHIVE_ROOT = "s3://rezono/"
RETAINED_PREFIX = "observations/retained/"
SUBMITTED_PREFIX = "observations/submitted/"
KEY_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")
PLAN_HASH = re.compile(r"[0-9a-f]{64}")
ATTEMPT_STATES = frozenset({"planned", "applying", "unknown", "applied", "failed", "cleaned"})
TICK_COLUMNS = {
    "loop_observation": ("event_time",),
    "loop_sweep": ("event_time",),
    "loop_sweep_receipt": ("event_time",),
    "loop_deadline": ("budget",),
    "flow_sweep_window": ("start", "stop"),
    "flow_node_report": ("first", "last"),
}


def instant(text: str) -> Fraction:
    """Read the full decimal fraction, including precision finer than datetime's microseconds."""
    match = INSTANT.fullmatch(text)
    if not match:
        raise ValueError("an observation needs an event time with a UTC offset")
    whole, digits, zone = match.groups()
    delta = datetime.fromisoformat(whole + zone.upper()) - EPOCH
    return delta.days * 86400 + delta.seconds + Fraction(int(digits or "0"), 10 ** len(digits or ""))


@dataclass(frozen=True)
class RunClock:
    origin: Fraction
    ticks_per_second: int

    def ticks(self, at: Fraction) -> Fraction:
        return (at - self.origin) * self.ticks_per_second


def read_clock(raw: object) -> RunClock:
    if (not isinstance(raw, dict) or set(raw) != {"origin", "ticks_per_second"}
            or not isinstance(raw["origin"], str)
            or type(raw["ticks_per_second"]) is not int or raw["ticks_per_second"] <= 0):
        raise ValueError("a recording clock needs a UTC origin and positive integer ticks_per_second")
    return RunClock(instant(raw["origin"]), raw["ticks_per_second"])


def integer_tick(ticks: Fraction | int) -> int:
    if not -(2 ** 63) <= ticks < 2 ** 63:
        raise ValueError("event-time offsets exceed the loop theory's integer range")
    return int(ticks)


def scale_timed_records(records: dict, run: str, factor: int) -> dict:
    scaled = records.copy()
    if factor != 1:
        for kind, columns in TICK_COLUMNS.items():
            if kind in records:
                scaled[kind] = [
                    {**row, **{name: integer_tick(row[name] * factor) for name in columns}}
                    if row["run"] == run else row
                    for row in records[kind]
                ]
    return scaled


def validate_contract(value: dict, schema: str, target: str) -> None:
    from contracts.validate import validator

    if not isinstance(value, dict):
        raise ValueError(f"{target} must be an object")
    results = validator(schema).validate(value, target).results
    if results:
        raise ValueError(f"{target}: {results[0].message}")


@dataclass
class Event:
    envelope: dict
    token: str
    time: Fraction

    def record(self, offset: int) -> dict:
        observation = self.envelope["observation"]
        value = observation["value"]
        return {"id": observation["id"], "run": self.envelope["run"], "token": self.token,
                "event_time": offset, "state": value["state"], "value": value.get("value", ""),
                "reason": self.envelope["reason"]}


def event(envelope: dict, readers: set[str], expectations: set[str]) -> Event:
    fields = {"run", "sweep", "port", "reason"}
    if (not isinstance(envelope, dict) or set(envelope) != fields | {"observation"}
            or not all(isinstance(envelope[k], str) and envelope[k].strip() for k in fields)):
        raise ValueError("an observation envelope needs run, sweep, port, reason and observation")
    if envelope["port"] not in readers:
        raise ValueError("observation port must declare loop_observation as an input port's product")
    observation = envelope["observation"]
    validate_contract(observation, "observation.yaml", "Observation")
    reference = observation["expectation"]
    key = json.loads(reference["key"])
    if (reference["relation"] != "loop_expectation__value" or not isinstance(key, list) or len(key) != 1
            or not isinstance(key[0], str) or key[0] not in expectations):
        raise ValueError("observation must reference an admitted loop expectation")
    if observation["value"]["state"] == "known" and "value" not in observation["value"]:
        raise ValueError("a known observation needs its value")
    return Event(envelope, key[0], instant(observation["event_time"]))


@dataclass
class Sweep:
    events: list[Event]
    receipt: dict | None = None
    dated: dict | None = None


def read_sweep(raw: list | dict, readers: set[str], expectations: set[str]) -> Sweep:
    if isinstance(raw, list):
        # Historical envelope lists record observations without a separate closure receipt.
        return Sweep([event(item, readers, expectations) for item in raw])
    if not isinstance(raw, dict) or set(raw) != {"id", "run", "event_time", "complete", "observations"}:
        raise ValueError("a dated sweep needs id, run, event_time, complete and observations")
    if (any(not isinstance(raw[k], str) or not raw[k].strip() for k in ("id", "run"))
            or type(raw["event_time"]) is not int or not -(2**63) <= raw["event_time"] < 2**63
            or type(raw["complete"]) is not bool or not isinstance(raw["observations"], list)):
        raise ValueError("invalid dated sweep metadata")
    events = [event(item, readers, expectations) for item in raw["observations"]]
    if any(e.envelope["sweep"] != raw["id"] or e.envelope["run"] != raw["run"] for e in events):
        raise ValueError("observation belongs to another sweep or run")
    dated = {k: raw[k] for k in ("id", "run", "event_time", "complete")}
    receipt = {k: raw[k] for k in ("id", "run", "event_time")} if raw["complete"] else None
    return Sweep(events, receipt, dated)


@dataclass(frozen=True)
class AttemptRecord:
    step: str
    plan_hash: str
    state: str


@dataclass(frozen=True)
class CertifiedRound:
    run: str
    cut: str
    attempts: tuple[AttemptRecord, ...]


def _admit_evidence(directory: Path, raw: object, model: "Pack", program: "Program") -> dict[str, list[tuple]]:
    """Admit archived Evidence via rezono_checker.evidence.admit and return declared protected rows."""
    from rezono_checker.evidence import Evidence, admit
    from rezono_compiler import rules_dl

    if not isinstance(raw, dict) or set(raw) not in ({"archive", "context"}, {"archive", "context", "index"}):
        raise ValueError("evidence must contain archive, context and optional index")
    archive_rel = raw["archive"]
    if (not isinstance(archive_rel, str) or not archive_rel.strip()
            or Path(archive_rel).anchor or ".." in Path(archive_rel).parts):
        raise ValueError("evidence archive must be a relative directory inside the recording directory")
    base_dir = directory.resolve()
    archive_dir = (directory / archive_rel).resolve()
    if not archive_dir.is_relative_to(base_dir) or not archive_dir.is_dir():
        raise ValueError("evidence archive directory does not exist inside the recording directory")

    context_ref = raw["context"]
    if not isinstance(context_ref, dict) or not isinstance(context_ref.get("uri"), str):
        raise ValueError("evidence context must be an archived-file reference")
    if not context_ref["uri"].startswith(ARCHIVE_ROOT + RETAINED_PREFIX):
        raise ValueError("evidence context must reside under observations/retained/")

    index_ref = raw.get("index")
    if index_ref is not None:
        if not isinstance(index_ref, dict) or not isinstance(index_ref.get("uri"), str):
            raise ValueError("evidence index must be an archived-file reference or null")
        if not index_ref["uri"].startswith(ARCHIVE_ROOT + SUBMITTED_PREFIX):
            raise ValueError("evidence index must reside under observations/submitted/")

    def read_bytes(uri: str) -> bytes | None:
        if not isinstance(uri, str) or not uri.startswith(ARCHIVE_ROOT):
            return None
        key = uri.removeprefix(ARCHIVE_ROOT)
        if not key.startswith((RETAINED_PREFIX, SUBMITTED_PREFIX)):
            return None
        parts = key.split("/")
        if not all(KEY_SEGMENT.fullmatch(part) and part not in (".", "..") for part in parts):
            return None
        target = (archive_dir / key).resolve()
        if not target.is_relative_to(archive_dir) or not target.is_file():
            return None
        return target.read_bytes()

    admitted = admit(Evidence(context_ref, index_ref, read_bytes))
    protected = {name: admitted.rows.get(name, []) for name in sorted(rules_dl.PROTECTED) if name in program.relations}
    base_tables = rules_dl.base_tables(model)
    for name in protected:
        key = [(col.name, col.type) for col in program.relations[name].key]
        if name in base_tables or key != rules_dl.PROTECTED[name]:
            raise ValueError(f"{name} is a protected admission input and must be declared with its fixed signature")
    return protected


def read_certified_rounds(raw: object, run: str, rounds: list[Sweep]) -> list[CertifiedRound]:
    """Validate recorded certified-round cut bindings and attempt states against the observation rounds."""
    if not isinstance(raw, list) or len(raw) != len(rounds):
        raise ValueError("certified_rounds must provide one entry per observation round")
    parsed: list[CertifiedRound] = []
    for entry, sweep in zip(raw, rounds, strict=True):
        if not isinstance(entry, dict) or set(entry) != {"run", "cut", "attempts"}:
            raise ValueError("a certified round needs run, cut and attempts")
        entry_run, cut, raw_attempts = entry["run"], entry["cut"], entry["attempts"]
        if not isinstance(entry_run, str) or entry_run != run:
            raise ValueError("certified round belongs to another run")
        if not isinstance(cut, str) or not cut.strip():
            raise ValueError("certified round requires a nonempty cut")
        if sweep.receipt is None or sweep.receipt["run"] != run or sweep.receipt["id"] != cut:
            raise ValueError(f"certified round cut {cut!r} does not match the sweep cut")
        if not isinstance(raw_attempts, list):
            raise ValueError("certified round attempts must be a list")
        attempts: list[AttemptRecord] = []
        seen_hashes: set[str] = set()
        for item in raw_attempts:
            if not isinstance(item, dict) or set(item) != {"step", "plan_hash", "state"}:
                raise ValueError("an attempt needs step, plan_hash and state")
            step, plan_hash, state = item["step"], item["plan_hash"], item["state"]
            if not isinstance(step, str) or not step.strip():
                raise ValueError("attempt step must be a nonempty string")
            if not isinstance(plan_hash, str) or not PLAN_HASH.fullmatch(plan_hash):
                raise ValueError("attempt plan_hash must be a lowercase SHA-256 digest")
            if not isinstance(state, str) or state not in ATTEMPT_STATES:
                raise ValueError(f"invalid attempt state {state!r}")
            if plan_hash in seen_hashes:
                raise ValueError(f"duplicate attempt plan_hash {plan_hash!r} in round cut {cut!r}")
            seen_hashes.add(plan_hash)
            attempts.append(AttemptRecord(step, plan_hash, state))
        parsed.append(CertifiedRound(entry_run, cut, tuple(attempts)))
    return parsed


@dataclass
class TypedRecording:
    run: str
    limit: int
    model: "Pack"
    program: "Program"
    records: dict
    rounds: list[Sweep]
    clock: RunClock | None = None
    admitted: dict[str, list[tuple]] = field(default_factory=dict)
    certified_rounds: list[CertifiedRound] | None = None

    def snapshots(self) -> Iterator[Snapshot]:
        from rezono_compiler import batch, facts, scenarios
        from rezono_compiler.diagnostics import Diagnosed

        schema = facts.schema(self.model)

        def is_run_scoped(kind: str) -> bool:
            return kind in schema.kinds and schema.slot(kind, "run") is not None

        stored = {}
        for row in self.records.get("loop_observation", ()):
            key = (row["run"], row["id"])
            if stored.setdefault(key, row) != row:
                raise ValueError(f"conflicting records for observation {row['id']!r}")
        sweeps = {}
        for row in self.records.get("loop_sweep", ()):
            key = (row["run"], row["id"])
            if sweeps.setdefault(key, row) != row:
                raise ValueError(f"conflicting records for sweep {row['id']!r}")
        clock = self.clock
        arrived: list[tuple[Event, Fraction]] = []
        relations = list(RELATIONS)
        for optional in ("fixed_point", "round_outcome"):
            if optional in self.program.derived():
                relations.append(optional)
        if self.certified_rounds is not None:
            relations.extend(("ready", "step_safety_current_cut"))
        try:
            for round_index, sweep in enumerate(self.rounds):
                if sweep.dated is not None:
                    key = (sweep.dated["run"], sweep.dated["id"])
                    if sweeps.setdefault(key, sweep.dated) != sweep.dated:
                        raise ValueError(f"conflicting records for sweep {sweep.dated['id']!r}")
                events = [e for e in sweep.events if e.envelope["run"] == self.run]
                if events:
                    if clock is None:
                        # Historical recordings implied their clock. Fix it when evidence first arrives.
                        times = [e.time for e in events]
                        clock = RunClock(min(times), lcm(*(at.denominator for at in times)))
                    arrived.extend((e, clock.ticks(e.time)) for e in events)

                # Refine only this snapshot's representation, scaling stored and arriving ticks together.
                factor = lcm(*(ticks.denominator for _, ticks in arrived))
                records = {}
                for kind, rows in self.records.items():
                    if kind in {"loop_observation", "loop_sweep", "loop_sweep_receipt"}:
                        continue
                    if isinstance(rows, list):
                        scoped = is_run_scoped(kind)
                        kept = [
                            row for row in rows
                            if not (isinstance(row, dict) and (scoped or "run" in row))
                            or row.get("run") == self.run
                        ]
                        if kept:
                            records[kind] = kept
                    else:
                        records[kind] = rows
                records["loop_observation"] = [row for row in stored.values() if row["run"] == self.run]
                active_sweeps = [row for row in sweeps.values() if row["run"] == self.run]
                if active_sweeps:
                    records["loop_sweep"] = active_sweeps
                else:
                    records.pop("loop_sweep", None)
                if sweep.receipt is not None and sweep.receipt["run"] == self.run:
                    records["loop_sweep_receipt"] = [sweep.receipt]
                else:
                    records.pop("loop_sweep_receipt", None)
                records = scale_timed_records(records, self.run, factor)
                observed = {(row["run"], row["id"]): row for row in records["loop_observation"]}
                for e, ticks in arrived:
                    row = e.record(integer_tick(ticks * factor))
                    key = (row["run"], row["id"])
                    if observed.setdefault(key, row) != row:
                        raise ValueError(f"conflicting records for observation {row['id']!r}")
                records["loop_observation"] = list(observed.values())
                fact_rows = facts.rows_of(self.model, records)
                if self.admitted:
                    fact_rows = fact_rows | self.admitted
                inputs = scenarios.rule_rows(self.model, self.program, fact_rows)
                with batch.connect(self.program, inputs) as connection:
                    batch.compute(connection, self.program)
                    rows = batch.read(connection, self.program, relations)
                selected = {name: {row for row in relation if row[0] == self.run}
                            for name, relation in rows.items()}
                round_outcome = None
                if "round_outcome" in selected:
                    outcomes = {row[1] for row in selected["round_outcome"]}
                    if len(outcomes) != 1 or not outcomes <= {"pending", "success", "failure"}:
                        raise ValueError(f"expected one round outcome for {self.run!r}, got {sorted(outcomes)}")
                    round_outcome = next(iter(outcomes))
                if self.certified_rounds is not None:
                    expected_cut = self.certified_rounds[round_index].cut
                    current_cuts = {row[1] for row in selected["step_safety_current_cut"]}
                    if current_cuts != {expected_cut}:
                        raise ValueError(
                            f"certified round cut {expected_cut!r} does not match current cut {sorted(current_cuts)}"
                        )
                    frontier_rows = selected["ready"]
                else:
                    frontier_rows = selected["unblocked"]
                yield Snapshot({row[1] for row in selected["declared"]}, frontier_rows,
                               {row[1] for row in selected["done"]}, {row[1] for row in selected["stuck"]},
                               selected["drift"], selected.get("fixed_point", ()), round_outcome)
        except Diagnosed as error:
            raise ValueError(str(error)) from error


def typed_recording(directory: Path, data: dict) -> TypedRecording:
    from rezono_compiler import facts, modules, pack, rules
    from rezono_compiler.diagnostics import Diagnosed

    clock = read_clock(data["clock"]) if "clock" in data else None
    pin = data["pack"]
    if (not isinstance(pin, dict) or set(pin) != {"path", "sha256"}
            or not isinstance(pin["path"], str) or not pin["path"].strip() or Path(pin["path"]).anchor):
        raise ValueError("the recording needs a relative pack path and its SHA-256")
    path = directory / pin["path"]
    if not path.is_dir() or modules.pack_hash(path) != pin["sha256"]:
        raise ValueError("the recorded pack does not match its SHA-256")
    try:
        model = pack.read(path)
        if model.meta["name"] != "std-loop" or not model.rules:
            raise ValueError("the recording requires the std-loop theory")
        program = rules.load(model.rules)
        if not set(RELATIONS).issubset(program.derived()):
            raise ValueError("the loop theory lacks a required decision relation")
        admitted = facts.rows_of(model, data["records"])
    except Diagnosed as error:
        raise ValueError(str(error)) from error

    if (data["run"],) not in admitted.get("loop_active_run", ()):
        raise ValueError("the recorded run must be active in the admitted records")
    expectations = {token for token, _ in admitted.get("loop_expectation__value", ())}
    if not isinstance(data["ports"], list):
        raise ValueError("ports must be a list of declarations")
    ports = {}
    for declaration in data["ports"]:
        validate_contract(declaration, "port.yaml", "Port")
        name = declaration["name"]
        if name in ports:
            raise ValueError(f"duplicate port declaration {name!r}")
        ports[name] = declaration
    readers = {name for name, port in ports.items()
               if port["kind"] == "in" and "loop_observation" in port["produces"]}
    if not isinstance(data["sweeps"], list):
        raise ValueError("sweeps must be an ordered list")
    rounds = []
    if not isinstance(data["initial"], (list, dict)) or data["records"].get("loop_sweep_receipt"):
        raise ValueError("a sweep receipt must arrive with its observation round")
    identities = {}
    sweep_ids = set()
    latest_boundary = {}
    for raw in chain((data["initial"],), data["sweeps"]):
        sweep = read_sweep(raw, readers, expectations)
        if isinstance(raw, dict):
            key = (raw["run"], raw["id"])
            if key in sweep_ids:
                raise ValueError(f"duplicate dated sweep {key!r}")
            if raw["run"] in latest_boundary and raw["event_time"] < latest_boundary[raw["run"]]:
                raise ValueError("dated sweeps must follow event-time order within a run")
            sweep_ids.add(key)
            latest_boundary[raw["run"]] = raw["event_time"]
        for e in sweep.events:
            observation = e.envelope["observation"]
            key = (e.envelope["run"], observation["id"])
            identity = (observation, e.envelope["reason"])
            if identities.setdefault(key, identity) != identity:
                raise ValueError(f"conflicting observations with event ID {key[1]!r}")
        rounds.append(sweep)

    admitted_rows = _admit_evidence(directory, data["evidence"], model, program) if "evidence" in data else {}
    certified_rounds = None
    if "certified_rounds" in data:
        if not {"ready", "step_safety_current_cut"}.issubset(program.derived()):
            raise ValueError("the loop theory lacks certified round relations")
        certified_rounds = read_certified_rounds(data["certified_rounds"], data["run"], rounds)
    return TypedRecording(
        data["run"], data["limit"], model, program, data["records"], rounds, clock, admitted_rows, certified_rounds
    )
