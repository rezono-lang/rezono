"""Standard pack std-review: the assessment of admitted reviews (decisions/review-and-rights.md).

The expectations are written by hand from the decision, case by case, not taken from an implementation. Each test
compiles a small consumer pack of its own (two kinds, three roles, grant clauses for may_read and may_review) that
imports std-access and std-review, and evaluates it on the DuckDB batch backend with base rows given per case.
Every case that grants something has a counter-case in which the one ground it needs is missing.
"""

import json
from contextlib import closing
from pathlib import Path

import pytest

from support import REPO
from rezono_compiler import batch, modules, pack
from rezono_compiler import rules as ir

pytest.importorskip("duckdb")

ACCESS = REPO / "packs" / "std-access"
REVIEW = REPO / "packs" / "std-review"

# Content and support hashes: two versions of each.
C1, C2 = "c1" * 32, "c2" * 32
S1, S2 = "5a" * 32, "5b" * 32

STATES = ("change_accepted", "change_rejected", "change_stale", "change_proposed", "review_due")
CHECKS = ("review_self", "review_unauthorized", "review_blind", "review_conflict")

CONSUMER_RULES = """\
// Grants of the consumer: notes for every reader, shelves only for the restricted reader; review of notes only.
.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read(r, "note", x) :- role__capability(r, "read"), note(x).
may_read(r, "shelf", x) :- role__capability(r, "read_restricted"), shelf(x).
.decl may_review(role: symbol, kind: symbol, element: symbol)
may_review(r, "note", x) :- role__capability(r, "review"), note(x).
"""

CONSUMER_SCHEMA = """\
id: https://rezono.example/review-probe
name: review_probe
in_language: en
imports:
  - linkml:types
default_range: string
annotations:
  layer: facts
classes:
  Note:
    attributes:
      id: {identifier: true}
  Shelf:
    attributes:
      id: {identifier: true}
"""

CONSUMER_MESSAGES = """\
@locale en
---
arrow.total = Each {$kind} has exactly one {$arrow}.
arrow.partial = Each {$kind} has at most one {$arrow}.
attribute.total = Each {$kind} has exactly one {$attribute}.
attribute.partial = Each {$kind} has at most one {$attribute}.
attribute.many.total = Each {$kind} has at least one {$attribute}.
attribute.many.partial = Each {$kind} may have more than one {$attribute}.
is_a = Each {$kind} is a {$parent}.
unique_key = Each {$key} belongs to at most one {$kind}.
path_equation = For each {$kind}, {$equation} holds.
"""

# Roles: a scribe reads and reviews notes; a warden also reads shelves; a clerk only reads notes.
ROLES = {"scribe": ("read", "review"), "warden": ("read", "read_restricted", "review"), "clerk": ("read",)}


