"""Hand-authored evidence and a finite oracle for a two-lane replacement."""

from dataclasses import dataclass
from typing import Literal

from rezono_canon import canonical_bytes, canonical_sha256


Phase = Literal["old", "offline", "new"]
Lane = Literal["lane-a", "lane-b"]
State = tuple[Phase, Phase]
SignedRow = tuple[str, tuple[str, str], int]

RUN = "replacement"
SCOPE = "serving-lanes"
ISSUER = "lane-observer"
LANES: tuple[Lane, Lane] = ("lane-a", "lane-b")
LANE_PHASE = "lane__phase"
INITIAL: State = ("old", "old")
# Both obligations are required at a boundary. The result rows are separate evidence.
OBLIGATIONS = ("lane-inventory-intact", "at-least-one-lane-serving")


@dataclass(frozen=True)
class Effect:
    step: str
    lane: Lane
    before: Phase
    after: Phase

    @property
    def old_row(self) -> tuple[str, str]:
        return self.lane, self.before

    @property
    def delta(self) -> tuple[SignedRow, SignedRow]:
        return (LANE_PHASE, self.old_row, -1), (LANE_PHASE, (self.lane, self.after), 1)

    @property
    def plan(self) -> dict:
        # The fixture adapter exposes one physical boundary per independently observed effect.
        return {"step": self.step, "target": self.lane, "expected_old": self.old_row, "delta": self.delta}

    @property
    def plan_hash(self) -> str:
        return canonical_sha256(self.plan)


WITHDRAW_A = Effect("withdraw-a", "lane-a", "old", "offline")
ACTIVATE_A = Effect("activate-a", "lane-a", "offline", "new")
WITHDRAW_B = Effect("withdraw-b", "lane-b", "old", "offline")
ACTIVATE_B = Effect("activate-b", "lane-b", "offline", "new")
EFFECTS = (WITHDRAW_A, ACTIVATE_A, WITHDRAW_B, ACTIVATE_B)


@dataclass(frozen=True)
class Readback:
    cut: str
    event_time: int
    state: State
    effect: Effect | None

    def inventory_bytes(self) -> bytes:
        return canonical_bytes({"run": RUN, "scope": SCOPE, "cut": self.cut, "members": LANES})

    def source_bytes(self) -> bytes:
        # These are the retained reader's observations. Speculative states never supply these bytes.
        observation = {
            "id": f"read-{self.cut}", "run": RUN, "scope": SCOPE, "cut": self.cut, "issuer": ISSUER,
            "event_time": self.event_time,
            "rows": [{"lane": lane, "phase": phase} for lane, phase in zip(LANES, self.state, strict=True)],
        }
        if self.effect is not None:
            observation["plan_hash"] = self.effect.plan_hash
        return canonical_bytes(observation)


# Independently recorded actual states. In particular the withdrawal is observed before activation.
OPENING = Readback("opening", 10, ("old", "old"), None)
A_WITHDRAWN = Readback("a-withdrawn", 11, ("offline", "old"), WITHDRAW_A)
A_RESTORED = Readback("a-restored", 12, ("new", "old"), ACTIVATE_A)
B_WITHDRAWN = Readback("b-withdrawn", 13, ("new", "offline"), WITHDRAW_B)
B_RESTORED = Readback("b-restored", 14, ("new", "new"), ACTIVATE_B)


@dataclass(frozen=True)
class Round:
    readback: Readback
    candidates: tuple[Effect, ...]
    selected: tuple[Effect, ...]


# Chosen effects for the recorded progression. The order of the opening candidates is
# intentionally different from the pack's priority order.
ROUNDS = (
    Round(OPENING, (WITHDRAW_B, WITHDRAW_A), (WITHDRAW_A,)),
    Round(A_WITHDRAWN, (WITHDRAW_B, ACTIVATE_A), (ACTIVATE_A,)),
    Round(A_RESTORED, (WITHDRAW_B,), (WITHDRAW_B,)),
    Round(B_WITHDRAWN, (ACTIVATE_B,), (ACTIVATE_B,)),
    Round(B_RESTORED, (), ()),
)
PRIORITIES = {"withdraw-a": 0, "activate-a": 1, "withdraw-b": 2, "activate-b": 3}


ALL_STATES: frozenset[State] = frozenset({
    ("old", "old"), ("old", "offline"), ("old", "new"),
    ("offline", "old"), ("offline", "offline"), ("offline", "new"),
    ("new", "old"), ("new", "offline"), ("new", "new"),
})
VIOLATION: State = ("offline", "offline")
SOLO_A: frozenset[State] = frozenset({INITIAL, ("offline", "old"), ("new", "old")})
SOLO_B: frozenset[State] = frozenset({INITIAL, ("old", "offline"), ("old", "new")})
FINISHED_ONLY: frozenset[State] = frozenset({INITIAL, ("new", "old"), ("old", "new"), ("new", "new")})


def visible_boundaries(start: State, effects: tuple[Effect, ...]) -> dict[State, dict[Effect, State]]:
    """Enumerate every permitted next boundary using only a lane's declared phase order."""
    pending = [start]
    visible = {}
    while pending:
        state = pending.pop()
        if state in visible:
            continue
        successors = {}
        for effect in effects:
            index = LANES.index(effect.lane)
            if state[index] == effect.before:
                step = list(state)
                step[index] = effect.after
                successor = (step[0], step[1])
                successors[effect] = successor
                pending.append(successor)
        visible[state] = successors
    return visible


def serving(state: State) -> int:
    return sum(phase in ("old", "new") for phase in state)
