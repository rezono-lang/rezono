"""Admit recorded observations and evaluate the pinned loop theory at each sweep boundary."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
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


RELATIONS = ("declared", "needed", "known", "waiting", "ready", "done", "stuck", "drift")
INSTANT = re.compile(r"(\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d)(?:\.(\d+))?([Zz]|[+-]\d\d:\d\d)")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
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


@dataclass
class TypedRecording:
    run: str
    limit: int
    model: "Pack"
    program: "Program"
    records: dict
    rounds: list[Sweep]
    clock: RunClock | None = None

    def snapshots(self) -> Iterator[Snapshot]:
        from rezono_compiler import batch, facts, scenarios
        from rezono_compiler.diagnostics import Diagnosed

        stored = {}
        for row in self.records.get("loop_observation", ()):
            if stored.setdefault(row["id"], row) != row:
                raise ValueError(f"conflicting records for observation {row['id']!r}")
        sweeps = {}
        for row in self.records.get("loop_sweep", ()):
            if sweeps.setdefault(row["id"], row) != row:
                raise ValueError(f"conflicting records for sweep {row['id']!r}")
        clock = self.clock
        arrived: list[tuple[Event, Fraction]] = []
        relations = list(RELATIONS)
        for optional in ("fixed_point", "round_outcome"):
            if optional in self.program.derived():
                relations.append(optional)
        try:
            for sweep in self.rounds:
                if sweep.dated is not None:
                    if sweeps.setdefault(sweep.dated["id"], sweep.dated) != sweep.dated:
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
                records = {**self.records, "loop_observation": list(stored.values())}
                if sweeps:
                    records["loop_sweep"] = list(sweeps.values())
                if sweep.receipt is not None:
                    records["loop_sweep_receipt"] = [sweep.receipt]
                records = scale_timed_records(records, self.run, factor)
                observed = {row["id"]: row for row in records["loop_observation"]}
                for e, ticks in arrived:
                    row = e.record(integer_tick(ticks * factor))
                    if observed.setdefault(row["id"], row) != row:
                        raise ValueError(f"conflicting records for observation {row['id']!r}")
                records["loop_observation"] = list(observed.values())
                inputs = scenarios.rule_rows(self.model, self.program, facts.rows_of(self.model, records))
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
                yield Snapshot({row[1] for row in selected["declared"]}, selected["ready"],
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
    if not isinstance(data["initial"], list) or data["records"].get("loop_sweep_receipt"):
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
    return TypedRecording(data["run"], data["limit"], model, program, data["records"], rounds, clock)