def consumer(tmp_path: Path) -> Path:
    d = tmp_path / "review-probe"
    for sub in ("schema", "rules", "labels", "messages"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    imports = "".join(f"  - name: {p.name}\n    path: {p.as_posix()}\n    sha256: {modules.pack_hash(p)}\n"
                      for p in (ACCESS, REVIEW))
    (d / "pack.yaml").write_text(f'name: review-probe\nversion: "0"\ndefault_language: en\nimports:\n{imports}',
                                 encoding="utf-8")
    (d / "channels.yaml").write_text("kinds:\n  - {kind: note, shape: rect}\n  - {kind: shelf, shape: ellipse}\n",
                                     encoding="utf-8")
    (d / "schema" / "probe.yaml").write_text(CONSUMER_SCHEMA, encoding="utf-8")
    (d / "rules" / "grants.dl").write_text(CONSUMER_RULES, encoding="utf-8")
    (d / "labels" / "en.yaml").write_text("note: note\nshelf: shelf\n", encoding="utf-8")
    (d / "messages" / "en.mf2").write_text(CONSUMER_MESSAGES, encoding="utf-8")
    return d


class Probe:
    """The consumer pack, compiled once per test; `run` evaluates one world."""

    def __init__(self, tmp_path: Path, missing: type[AssertionError]):
        self.missing = missing
        if not (REVIEW / "pack.yaml").exists():
            raise missing("packs/std-review does not exist yet")
        try:
            model = pack.read(consumer(tmp_path))
            self.prog = ir.load(model.rules)
            self.kinds = set(model.kinds)
        except Exception as refused:
            raise missing(f"the consumer pack does not compile: {refused}") from refused

    def invariant(self, *names):
        rels = self.prog.relations
        wrong = [n for n in names if n not in rels or not rels[n].invariant]
        if wrong:
            raise self.missing(f"not declared as a blocking invariant: {wrong}")

    def run(self, rows: dict) -> dict:
        # A table no rule reads is not in the program; its kind must still be in the schema.
        unknown = sorted(n for n in rows if n not in self.prog.relations and n.split("__")[0] not in self.kinds)
        if unknown:
            raise self.missing(f"tables the decision names are not in the pack: {unknown}")
        try:
            with closing(batch.connect(self.prog, {k: sorted(v) for k, v in rows.items()})) as con:
                batch.compute(con, self.prog)
                return batch.read(con, self.prog)
        except Exception as failed:
            raise self.missing(f"evaluation failed: {failed}") from failed

    def expect(self, label: str, got: dict, want: dict):
        """Each relation in `want` must hold exactly these rows; a relation the program lacks is missing."""
        diff = {}
        for name, rows in want.items():
            have = got.get(name)
            if have is None or have != {tuple(str(v) for v in r) for r in rows}:
                diff[name] = {"expected": sorted(map(list, rows)), "actual": None if have is None else sorted(map(list, have))}
        if diff:
            raise self.missing(f"{label}: {json.dumps(diff, indent=1)}")


def world(changes=(), reviews=(), grants=(), dismissed=(), phase=None, policies=()):
    """Base rows from short records.

    change: (id, author, content, support, members, supports), members and supports as (kind, element) pairs;
    review: (id, change, reviewer, role, verdict, day, content, support), with a reason when rejected;
    grant: (id, subject, role, first day, exclusive last day or None, introducing change or None);
    phase: (phase, owner); policy: (id, kind, policy).
    """
    rows: dict = {}

    def add(table, *row):
        rows.setdefault(table, set()).add(row)

    for role, capabilities in ROLES.items():
        add("role", role)
        for c in capabilities:
            add("role__capability", role, c)
    for n in ("n1", "n2", "x1"):
        add("note", n)
    for s in ("s1", "x1"):
        add("shelf", s)
    for c, author, content, support, members, supports in changes:
        add("change", c)
        add("change__author", c, author)
        add("change__content_sha256", c, content)
        add("change__support_sha256", c, support)
        for i, (kind, element) in enumerate(members):
            m = f"{c}-m{i}"
            add("change_member", m), add("change_member__change", m, c)
            add("change_member__kind", m, kind), add("change_member__element", m, element)
        for i, (kind, element) in enumerate(supports):
            s = f"{c}-s{i}"
            add("change_support", s), add("change_support__change", s, c)
            add("change_support__kind", s, kind), add("change_support__element", s, element)
    for r, c, reviewer, role, verdict, day, content, support in reviews:
        add("review", r)
        add("review__change", r, c)
        add("review__reviewer", r, reviewer)
        add("review__role", r, role)
        add("review__verdict", r, verdict)
        add("review__day", r, day)
        add("review__content_sha256", r, content)
        add("review__support_sha256", r, support)
        if verdict == "rejected":
            add("review__reason", r, "the totals do not add up")
    for g, subject, role, first, last, introduced_by in grants:
        add("role_grant", g)
        add("role_grant__subject", g, subject)
        add("role_grant__role", g, role)
        add("role_grant__from_day", g, first)
        if last is not None:
            add("role_grant__until_day", g, last)
        if introduced_by is not None:
            add("role_grant__change", g, introduced_by)
    for i, r in enumerate(dismissed):
        add("review_dismissal", f"d{i}"), add("review_dismissal__review", f"d{i}", r)
    if phase is not None:
        add("review_phase", "phase"), add("review_phase__phase", "phase", phase[0])
        add("review_phase__owner", "phase", phase[1])
    for p, kind, policy in policies:
        add("review_policy", p), add("review_policy__kind", p, kind), add("review_policy__policy", p, policy)
    return rows


# A change by one person to a note, resting on another note; a reviewer who held the scribe role all year.
NOTE_CHANGE = ("ch-1", "ivo", C1, S1, [("note", "n1")], [("note", "n2")])
SCRIBE_YEAR = ("g-una", "una", "scribe", 20260101, None, None)
IVO_SCRIBE = ("g-ivo", "ivo", "scribe", 20260101, None, None)


def accept(r="rv-1", change="ch-1", who="una", role="scribe", day=20260310, content=C1, support=S1):
    return (r, change, who, role, "accepted", day, content, support)


def reject(r="rv-2", change="ch-1", who="una", role="scribe", day=20260310, content=C1, support=S1):
    return (r, change, who, role, "rejected", day, content, support)


def states(accepted=(), rejected=(), stale=(), proposed=(), due=()):
    return {"change_accepted": {(c,) for c in accepted}, "change_rejected": {(c,) for c in rejected},
            "change_stale": {(c,) for c in stale}, "change_proposed": {(c,) for c in proposed},
            "review_due": {(c,) for c in due}}


class MissingReviewStates(AssertionError):
    """std-review is missing, or derives the review state of a change otherwise than the decision gives."""


def test_review_states(tmp_path):
    p = Probe(tmp_path, MissingReviewStates)
    grants = [SCRIBE_YEAR]
    p.expect("no review", p.run(world([NOTE_CHANGE], grants=grants)), states(proposed=["ch-1"], due=["ch-1"]))
    p.expect("a valid acceptance", p.run(world([NOTE_CHANGE], [accept()], grants)), states(accepted=["ch-1"]))
    p.expect("a valid rejection with a reason", p.run(world([NOTE_CHANGE], [reject()], grants)),
             states(rejected=["ch-1"]))
    newer_content = ("ch-1", "ivo", C2, S1, [("note", "n1")], [("note", "n2")])
    p.expect("the content changed after the acceptance", p.run(world([newer_content], [accept()], grants)),
             states(stale=["ch-1"], due=["ch-1"]))
    newer_support = ("ch-1", "ivo", C1, S2, [("note", "n1")], [("note", "n2")])
    p.expect("the support changed, the content did not", p.run(world([newer_support], [accept()], grants)),
             states(stale=["ch-1"], due=["ch-1"]))
    other = ("ch-2", "ivo", C2, S2, [("note", "x1")], [])
    p.expect("another change moved", p.run(world([NOTE_CHANGE, other], [accept()], grants)),
             states(accepted=["ch-1"], proposed=["ch-2"], due=["ch-2"]))
    # A review of another change is no history of this one: the new change is proposed, not stale.
    old = ("ch-0", "ivo", C1, S1, [("note", "n1")], [])
    fresh = ("ch-3", "ivo", C2, S1, [("note", "n1")], [])
    p.expect("only another change was reviewed", p.run(world([old, fresh], [accept(change="ch-0")], grants)),
             states(accepted=["ch-0"], proposed=["ch-3"], due=["ch-3"]))
    # A re-review of the new pair accepts again; the earlier review stays as it was, and is no longer current.
    rereviewed = p.run(world([newer_support], [accept(), accept("rv-3", day=20260402, support=S2)], grants))
    p.expect("a re-review of the new support", rereviewed, states(accepted=["ch-1"]))
    p.expect("only the re-review is current", rereviewed, {"review_current": {("rv-3",)},
                                                             "review_active": {("rv-1",), ("rv-3",)}})
    # An old rejection about another content does not stand against a current acceptance.
    p.expect("an old rejection", p.run(world([NOTE_CHANGE], [accept(), reject(content=C2)], grants)),
             states(accepted=["ch-1"]))


class MissingSelfReviewCheck(AssertionError):
    """std-review lacks the four-eyes check review_self, or applies it otherwise than the decision gives."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingSelfReviewCheck,
    reason="extra: decisions/review-and-rights.md: Write packs/std-review/rules/self.dl: the invariant "
           "review_self(review) for an author of the change (its author, or the subject of a role_grant the change "
           "introduces), with the lab exception for the owner's own work only, and add !review_self(r) to "
           "review_valid in rules/state.dl. Read sections 7, 8 and 10 and the open case on a beneficiary. Waits "
           "for test_review_states.",
)
def test_review_self(tmp_path):
    p = Probe(tmp_path, MissingSelfReviewCheck)
    p.invariant("review_self")
    grants = [SCRIBE_YEAR, IVO_SCRIBE]
    own = [accept(who="ivo")]
    for label, phase in (("four eyes in the strict phase", ("strict", "una")), ("no phase fact is strict", None),
                         ("the lab exception is for the owner only", ("lab", "una"))):
        p.expect(label, p.run(world([NOTE_CHANGE], own, grants, phase=phase)),
                 {"review_self": {("rv-1",)}, **states(proposed=["ch-1"], due=["ch-1"])})
    p.expect("the owner's own work in the lab phase", p.run(world([NOTE_CHANGE], own, grants, phase=("lab", "ivo"))),
             {"review_self": set(), **states(accepted=["ch-1"])})
    p.expect("two people with one role", p.run(world([NOTE_CHANGE], [accept()], grants, phase=("strict", "una"))),
             {"review_self": set(), **states(accepted=["ch-1"])})
    p.expect("a dismissed self-review blocks nothing",
             p.run(world([NOTE_CHANGE], own, grants, dismissed=["rv-1"], phase=("strict", "una"))),
             {"review_self": set(), **states(proposed=["ch-1"], due=["ch-1"])})
    # A change that grants the warden role to the owner: the owner is its beneficiary, also in the lab phase.
    grant_change = ("ch-g", "ivo", C1, S1, [("note", "n1")], [])
    raise_una = ("g-new", "una", "warden", 20260301, None, "ch-g")
    p.expect("a beneficiary in the lab phase",
             p.run(world([grant_change], [accept(change="ch-g")], grants + [raise_una], phase=("lab", "una"))),
             {"review_self": {("rv-1",)}, **states(proposed=["ch-g"], due=["ch-g"])})
    p.expect("someone else accepts the grant",
             p.run(world([grant_change], [accept(change="ch-g", who="ada")],
                         grants + [raise_una, ("g-ada", "ada", "scribe", 20260101, None, None)],
                         phase=("lab", "una"))),
             {"review_self": set(), **states(accepted=["ch-g"])})


class MissingReviewAuthorityCheck(AssertionError):
    """std-review lacks review_unauthorized, or does not evaluate review rights at the moment of review."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReviewAuthorityCheck,
    reason="extra: decisions/review-and-rights.md: Write packs/std-review/rules/authority.dl: the invariant "
           "review_unauthorized(review) from the role_grant held on the review day (first day inclusive, last day "
           "exclusive), not introduced by the reviewed change, and may_review of that role over every "
           "change_member; a grant that a change introduces counts only from the day a review on founding "
           "grants alone accepted that change, and while it stays accepted. Add !review_unauthorized(r) to "
           "review_valid in rules/state.dl. Read sections 3, 5, 7 and 8. Waits for test_review_blind, which edits "
           "the same rule, and for compiler/tests/test_std_access.py::test_standard_access_declares_the_four_rights (may_review).",
)
def test_review_unauthorized(tmp_path):
    p = Probe(tmp_path, MissingReviewAuthorityCheck)
    p.invariant("review_unauthorized")
    ok = {"review_unauthorized": set(), **states(accepted=["ch-1"])}
    bad = {"review_unauthorized": {("rv-1",)}, **states(proposed=["ch-1"], due=["ch-1"])}
    revoked_later = ("g-una", "una", "scribe", 20260101, 20260601, None)
    p.expect("a grant revoked after the review", p.run(world([NOTE_CHANGE], [accept()], [revoked_later])), ok)
    starts_later = ("g-una", "una", "scribe", 20260401, None, None)
    p.expect("a grant that starts after the review", p.run(world([NOTE_CHANGE], [accept()], [starts_later])), bad)
    p.expect("the last day is exclusive", p.run(world([NOTE_CHANGE], [accept(day=20260601)], [revoked_later])), bad)
    p.expect("no grant at all", p.run(world([NOTE_CHANGE], [accept()])), bad)
    # A grant introduced by the change under review authorises no review of that change.
    self_grant = ("g-una", "una", "scribe", 20260101, None, "ch-1")
    p.expect("a grant in the reviewed change", p.run(world([NOTE_CHANGE], [accept()], [self_grant])), bad)
    # A grant introduced by a change counts for another change only once its own change is accepted, on the
    # authority of founding grants alone, from the day of that acceptance and while it stays accepted.
    other = ("ch-2", "ivo", C2, S2, [("note", "n2")], [])
    by_una = accept("rv-2", change="ch-2", content=C2, support=S2)
    founder = ("g-ada", "ada", "scribe", 20260101, None, None)
    p.expect("a grant whose change is still proposed",
             p.run(world([NOTE_CHANGE, other], [by_una], [self_grant])),
             {"review_unauthorized": {("rv-2",)}, **states(proposed=["ch-1", "ch-2"], due=["ch-1", "ch-2"])})
    by_ada = accept(who="ada", day=20260305)
    p.expect("a grant whose change a founder accepted",
             p.run(world([NOTE_CHANGE, other], [by_ada, by_una], [self_grant, founder])),
             {"review_unauthorized": set(), **states(accepted=["ch-1", "ch-2"])})
    p.expect("a review before that acceptance",
             p.run(world([NOTE_CHANGE, other], [by_ada, by_una[:5] + (20260301,) + by_una[6:]], [self_grant, founder])),
             {"review_unauthorized": {("rv-2",)}, **states(accepted=["ch-1"], proposed=["ch-2"], due=["ch-2"])})
    moved = ("ch-1", "ivo", C2, S1, [("note", "n1")], [("note", "n2")])
    p.expect("a grant whose accepted change went stale",
             p.run(world([moved, other], [by_ada, by_una], [self_grant, founder])),
             {"review_unauthorized": {("rv-2",)}, **states(stale=["ch-1"], proposed=["ch-2"], due=["ch-1", "ch-2"])})
    # Two changes that grant each other's reviewer a role cannot accept each other into being.
    first = ("ch-1", "ivo", C1, S1, [("note", "n1")], [])
    second = ("ch-2", "ivo", C2, S2, [("note", "n2")], [])
    crosswise = [("g-una", "una", "scribe", 20260101, None, "ch-1"), ("g-ada", "ada", "scribe", 20260101, None, "ch-2")]
    p.expect("two changes that grant each other's reviewer",
             p.run(world([first, second], [accept(who="ada"), by_una], crosswise)),
             {"review_unauthorized": {("rv-1",), ("rv-2",)},
              **states(proposed=["ch-1", "ch-2"], due=["ch-1", "ch-2"])})
    # Rights are typed: a review right over the note x1 is none over the shelf x1.
    shelf = ("ch-1", "ivo", C1, S1, [("shelf", "x1")], [])
    note = ("ch-1", "ivo", C1, S1, [("note", "x1")], [])
    wide = ("g-una", "una", "warden", 20260101, None, None)
    p.expect("the same id under another kind", p.run(world([shelf], [accept(role="warden")], [wide])), bad)
    p.expect("the kind the right names", p.run(world([note], [accept(role="warden")], [wide])), ok)
    p.expect("a role claimed but not held", p.run(world([NOTE_CHANGE], [accept(role="warden")], [SCRIBE_YEAR])), bad)
    clerk = ("g-una", "una", "clerk", 20260101, None, None)
    p.expect("a role without the review right", p.run(world([NOTE_CHANGE], [accept(role="clerk")], [clerk])), bad)


class MissingReadToJudgeCheck(AssertionError):
    """std-review lacks review_blind, or does not require the reviewer to read what the change rests on."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReadToJudgeCheck,
    reason="extra: decisions/review-and-rights.md: Write packs/std-review/rules/blind.dl: the invariant "
           "review_blind(review) when the role the review names lacks may_read over one change_member or "
           "change_support of its change, and add !review_blind(r) to review_valid in rules/state.dl. Read "
           "sections 4 and 8. Waits for test_review_self, which edits the same rule.",
)
def test_review_blind(tmp_path):
    p = Probe(tmp_path, MissingReadToJudgeCheck)
    p.invariant("review_blind")
    on_shelf = ("ch-1", "ivo", C1, S1, [("note", "n1")], [("note", "n2"), ("shelf", "s1")])
    scribe, warden = SCRIBE_YEAR, ("g-una", "una", "warden", 20260101, None, None)
    p.expect("the scribe cannot read the shelf it rests on", p.run(world([on_shelf], [accept()], [scribe])),
             {"review_blind": {("rv-1",)}, **states(proposed=["ch-1"], due=["ch-1"])})
    p.expect("the warden reads it", p.run(world([on_shelf], [accept(role="warden")], [warden])),
             {"review_blind": set(), **states(accepted=["ch-1"])})
    p.expect("everything readable", p.run(world([NOTE_CHANGE], [accept()], [scribe])),
             {"review_blind": set(), **states(accepted=["ch-1"])})


class MissingReviewConflictCheck(AssertionError):
    """std-review lacks review_conflict, or resolves opposite reviews or dismissals otherwise than the decision."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReviewConflictCheck,
    reason="extra: decisions/review-and-rights.md: Write packs/std-review/rules/conflict.dl: the invariant "
           "review_conflict(change) for two valid current reviews with opposite verdicts, without a new state, "
           "and make sure a review_dismissal takes a review out of every count. Read section 8 and the open cases "
           "on two opposite reviews and on a dismissed approval. Waits for test_review_states.",
)
def test_review_conflict_and_dismissal(tmp_path):
    p = Probe(tmp_path, MissingReviewConflictCheck)
    p.invariant("review_conflict")
    grants = [SCRIBE_YEAR, ("g-ada", "ada", "scribe", 20260101, None, None)]
    both = [accept(), reject(who="ada")]
    p.expect("two opposite valid reviews", p.run(world([NOTE_CHANGE], both, grants)),
             {"review_conflict": {("ch-1",)}, **states(proposed=["ch-1"], due=["ch-1"])})
    earlier = accept("rv-0", content=C2, day=20260201)
    p.expect("a conflict after an earlier acceptance", p.run(world([NOTE_CHANGE], both + [earlier], grants)),
             {"review_conflict": {("ch-1",)}, **states(stale=["ch-1"], due=["ch-1"])})
    p.expect("the rejection is dismissed", p.run(world([NOTE_CHANGE], both, grants, dismissed=["rv-2"])),
             {"review_conflict": set(), **states(accepted=["ch-1"])})
    p.expect("the only approval is dismissed", p.run(world([NOTE_CHANGE], [accept()], grants, dismissed=["rv-1"])),
             {"review_conflict": set(), **states(proposed=["ch-1"], due=["ch-1"])})
    p.expect("a rejection about an old content", p.run(world([NOTE_CHANGE], [accept(), reject(who="ada", content=C2)],
                                                             grants)),
             {"review_conflict": set(), **states(accepted=["ch-1"])})


class MissingReviewPolicy(AssertionError):
    """std-review lacks the publication policy per kind, or allows require in the lab phase."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingReviewPolicy,
    reason="extra: decisions/review-and-rights.md: Write packs/std-review/rules/policy.dl: the invariants "
           "unreviewed_required(change) and require_in_lab(policy) and the derived unreviewed_marked(change), "
           "from review_policy per kind of a change_member and review_phase. Read sections 9 and 10. Waits for "
           "test_review_states.",
)
def test_review_policy(tmp_path):
    p = Probe(tmp_path, MissingReviewPolicy)
    p.invariant("unreviewed_required", "require_in_lab")
    if p.prog.relations.get("unreviewed_marked") is None or p.prog.relations["unreviewed_marked"].invariant:
        raise MissingReviewPolicy("unreviewed_marked must be a derived relation that does not block")
    strict = ("strict", "una")
    for policy, required, marked in (("require", {("ch-1",)}, set()), ("mark", set(), {("ch-1",)}),
                                     ("none", set(), set())):
        p.expect(f"{policy}, not accepted",
                 p.run(world([NOTE_CHANGE], grants=[SCRIBE_YEAR], phase=strict, policies=[("pol", "note", policy)])),
                 {"unreviewed_required": required, "unreviewed_marked": marked, "require_in_lab": set()})
        p.expect(f"{policy}, accepted",
                 p.run(world([NOTE_CHANGE], [accept()], [SCRIBE_YEAR], phase=strict,
                             policies=[("pol", "note", policy)])),
                 {"unreviewed_required": set(), "unreviewed_marked": set()})
    p.expect("a policy for another kind", p.run(world([NOTE_CHANGE], phase=strict,
                                                      policies=[("pol", "shelf", "require")])),
             {"unreviewed_required": set(), "unreviewed_marked": set()})
    p.expect("require in the lab phase", p.run(world(phase=("lab", "una"), policies=[("pol", "note", "require")])),
             {"require_in_lab": {("pol",)}})
    p.expect("mark in the lab phase", p.run(world(phase=("lab", "una"), policies=[("pol", "note", "mark")])),
             {"require_in_lab": set()})
