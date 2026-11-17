from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.12.0"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'rede',
     'default_range': 'string',
     'description': 'Explanation as a question about the proof (decisions R8, R9, '
                    'R10; docs/gui.md, "Explanation as questions over the proof"). '
                    'A question is data: a term, what it starts from, its steps '
                    '(the building blocks trace and suppose) and the shape of its '
                    'answer. Packs write them in questions.yaml (rede.questions/1, '
                    'checked by the compiler: only names that exist in the pack); '
                    'the standard pack std-explain gives the known ones. The '
                    'compiler puts them in the schema bundle in the form below, '
                    "imports first, then the pack's own. The gate answers a "
                    'question page by page (Answer, rede.answer/1, from GET '
                    '/<pack>/<manifest>/ask/<term>).',
     'id': 'https://rede.dev/contracts/explain',
     'imports': ['linkml:types', 'proof', 'source'],
     'name': 'rede_explain',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'explain.yaml',
     'title': 'Explanation questions'} )

class Polarity(str, Enum):
    """
    Whether a premise must be present or absent.
    """
    positive = "positive"
    """
    The premise holds in the model at the snapshot.
    """
    negative = "negative"
    """
    The premise is absent from its (lower) stratum at the snapshot.
    """


class ValueState(str, Enum):
    """
    The four states of a value. Their codes 0 known, 1 not_applicable, 2 unknown, 3 invalid are also the precedence order: a result derived from several states takes the highest (Reckon v0 §7b; docs/semantics/values.md §3).
    """
    known = "known"
    """
    Code 0. The value is present and valid.
    """
    unknown = "unknown"
    """
    Code 2. The value should exist but is missing. Never treated as zero.
    """
    not_applicable = "not_applicable"
    """
    Code 1. The value does not apply here. Does not count.
    """
    invalid = "invalid"
    """
    Code 3. The input contradicts the schema (for example overflow or a type error). Whether it blocks is decided at its decision point.
    """


class SourceKind(str, Enum):
    """
    The kind of source in which a fact was recorded.
    """
    git = "git"
    """
    A repository at a pinned commit and a position in a file.
    """
    pack = "pack"
    """
    A fact file written in the pack itself.
    """
    scenario = "scenario"
    """
    A scenario file that supplies or replaces a record.
    """
    proposal = "proposal"
    """
    A proposal and the delta step that supplies a row.
    """
    query = "query"
    """
    A query on a system, such as a metric, an API or a database.
    """
    tool = "tool"
    """
    A tool that reports a status or a measurement.
    """
    person = "person"
    """
    A recorded fact or observation by a person.
    """
    document = "document"
    """
    A document outside Git, with an anchored fragment, its hash, a version or retrieval instant, and its licence and attribution.
    """


class SourceOwnership(str, Enum):
    """
    Declared by the ingester; ownership is not inferred from a hostname or source kind.
    """
    first_party = "first_party"
    """
    Content owned by the pack's author.
    """
    third_party = "third_party"
    """
    Content from another party; licence and attribution are required.
    """


class DayReading(str, Enum):
    """
    How a whole number is read as a day (the vocabulary of contracts/pack.yaml, ViewColumn.reading).
    """
    days = "days"
    """
    The number of days since 1970-01-01 in the proleptic Gregorian calendar (decision R18).
    """
    yyyymmdd = "yyyymmdd"
    """
    A whole number written YYYYMMDD.
    """


class QuestionStart(str, Enum):
    """
    What a question starts from.
    """
    present = "present"
    """
    A row that exists.
    """
    absent = "absent"
    """
    A row that does not exist, in a derived relation (gap).
    """
    delta = "delta"
    """
    A published proposal or sweep variant (proposal= or variant=).
    """
    sweep = "sweep"
    """
    A sweep of the pack (sweep=): each of its variants.
    """


class AnswerShape(str, Enum):
    """
    The shape of the answer, which std-view draws.
    """
    route = "route"
    """
    The Route, with numbered steps from the root.
    """
    rings = "rings"
    """
    Nodes by distance, as rings (the Compass).
    """
    gap = "gap"
    """
    The route down to the first failing premise, with candidates.
    """
    overlay = "overlay"
    """
    The fold of current and proposed.
    """
    series = "series"
    """
    A series of scenarios over a range (sweep).
    """


class Direction(str, Enum):
    """
    The direction of a walk through the proof.
    """
    back = "back"
    """
    From a conclusion to its premises, to the sources.
    """
    forward = "forward"
    """
    From a premise to what it derives.
    """


class Through(str, Enum):
    """
    What a walk goes through.
    """
    proof = "proof"
    """
    The role's proof graph (the relation step).
    """
    rules = "rules"
    """
    The rules, with the premise test on the snapshot (gap); only back from an absent start.
    """


class SupposeDelta(str, Enum):
    """
    Which delta a suppose step applies.
    """
    given = "given"
    """
    The deltas the start names: a published proposal or variant, or each variant of a sweep.
    """
    candidates = "candidates"
    """
    The candidate deltas the trace before it proposes.
    """
    without = "without"
    """
    The published variant whose only change withdraws the start fact (consequence, RV-X24): with the pack's own means its standing changes (its state becomes withdrawn); no row is deleted (RV-A33). Its difference is what breaks without that fact. No such variant: the answer is not_computed.
    """


class DeltaKind(str, Enum):
    """
    What a delta start names.
    """
    proposal = "proposal"
    """
    A proposal by its id (the pull request); its manifest on the newest main.
    """
    variant = "variant"
    """
    A sweep variant by its manifest id.
    """
    sweep = "sweep"
    """
    A sweep by its name.
    """
    supposition = "supposition"
    """
    A delta given with the request and computed live (POST /<pack>/<manifest>/suppose); nothing is published. Its id is the sha256 of the delta's canonical text.
    """


class DifferenceChange(str, Enum):
    """
    What a delta did to one row of a role's snapshot.
    """
    added = "added"
    """
    In the target only.
    """
    removed = "removed"
    """
    In the base only.
    """
    changed = "changed"
    """
    A changed cell: the one row with this key prefix (all columns but the last) on each side, and they differ.
    """


class NodeChange(str, Enum):
    """
    What a delta did to a node of an impact answer (the ripple, docs/interaction.md section 3), for the role. Always said, never left out.
    """
    added = "added"
    """
    In the target only.
    """
    removed = "removed"
    """
    In the base only.
    """
    changed = "changed"
    """
    A changed cell; was names the row in the base.
    """
    unchanged = "unchanged"
    """
    The shore: reached by the walk and the same on both sides; the walk does not go past it.
    """
    not_read_in_full = "not_read_in_full"
    """
    The role reads the row's relation in part, or not at all (an anonymous step): what changed there is not said.
    """


class Incompleteness(str, Enum):
    """
    Why an impact answer is not complete.
    """
    depth = "depth"
    """
    The walk ended at its depth before every changed row the role reads had a ring.
    """
    budget = "budget"
    """
    The walk ended at the gate's limit of nodes.
    """
    not_read_in_full = "not_read_in_full"
    """
    A relation of the difference is read in part, or a changed row is reached only through what the role does not read.
    """


class SeriesStatus(str, Enum):
    """
    The state of one grid value of a sweep, for the role (as GET /<pack>/sweeps gives it).
    """
    green = "green"
    warning = "warning"
    red = "red"
    """
    Its checks failed: a diagnosis, no difference.
    """
    not_computed = "not_computed"
    """
    No variant published for it yet.
    """
    unavailable = "unavailable"
    """
    The role reads the swept cell but not every relation in full: no status.
    """


class StepHow(str, Enum):
    """
    How a premise counts for its conclusion, on an edge of the proof graph (the relation step).
    """
    positive = "positive"
    """
    A premise that holds.
    """
    negative = "negative"
    """
    A premise that is absent.
    """
    contributes = "contributes"
    """
    A row of an aggregated group.
    """


class GapItem(str, Enum):
    """
    What an item of a rule's schedule is in the rule (rede_compiler.gap).
    """
    positive = "positive"
    """
    A positive literal of the body.
    """
    negative = "negative"
    """
    A negated literal of the body.
    """
    condition = "condition"
    """
    A comparison.
    """
    assignment = "assignment"
    """
    Arithmetic into a variable.
    """
    aggregate = "aggregate"
    """
    An aggregate over one atom.
    """


class Change(str, Enum):
    """
    What a candidate does to a base relation.
    """
    insert = "insert"
    """
    Add the row.
    """
    delete = "delete"
    """
    Remove the row.
    """


class CandidateStatus(str, Enum):
    """
    Whether a candidate is shown to be enough on its own.
    """
    sufficient = "sufficient"
    """
    Fully bound, nothing on the path can undo it, and the rest of each rule on the path holds with it supposed.
    """
    to_test = "to_test"
    """
    Offered as a proposal: its proposal manifest gives the answer (suppose).
    """


class QuestionDerivation(str, Enum):
    """
    Which values a question applies to.
    """
    fact = "fact"
    conclusion = "conclusion"


class UndecidedState(str, Enum):
    """
    The state of a binder row an ask ... where cannot decide (S1 §3.3, P10.2a §7a): the condition is unknown or invalid there. A not_applicable condition is not undecided; the row is left out and counted.
    """
    unknown = "unknown"
    """
    The condition depends on a value that is not known.
    """
    invalid = "invalid"
    """
    The condition depends on a value or calculation that is invalid.
    """



class RowRef(ConfiguredBaseModel):
    """
    A reference to one row of one relation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    relation: str = Field(default=..., description="""Relation name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    key: str = Field(default=..., description="""Canonical key of the row: stable and deterministic.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef', 'DifferenceEntry', 'AnswerNode', 'GapCandidate']} })


class Premise(ConfiguredBaseModel):
    """
    One body atom of a witness, with its polarity and stratum.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    row: RowRef = Field(default=..., description="""The row the premise refers to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise', 'SourceEntry']} })
    polarity: Polarity = Field(default=..., description="""Whether the row must be present or absent.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise']} })
    stratum: int = Field(default=..., description="""Stratum of the premise relation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise']} })


class Aggregate(ConfiguredBaseModel):
    """
    Evidence for an aggregate premise; the checker recomputes it over the group.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    relation: str = Field(default=..., description="""Relation that is aggregated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    position: Optional[int] = Field(default=None, description="""The place of this aggregate in the rule (from 0). Two aggregates over the same relation and group (a count and a sum) are told apart by it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate', 'SourceRecord', 'Source', 'AnswerStep']} })
    group_key: str = Field(default=..., description="""Canonical key of the group.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    count: int = Field(default=..., description="""Number of contributing rows in the group.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    contributors_sha256: str = Field(default=..., description="""Hash over the sorted keys and values of all contributing rows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    result: str = Field(default=..., description="""Canonical text of the aggregate value with its state.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })


class Witness(ConfiguredBaseModel):
    """
    One rule instance that derives a conclusion.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    conclusion: RowRef = Field(default=..., description="""The row this witness derives.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness', 'AnswerStep']} })
    rule_id: str = Field(default=..., description="""Identifier of the rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness']} })
    bindings: Optional[list[Binding]] = Field(default=None, description="""The substitution of the rule variables.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'GapPremise']} })
    premises: Optional[list[Premise]] = Field(default=None, description="""The instantiated body atoms.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness', 'GapAnswer']} })
    aggregates: Optional[list[Aggregate]] = Field(default=None, description="""Evidence for the aggregate body atoms.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness']} })


class Binding(ConfiguredBaseModel):
    """
    One variable of the rule bound to a canonical value.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    variable: str = Field(default=..., description="""Variable name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding']} })
    value: str = Field(default=..., description="""Canonical value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep']} })


class CalcStep(ConfiguredBaseModel):
    """
    One evaluated node of a calculation (docs/compiler.md, \"Design M3: calculation witnesses\"). A constant has no step; an untaken branch of an `if` and the value of a definition that does not apply are not evaluated.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    path: str = Field(default=..., description="""The node: <definition>/when or <definition>/value, then one argument index per level.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })
    op: str = Field(default=..., description="""What the node is, as the program has it: fact, parameter or rule for a leaf, else the operator (add, if, round, ...).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })
    ref: Optional[str] = Field(default=None, description="""For a leaf: the fact, the parameter or the rule (rule or rule@version) it names, so an explanation can name and link it. Absent for an operator.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })
    relation: Optional[str] = Field(default=None, description="""For a leaf: the table or view it is read from (the attribute table, the derived relation, the parameter table, the rule's view). Absent for an operator and for an input concept.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    value: Optional[str] = Field(default=None, description="""Canonical text of the value (a number as n or n/d in lowest terms, a boolean as true or false); empty unless the state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep']} })
    state: ValueState = Field(default=..., description="""State of the value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'UndecidedRow']} })
    reason: Optional[str] = Field(default=None, description="""Why the value is not known; empty when it is.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })
    element: Optional[str] = Field(default=None, description="""For a parameter leaf: the id of the parameter element it read, so an explanation reaches the row and its source. Absent when no row was read or chosen.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep', 'ReaderColumn']} })

    @field_validator('path')
    def pattern_path(cls, v):
        pattern=re.compile(r"^[^/]+/(when|value)(/(0|[1-9][0-9]*))*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid path format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid path format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('op')
    def pattern_op(cls, v):
        pattern=re.compile(r"^[a-z]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid op format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid op format: {v}"
            raise ValueError(err_msg)
        return v


class CalcWitness(ConfiguredBaseModel):
    """
    One evaluation of a calculation rule for one subject (decision W12): the chosen version, the definition that applies, the result, and the steps along the path taken. The checker recomputes every step from its arguments and every leaf from the snapshots.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    conclusion: RowRef = Field(default=..., description="""The row it explains, (subject, value, state, reason), in the rule's view (or a version's view, for a version named as rule@version).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness', 'AnswerStep']} })
    rule: str = Field(default=..., description="""The calculation rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'GapPremise']} })
    version: Optional[str] = Field(default=None, description="""The chosen version; empty when none was chosen.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    valid_at: Optional[str] = Field(default=None, description="""The evaluation date the version was chosen on (ISO date); empty when there is none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    known_at: Optional[str] = Field(default=None, description="""The knowledge date the version was chosen on (ISO date); empty when there is none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    definition: Optional[str] = Field(default=None, description="""The name of the definition that applies; empty when none applies.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    value: Optional[str] = Field(default=None, description="""Canonical text of the result; empty unless the state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep']} })
    state: ValueState = Field(default=..., description="""State of the result.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'UndecidedRow']} })
    reason: Optional[str] = Field(default=None, description="""Why the result is not known; empty when it is.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })
    premises: Optional[list[RowRef]] = Field(default=None, description="""The other conclusions it read: rows of derived relations and the results of other calculation rules.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness', 'GapAnswer']} })
    reads: list[str] = Field(default=..., description="""Every relation the evaluation reads, sorted: absences decide states there (a missing fact is unknown or not_applicable, two values invalid), so a role sees the result only while it reads each in full (decision O8).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    steps: Optional[list[CalcStep]] = Field(default=None, description="""The evaluated nodes, in evaluation order: the conditions of all definitions in program order, then the value of the definition that applies; a node before its arguments.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'Question', 'Answer']} })


class Proof(ConfiguredBaseModel):
    """
    The chosen proof for one conclusion; acyclic, shortest first, then lexicographic.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    root: RowRef = Field(default=..., description="""The conclusion this proof explains.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })
    manifest_id: str = Field(default=..., description="""The manifest this proof is checked against.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof', 'Answer', 'BoundSweepList']} })
    witnesses: Optional[list[Witness]] = Field(default=None, description="""The witnesses of the proof graph.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof', 'Answer']} })
    calc_witnesses: Optional[list[CalcWitness]] = Field(default=None, description="""The calculation witnesses of the proof graph (decision W12).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof', 'Answer']} })
    hidden: Optional[list[RowRef]] = Field(default=None, description="""Conclusions whose witnesses the viewer may not see. The witnesses stay in the proof and are checked; the explainer redacts them afterwards.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })


class Value(ConfiguredBaseModel):
    """
    A scalar with its state.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/value',
         'rules': [{'description': 'A value that is not known has no payload.',
                    'postconditions': {'slot_conditions': {'value': {'name': 'value',
                                                                     'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                    'none_of': [{'equals_string': 'known'}]}}}},
                   {'description': 'A known value has no reason, except the core code '
                                   'added_later.',
                    'postconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                     'none_of': [{'equals_string': 'known'}]}}},
                    'preconditions': {'slot_conditions': {'reason': {'name': 'reason',
                                                                     'none_of': [{'equals_string': 'added_later'}],
                                                                     'value_presence': 'PRESENT'}}}}]})

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })
    value: Optional[str] = Field(default=None, description="""Canonical text form; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep']} })
    state: ValueState = Field(default=..., description="""State of the value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'UndecidedRow']} })

    @field_validator('reason')
    def pattern_reason(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid reason format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid reason format: {v}"
            raise ValueError(err_msg)
        return v


class Amount(ConfiguredBaseModel):
    """
    Money as integer minor units with an ISO 4217 currency.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/value',
         'rules': [{'description': 'A value that is not known has no payload.',
                    'postconditions': {'slot_conditions': {'minor_units': {'name': 'minor_units',
                                                                           'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                    'none_of': [{'equals_string': 'known'}]}}}},
                   {'description': 'A known value has no reason, except the core code '
                                   'added_later.',
                    'postconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                     'none_of': [{'equals_string': 'known'}]}}},
                    'preconditions': {'slot_conditions': {'reason': {'name': 'reason',
                                                                     'none_of': [{'equals_string': 'added_later'}],
                                                                     'value_presence': 'PRESENT'}}}}]})

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })
    minor_units: Optional[int] = Field(default=None, description="""Integer minor units; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'Quantity']} })
    currency: str = Field(default=..., description="""ISO 4217 currency code.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount']} })
    state: ValueState = Field(default=..., description="""State of the amount.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'UndecidedRow']} })

    @field_validator('reason')
    def pattern_reason(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid reason format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid reason format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('currency')
    def pattern_currency(cls, v):
        pattern=re.compile(r"^[A-Z]{3}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid currency format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid currency format: {v}"
            raise ValueError(err_msg)
        return v


class Quantity(ConfiguredBaseModel):
    """
    A measured quantity as integer minor units with a UCUM unit.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/value',
         'rules': [{'description': 'A value that is not known has no payload.',
                    'postconditions': {'slot_conditions': {'minor_units': {'name': 'minor_units',
                                                                           'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                    'none_of': [{'equals_string': 'known'}]}}}},
                   {'description': 'A known value has no reason, except the core code '
                                   'added_later.',
                    'postconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                     'none_of': [{'equals_string': 'known'}]}}},
                    'preconditions': {'slot_conditions': {'reason': {'name': 'reason',
                                                                     'none_of': [{'equals_string': 'added_later'}],
                                                                     'value_presence': 'PRESENT'}}}}]})

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })
    minor_units: Optional[int] = Field(default=None, description="""Integer minor units; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'Quantity']} })
    scale: Optional[int] = Field(default=None, description="""Number of decimals in minor_units: kg with scale 0, g with scale 3.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Quantity']} })
    unit: str = Field(default=..., description="""UCUM unit.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Quantity']} })
    state: ValueState = Field(default=..., description="""State of the quantity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'UndecidedRow']} })

    @field_validator('reason')
    def pattern_reason(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid reason format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid reason format: {v}"
            raise ValueError(err_msg)
        return v


class Ratio(ConfiguredBaseModel):
    """
    An exact fraction in canonical form (positive denominator, gcd 1).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/value',
         'rules': [{'description': 'A value that is not known has no payload.',
                    'postconditions': {'slot_conditions': {'numerator': {'name': 'numerator',
                                                                         'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                    'none_of': [{'equals_string': 'known'}]}}}},
                   {'description': 'A value that is not known has no denominator '
                                   'either.',
                    'postconditions': {'slot_conditions': {'denominator': {'name': 'denominator',
                                                                           'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                    'none_of': [{'equals_string': 'known'}]}}}},
                   {'description': 'A known value has no reason, except the core code '
                                   'added_later.',
                    'postconditions': {'slot_conditions': {'state': {'name': 'state',
                                                                     'none_of': [{'equals_string': 'known'}]}}},
                    'preconditions': {'slot_conditions': {'reason': {'name': 'reason',
                                                                     'none_of': [{'equals_string': 'added_later'}],
                                                                     'value_presence': 'PRESENT'}}}}]})

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })
    numerator: Optional[int] = Field(default=None, description="""Numerator; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ratio']} })
    denominator: Optional[int] = Field(default=None, description="""Denominator of at least 1; absent unless state is known.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Ratio']} })
    state: ValueState = Field(default=..., description="""State of the ratio.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'UndecidedRow']} })

    @field_validator('reason')
    def pattern_reason(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid reason format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid reason format: {v}"
            raise ValueError(err_msg)
        return v


class SourceSidecar(ConfiguredBaseModel):
    """
    A facts/<file>.sources.yaml companion. Exact rows take precedence over a cell, record or file default. The canonical writer emits rows only; record selectors remain compatible with ingested sidecars.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source', 'tree_root': True})

    default: Optional[Source] = Field(default=None, description="""The fallback source for every record in the fact file.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSidecar']} })
    records: Optional[list[SourceRecord]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSidecar']} })
    rows: Optional[list[SourceEntry]] = Field(default=None, description="""Exact RowRefs with complete sources; keys must be canonical and actually occur in the companion fact file.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSidecar', 'AnswerCounts']} })


class SourceSelector(ConfiguredBaseModel):
    """
    A record, or one cell of it, using the fact file's typed kind and identifier.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'SourceRecord',
                       'Source',
                       'ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise']} })
    id: Union[int, str] = Field(default=..., description="""The identifier in the root kind's SQL type; a boolean is never an integer identifier.""", json_schema_extra = { "linkml_meta": {'any_of': [{'range': 'string'}, {'range': 'integer'}],
         'domain_of': ['SourceSelector',
                       'ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef']} })
    slot: Optional[str] = Field(default=None, description="""When present, a slot of this kind, including inherited slots.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector', 'SweepCellRef']} })

    @field_validator('kind')
    def pattern_kind(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid kind format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid kind format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('slot')
    def pattern_slot(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid slot format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid slot format: {v}"
            raise ValueError(err_msg)
        return v


class SourceRecord(ConfiguredBaseModel):
    """
    One compatible record/cell override. Missing source fields inherit the file default; the merged source must satisfy Source, including its kind's required revision. Duplicate selectors union sources.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source'})

    of: SourceSelector = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord']} })
    kind: Optional[SourceKind] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'SourceRecord',
                       'Source',
                       'ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise']} })
    name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source', 'BoundSweep', 'SweepCheck']} })
    revision: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    position: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate', 'SourceRecord', 'Source', 'AnswerStep']} })
    url: Optional[str] = Field(default=None, description="""Absolute HTTP(S) document or API/resource URL; a locator, never fetched by contract validation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    retrieved_at: Optional[datetime ] = Field(default=None, description="""When the document bytes were retrieved; required for a document without a version. This is not an observation's event_time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    fragment_sha256: Optional[str] = Field(default=None, description="""SHA-256 of the exact UTF-8 bytes of the cited short fragment; no fragment text is stored in this contract.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    ownership: Optional[SourceOwnership] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    licence: Optional[str] = Field(default=None, description="""The declared SPDX id, LicenseRef or licence file in the pack, verified by the importer; validation makes no claim about legal permission.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    attribution: Optional[str] = Field(default=None, description="""The required name/credit for the third-party source.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    reason: Optional[str] = Field(default=None, description="""Message key explaining why this row remains a fact instead of being derived.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })

    @field_validator('url')
    def pattern_url(cls, v):
        pattern=re.compile(r"^https?://[^\s/?#]+([/?#][^\s]*)?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid url format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid url format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('fragment_sha256')
    def pattern_fragment_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid fragment_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid fragment_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('licence')
    def pattern_licence(cls, v):
        pattern=re.compile(r"^\S(.*\S)?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid licence format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid licence format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('attribution')
    def pattern_attribution(cls, v):
        pattern=re.compile(r"^\S(.*\S)?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid attribution format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid attribution format: {v}"
            raise ValueError(err_msg)
        return v


class Source(ConfiguredBaseModel):
    """
    A repository, file, proposal, query, tool or register and a location within it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source',
         'rules': [{'postconditions': {'slot_conditions': {'revision': {'name': 'revision',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'git',
                                                                   'name': 'kind'}}}},
                   {'postconditions': {'slot_conditions': {'revision': {'name': 'revision',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'proposal',
                                                                   'name': 'kind'}}}},
                   {'postconditions': {'any_of': [{'slot_conditions': {'revision': {'name': 'revision',
                                                                                    'pattern': '^\\S(.*\\S)?$',
                                                                                    'required': True}}},
                                                  {'slot_conditions': {'retrieved_at': {'name': 'retrieved_at',
                                                                                        'required': True}}}],
                                       'slot_conditions': {'attribution': {'name': 'attribution',
                                                                           'required': True},
                                                           'fragment_sha256': {'name': 'fragment_sha256',
                                                                               'required': True},
                                                           'licence': {'name': 'licence',
                                                                       'required': True},
                                                           'position': {'name': 'position',
                                                                        'pattern': '^\\S(.*\\S)?$'},
                                                           'url': {'name': 'url',
                                                                   'required': True}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'document',
                                                                   'name': 'kind'}}}},
                   {'postconditions': {'slot_conditions': {'revision': {'name': 'revision',
                                                                        'pattern': '^\\S(.*\\S)?$'}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'document',
                                                                   'name': 'kind'},
                                                          'revision': {'name': 'revision',
                                                                       'value_presence': 'PRESENT'}}}},
                   {'postconditions': {'slot_conditions': {'attribution': {'name': 'attribution',
                                                                           'required': True},
                                                           'licence': {'name': 'licence',
                                                                       'required': True}}},
                    'preconditions': {'slot_conditions': {'ownership': {'equals_string': 'third_party',
                                                                        'name': 'ownership'}}}}]})

    kind: SourceKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'SourceRecord',
                       'Source',
                       'ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise']} })
    name: str = Field(default=..., description="""The repository, file, proposal, query, tool or register.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source', 'BoundSweep', 'SweepCheck']} })
    revision: Optional[str] = Field(default=None, description="""The pinned revision: required for a Git commit or a proposal manifest; a document version or a query's API/schema version when supplied.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    position: str = Field(default=..., description="""Where in the source: Git path#section or path#L12-L24, a document section/paragraph anchor, a query's resource version or date, a JSON pointer, line, row and column, offset or delta step. Existing locators stay valid.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate', 'SourceRecord', 'Source', 'AnswerStep']} })
    url: Optional[str] = Field(default=None, description="""Absolute HTTP(S) document or API/resource URL; a locator, never fetched by contract validation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    retrieved_at: Optional[datetime ] = Field(default=None, description="""When the document bytes were retrieved; required for a document without a version. This is not an observation's event_time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    fragment_sha256: Optional[str] = Field(default=None, description="""SHA-256 of the exact UTF-8 bytes of the cited short fragment; no fragment text is stored in this contract.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    ownership: Optional[SourceOwnership] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    licence: Optional[str] = Field(default=None, description="""The declared SPDX id, LicenseRef or licence file in the pack, verified by the importer; validation makes no claim about legal permission.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    attribution: Optional[str] = Field(default=None, description="""The required name/credit for the third-party source.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })

    @field_validator('url')
    def pattern_url(cls, v):
        pattern=re.compile(r"^https?://[^\s/?#]+([/?#][^\s]*)?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid url format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid url format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('fragment_sha256')
    def pattern_fragment_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid fragment_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid fragment_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('licence')
    def pattern_licence(cls, v):
        pattern=re.compile(r"^\S(.*\S)?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid licence format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid licence format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('attribution')
    def pattern_attribution(cls, v):
        pattern=re.compile(r"^\S(.*\S)?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid attribution format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid attribution format: {v}"
            raise ValueError(err_msg)
        return v


class SourceEntry(ConfiguredBaseModel):
    """
    The sources of one base row, using the row identity shared with proofs.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source'})

    row: RowRef = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Premise', 'SourceEntry']} })
    sources: list[Source] = Field(default=..., description="""Every source of the row; a writer sorts and deduplicates them.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceEntry', 'AnswerNode']} })
    reason: Optional[str] = Field(default=None, description="""Message key explaining why this row remains a fact instead of being derived (S29).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })


class SourceSet(ConfiguredBaseModel):
    """
    The manifest's reference to a role's file of source entries.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source'})

    role: str = Field(default=..., description="""The role whose base rows the entries describe.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSet']} })
    uri: str = Field(default=..., description="""The location of the source-entry file.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSet']} })
    sha256: str = Field(default=..., description="""SHA-256 of the source-entry file bytes.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSet']} })

    @field_validator('sha256')
    def pattern_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid sha256 format: {v}"
            raise ValueError(err_msg)
        return v


class Question(ConfiguredBaseModel):
    """
    One explanation question, as the schema bundle carries it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    term: str = Field(default=..., description="""The name in code; its label is the message explain.<term>, its sentence explain.<term>.question.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question']} })
    start: QuestionStart = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer']} })
    applies_to: Optional[AppliesTo] = Field(default=None, description="""Absent means every value the start allows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question']} })
    steps: list[Step] = Field(default=..., description="""In order: the rows a step ends on are the start of the next.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'Question', 'Answer']} })
    answer: AnswerShape = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Question']} })
    limit: int = Field(default=..., description="""Nodes per page; the profile caps it.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Question']} })

    @field_validator('term')
    def pattern_term(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid term format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid term format: {v}"
            raise ValueError(err_msg)
        return v


class ReaderQuestion(ConfiguredBaseModel):
    """
    A reader question (RV-C04; docs/gui.md, \"Reader questions\"): a question in the reader's words whose answer is the role's rows of one derived relation, each with a link to its proof. Written in questions.yaml under `reader:`; the compiler checks every name and resolves the proof. The viewer and the REPL offer it to a role that reads the relation in full or reads a row of it, and read the rows and the proof from the gate's rows and ask routes.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    id: str = Field(default=..., description="""Kebab case: the page's address and the REPL name; once in the import closure.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef']} })
    title_message: str = Field(default=..., description="""Message id of the question as the reader asks it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion']} })
    about_message: str = Field(default=..., description="""Message id of one sentence: what the answer holds.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion']} })
    relation: str = Field(default=..., description="""A derived relation of the pack.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    proof: str = Field(default=..., description="""The term of the question that opens a row's proof: the one written, or the first a row of the relation offers in bundle order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion']} })
    columns: list[ReaderColumn] = Field(default=..., description="""The columns shown, in order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion']} })
    context: Optional[list[ReaderContext]] = Field(default=None, description="""Shown above the answer, such as a reference date and a window. Absent: none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('proof')
    def pattern_proof(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid proof format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid proof format: {v}"
            raise ValueError(err_msg)
        return v


class ReaderColumn(ConfiguredBaseModel):
    """
    A column of a reader question's relation, as it is shown.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    column: str = Field(default=..., description="""The relation's column.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn']} })
    message: str = Field(default=..., description="""Message id of its heading.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn']} })
    element: Optional[str] = Field(default=None, description="""A kind: the column is text and holds an id of that kind, shown by its name. Absent: the value is never looked up.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep', 'ReaderColumn']} })
    reading: Optional[DayReading] = Field(default=None, description="""The column is a whole number that is no amount, read as a day, shown as a date; a value that is no calendar day is shown as the number. Until a column carries a date type (M3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'ReaderField']} })


class ReaderContext(ConfiguredBaseModel):
    """
    The role's rows of a kind, with fields of its page, as a Cards part names them. The compiled form: questions.yaml writes `fields` as a list of `<kind>.<slot>`, as a Cards part does, with a map `readings` beside it from a field to its reading; the compiler writes each field with its reading here.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'SourceRecord',
                       'Source',
                       'ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise']} })
    fields: list[ReaderField] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext']} })


class ReaderField(ConfiguredBaseModel):
    """
    A slot of the context kind's page, by element id.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    field: str = Field(default=..., description="""`<kind>.<slot>`; its label is the slot's label.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderField']} })
    reading: Optional[DayReading] = Field(default=None, description="""As on a column: a whole number read as a day.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'ReaderField']} })


class AppliesTo(ConfiguredBaseModel):
    """
    The values a question is offered for.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    derivation: Optional[QuestionDerivation] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo']} })
    kinds: Optional[list[str]] = Field(default=None, description="""Kind ids.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter']} })
    relations: Optional[list[str]] = Field(default=None, description="""Relation names.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter']} })


class Step(ConfiguredBaseModel):
    """
    One building block; exactly one of trace and suppose.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    trace: Optional[Trace] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Step']} })
    suppose: Optional[Suppose] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Step']} })


class Trace(ConfiguredBaseModel):
    """
    A walk through the proof, with a direction, a depth and filters.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    direction: Direction = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Trace']} })
    depth: str = Field(default=..., description="""A whole number from 1 as decimal text, or all.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Trace']} })
    through: Optional[Through] = Field(default=None, description="""Absent: proof.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Trace']} })
    keep: Optional[Filter] = Field(default=None, description="""The nodes the answer shows; the walk goes on through the others.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Trace']} })
    stop: Optional[Filter] = Field(default=None, description="""Nodes the walk reaches but does not go past.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Trace']} })
    fanout: Optional[int] = Field(default=None, description="""With through: rules, the branches per literal.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Trace']} })

    @field_validator('depth')
    def pattern_depth(cls, v):
        pattern=re.compile(r"^(all|[1-9][0-9]*)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid depth format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid depth format: {v}"
            raise ValueError(err_msg)
        return v


class Filter(ConfiguredBaseModel):
    """
    Names that select nodes; a node matches if it matches any of them.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    kinds: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter']} })
    relations: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter']} })
    rules: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Filter']} })
    layers: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Filter']} })


class Suppose(ConfiguredBaseModel):
    """
    A counterfactual step; exactly one of delta and over.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    delta: Optional[SupposeDelta] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose', 'Answer']} })
    over: Optional[str] = Field(default=None, description="""A sweep of the pack (sweeps.yaml), each variant in turn.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose']} })


class Answer(ConfiguredBaseModel):
    """
    One page of the answer to a question (rede.answer/1), from GET /<pack>/<manifest>/ask/<term> for one role. The nodes are in a fixed order, by distance, then by reference (relation, then key, both by their UTF-8 bytes), at most the limit of the question. A walk expands a level only while the levels before it are within the limit; where it stops before its depth, the nodes of its last level are continuations (more).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain',
         'rules': [{'description': 'An ask ... where answer carries its output schema '
                                   'id and its counts together.',
                    'postconditions': {'slot_conditions': {'counts': {'name': 'counts',
                                                                      'required': True}}},
                    'preconditions': {'slot_conditions': {'output_schema': {'name': 'output_schema',
                                                                            'value_presence': 'PRESENT'}}}},
                   {'postconditions': {'slot_conditions': {'output_schema': {'name': 'output_schema',
                                                                             'required': True}}},
                    'preconditions': {'slot_conditions': {'counts': {'name': 'counts',
                                                                     'value_presence': 'PRESENT'}}}},
                   {'description': 'Only a computed answer says that it could not be '
                                   'computed.',
                    'postconditions': {'slot_conditions': {'computed': {'name': 'computed',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'not_computed': {'name': 'not_computed',
                                                                           'value_presence': 'PRESENT'}}}},
                   {'description': 'Undecided rows belong to an ask ... where answer, '
                                   'which says how many there are in all.',
                    'postconditions': {'slot_conditions': {'counts': {'name': 'counts',
                                                                      'required': True}}},
                    'preconditions': {'slot_conditions': {'undecided': {'name': 'undecided',
                                                                        'value_presence': 'PRESENT'}}}}]})

    format: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    question: str = Field(default=..., description="""The term asked.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    manifest_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Proof', 'Answer', 'BoundSweepList']} })
    start: Optional[RowRef] = Field(default=None, description="""The row the question starts from; absent for a delta or a sweep (delta).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer']} })
    delta: Optional[DeltaStart] = Field(default=None, description="""The delta or sweep the question starts from; absent for a row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose', 'Answer']} })
    nodes: list[AnswerNode] = Field(default=..., description="""The nodes on this page; the start, at distance 0, on the first.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    steps: Optional[list[AnswerStep]] = Field(default=None, description="""The edges that reach a node on this page, from a node the answer shows (on this page or an earlier one); by conclusion, how, position and premise.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'Question', 'Answer']} })
    witnesses: Optional[list[Witness]] = Field(default=None, description="""The chosen witness of each conclusion on this page, in page order: the captions.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof', 'Answer']} })
    calc_witnesses: Optional[list[CalcWitness]] = Field(default=None, description="""The witness of each calculated row on this page, in page order (decision W12): its version, definition and steps, unchanged. Each premise is also an edge of the answer (positive, at its index in premises); absent when the page has none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof', 'Answer']} })
    next: Optional[str] = Field(default=None, description="""The cursor of the next page, <distance>,<relation>,<key> (the query parameter after); absent on the last page.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    more: Optional[list[RowRef]] = Field(default=None, description="""The nodes on this page where the walk stopped before its depth, to stay within the limit: each continues with the same question from that node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'GapPremise']} })
    gap: Optional[GapAnswer] = Field(default=None, description="""For a question through the rules (gap): the failing premises and the candidates.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    difference: Optional[Difference] = Field(default=None, description="""For a question from a delta: the counts, and after suppose alone the page of changed rows (its nodes, at distance 0).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    series: Optional[list[SeriesCell]] = Field(default=None, description="""For a question from a sweep: one cell per grid value, in grid order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    output_schema: Optional[str] = Field(default=None, description="""For an ask ... where: the id of its output schema (P10.2a §8a, Reckon Data L0 §7.1), the answer dataset's $schema, so a client gets types without guessing.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    counts: Optional[AnswerCounts] = Field(default=None, description="""For an ask ... where: the counts of the whole answer, not of this page (P10.2a §7a rule 4).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Difference', 'SeriesCell']} })
    complete: Optional[bool] = Field(default=None, description="""For impact: true when every changed row the role reads has a ring and no relation of the difference is read in part (docs/interaction.md section 3); it counts nothing the role does not read.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    incomplete: Optional[list[Incompleteness]] = Field(default=None, description="""For impact, when not complete: why, in the order depth, budget, not_read_in_full.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    undecided: Optional[list[UndecidedRow]] = Field(default=None, description="""For an ask ... where: the binder rows on this page whose condition is unknown or invalid, in canonical key order. An answer never drops them (S1 §3.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'AnswerCounts']} })
    expression: Optional[AnswerExpression] = Field(default=None, description="""For an ask ... where (POST /<pack>/<manifest>/ask, RV-S16): the question asked, which has no term of the bundle; question is then ask.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    diagnostics: Optional[list[ReckonDiagnostic]] = Field(default=None, description="""For an ask ... where: the warnings of the check, in source order. A text with an error gets no answer (400, with its diagnostics).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    dataset: Optional[Any] = Field(default=None, description="""For an ask ... where: this page as a Reckon Data dataset (P10.2a §8a; docs/reckon-data/l0.md): the members $schema, schema and rows, the Answer rows of the page and then its Undecided rows, as Row JSON. Its $schema equals output_schema.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    computed: Optional[bool] = Field(default=None, description="""True on a computed answer (contrast, consequence): derived by Rede, not quoted, and shown as computed (docs/explain/contract.md, rule 5). Absent on the others.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    not_computed: Optional[str] = Field(default=None, description="""A computed answer that could not be computed, with its reason code (for consequence: no_variant, no published variant withdraws the start fact alone). The answer then holds its start alone; missing is never an empty answer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })

    @field_validator('format')
    def pattern_format(cls, v):
        pattern=re.compile(r"^rede\.answer/1$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid format format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid format format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('question')
    def pattern_question(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid question format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid question format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('output_schema')
    def pattern_output_schema(cls, v):
        pattern=re.compile(r"^s-[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid output_schema format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid output_schema format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('not_computed')
    def pattern_not_computed(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid not_computed format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid not_computed format: {v}"
            raise ValueError(err_msg)
        return v


class AnswerExpression(ConfiguredBaseModel):
    """
    The question of an ask ... where answer (P10.2a §9).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    hash: str = Field(default=..., description="""The sha256 of the question's canonical JSON form.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerExpression']} })
    text: str = Field(default=..., description="""The question in its normal form, as the printer writes it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerExpression']} })

    @field_validator('hash')
    def pattern_hash(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid hash format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid hash format: {v}"
            raise ValueError(err_msg)
        return v


class ReckonDiagnostic(ConfiguredBaseModel):
    """
    A diagnostic of the check of a Reckon text (docs/reckon/expressions.md §8b), by code; its sentence is in the message catalogue.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    code: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic']} })
    span: Optional[Any] = Field(default=None, description="""Its place in the text: {text, start, end}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic']} })
    args: Optional[list[str]] = Field(default=None, description="""The values its sentence needs.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic']} })
    hint: Optional[Any] = Field(default=None, description="""What to write instead: a sentence by its id, with its values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic']} })
    suggest: Optional[list[str]] = Field(default=None, description="""The names it may have meant, nearest first.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic']} })


class AnswerCounts(ConfiguredBaseModel):
    """
    The counts of an ask ... where answer over all its pages (P10.2a §8a): rows where the condition is true, undecided rows, and rows left out because the condition is not_applicable there. Missing is never zero: each count is given.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    rows: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSidecar', 'AnswerCounts']} })
    undecided: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'AnswerCounts']} })
    not_applicable: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerCounts']} })


class UndecidedRow(ConfiguredBaseModel):
    """
    A binder row whose condition the answer cannot decide (S1 §3.3, P10.2a §8a, cases E42, E43). In the answer dataset it is an Undecided row; its cause there is cause_relation and cause_key, both \"\" where cause is absent here.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    binder: str = Field(default=..., description="""The binder row's id, its key in the answer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow']} })
    state: UndecidedState = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'UndecidedRow']} })
    reason: Optional[str] = Field(default=None, description="""A reason code (S1 §2.3: the least code, A.4); left out when there is none, never free text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry',
                       'UndecidedRow']} })
    cause: Optional[RowRef] = Field(default=None, description="""The row that holds, or for a missing value would hold, the value the condition depends on; its key is canonical key text, as in the snapshots. Absent for a state written as a constant.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow']} })

    @field_validator('reason')
    def pattern_reason(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid reason format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid reason format: {v}"
            raise ValueError(err_msg)
        return v


class DeltaStart(ConfiguredBaseModel):
    """
    The delta a question starts from.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    kind: DeltaKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'SourceRecord',
                       'Source',
                       'ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise']} })
    id: str = Field(default=..., description="""The proposal id, the variant's manifest id or the sweep's name, as asked; for a supposition, the sha256 of its delta.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef']} })
    manifest: Optional[str] = Field(default=None, description="""The target manifest (a proposal or variant); absent for a sweep and for a supposition, which has none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DeltaStart', 'SeriesCell', 'BoundSweepCell']} })


class Difference(ConfiguredBaseModel):
    """
    What a delta changed in what the role reads (rede.explain-index/1, docs/gui.md \"suppose in profile edge\"), in its own order: by relation, then by key element by element. A page holds at most the limit of entries; the cursor (next) is 0,<relation>,<key>.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    counts: list[RelationCount] = Field(default=..., description="""Per changed relation, by relation; none for a relation that did not change.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Difference', 'SeriesCell']} })
    entries: Optional[list[DifferenceEntry]] = Field(default=None, description="""The changed rows on this page.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Difference']} })


class RelationCount(ConfiguredBaseModel):
    """
    The changes of one relation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    relation: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    added: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['RelationCount']} })
    removed: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['RelationCount']} })
    changed: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['RelationCount']} })


class DifferenceEntry(ConfiguredBaseModel):
    """
    One changed row; keys are canonical key text, as in the snapshots.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    relation: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    key: str = Field(default=..., description="""The row in the target (added, changed) or in the base (removed).""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef', 'DifferenceEntry', 'AnswerNode', 'GapCandidate']} })
    change: DifferenceChange = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry', 'AnswerNode', 'GapCandidate']} })
    was: Optional[str] = Field(default=None, description="""For changed: the row in the base.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry', 'AnswerNode']} })


class SeriesCell(ConfiguredBaseModel):
    """
    One grid value of a sweep, with the counts of its variant's difference where one was published.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    index: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'GapPremise']} })
    value: str = Field(default=..., description="""The value as decimal text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep']} })
    status: SeriesStatus = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'SweepCheck', 'GapCandidate']} })
    manifest: Optional[str] = Field(default=None, description="""The variant's manifest, if it is green or warning.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DeltaStart', 'SeriesCell', 'BoundSweepCell']} })
    diagnosis: Optional[str] = Field(default=None, description="""The variant's diagnosis, if it is red.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell']} })
    counts: Optional[list[RelationCount]] = Field(default=None, description="""The counts of its difference for the role; absent where none was published.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Difference', 'SeriesCell']} })


class BoundSweepList(ConfiguredBaseModel):
    """
    The opt-in GET /<pack>/sweeps?m=<main> response for one verified role, bound to exactly manifest_id. A stale main, missing grid or unreadable swept cell gives the same generic 404; the gate never substitutes a newer main. The route without m keeps its legacy array.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    manifest_id: str = Field(default=..., description="""The exact selected main manifest, checked before grid or variant metadata is read.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof', 'Answer', 'BoundSweepList']} })
    sweeps: list[BoundSweep] = Field(default=..., description="""The current pack contract allows one sweep; only a sweep whose cell the role reads appears.""", min_length=1, max_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweepList']} })


class BoundSweep(ConfiguredBaseModel):
    """
    A published grid and its actual swept fact-cell identity, not a fabricated proof row.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source', 'BoundSweep', 'SweepCheck']} })
    cell: SweepCellRef = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })
    min: str = Field(default=..., description="""Exact whole-number decimal text, including values beyond JavaScript's safe integer range.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })
    max: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })
    step: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })
    cells: list[BoundSweepCell] = Field(default=..., description="""The complete fixed grid in index order; no interpolation or computed intermediate values.""", min_length=1, max_length=64, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('min')
    def pattern_min(cls, v):
        pattern=re.compile(r"^(0|-?[1-9][0-9]*)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid min format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid min format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('max')
    def pattern_max(cls, v):
        pattern=re.compile(r"^(0|-?[1-9][0-9]*)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid max format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid max format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('step')
    def pattern_step(cls, v):
        pattern=re.compile(r"^[1-9][0-9]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid step format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid step format: {v}"
            raise ValueError(err_msg)
        return v


class SweepCellRef(ConfiguredBaseModel):
    """
    The fact cell named by the verified published grid: its kind, the element's identifier and its slot. This identifier triple is not an engine RowRef with an invented value key. It grants no access; the listing is filtered with the selected manifest and verified role.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'SourceRecord',
                       'Source',
                       'ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise']} })
    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef']} })
    slot: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector', 'SweepCellRef']} })


class BoundSweepCell(ConfiguredBaseModel):
    """
    One public grid sample. Only a green or warning sample may carry the already published, role-checked variant manifest. Red has checks but no diagnosis reference here; unavailable and not_computed carry no variant reference or counts. Missing information is never zero.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain',
         'rules': [{'postconditions': {'slot_conditions': {'manifest': {'name': 'manifest',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'status': {'equals_string': 'green',
                                                                     'name': 'status'}}}},
                   {'postconditions': {'slot_conditions': {'manifest': {'name': 'manifest',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'status': {'equals_string': 'warning',
                                                                     'name': 'status'}}}},
                   {'postconditions': {'slot_conditions': {'manifest': {'name': 'manifest',
                                                                        'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'status': {'equals_string': 'red',
                                                                     'name': 'status'}}}},
                   {'postconditions': {'slot_conditions': {'manifest': {'name': 'manifest',
                                                                        'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'status': {'equals_string': 'unavailable',
                                                                     'name': 'status'}}}},
                   {'postconditions': {'slot_conditions': {'manifest': {'name': 'manifest',
                                                                        'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'status': {'equals_string': 'not_computed',
                                                                     'name': 'status'}}}}]})

    index: int = Field(default=..., ge=0, le=63, json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'GapPremise']} })
    value: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep']} })
    status: SeriesStatus = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'SweepCheck', 'GapCandidate']} })
    checks: Optional[list[SweepCheck]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweepCell']} })
    manifest: Optional[str] = Field(default=None, description="""An already published variant manifest, only with green or warning status; never a guessed id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DeltaStart', 'SeriesCell', 'BoundSweepCell']} })

    @field_validator('value')
    def pattern_value(cls, v):
        pattern=re.compile(r"^(0|-?[1-9][0-9]*)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid value format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid value format: {v}"
            raise ValueError(err_msg)
        return v


class SweepCheck(ConfiguredBaseModel):
    """
    A public check's name and status; never a violation count or a private reader list.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source', 'BoundSweep', 'SweepCheck']} })
    status: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'SweepCheck', 'GapCandidate']} })

    @field_validator('status')
    def pattern_status(cls, v):
        pattern=re.compile(r"^(green|warning|red|unavailable)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid status format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid status format: {v}"
            raise ValueError(err_msg)
        return v


class AnswerNode(ConfiguredBaseModel):
    """
    One node of an answer, a row, with its distance from the start; or an anonymous node (outside), where the question needs what the role may not read: no relation, no key, no address. For gap, a key's free column is null.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    relation: Optional[str] = Field(default=None, description="""Absent on an anonymous node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    key: Optional[str] = Field(default=None, description="""Canonical key text, as in the snapshots; absent on an anonymous node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef', 'DifferenceEntry', 'AnswerNode', 'GapCandidate']} })
    distance: int = Field(default=..., description="""The number of steps from the start, which is 0.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'GapPremise']} })
    outside: Optional[bool] = Field(default=None, description="""An anonymous node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'GapPremise']} })
    change: Optional[NodeChange] = Field(default=None, description="""For impact: what the delta did to this row for the role; every node of an impact answer has one.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry', 'AnswerNode', 'GapCandidate']} })
    was: Optional[str] = Field(default=None, description="""For impact, a changed cell: its row in the base, as canonical key text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry', 'AnswerNode']} })
    sources: Optional[list[Source]] = Field(default=None, description="""A base row's sources (S25), from the role's own source set and by today's rights, as the publisher sorted them: where a walk back ends. Absent on a conclusion, and on every node of a manifest without source sets. A locator, not proof that the row is true.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceEntry', 'AnswerNode']} })


class GapAnswer(ConfiguredBaseModel):
    """
    What is missing for an absent start (docs/gui.md, \"gap\"), in the walk's order.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    premises: list[GapPremise] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness', 'GapAnswer']} })
    candidates: Optional[list[GapCandidate]] = Field(default=None, description="""Changes to base rows that answer a failing premise.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapAnswer']} })
    cut: bool = Field(default=..., description="""Premises were left out to stay within the limit.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapAnswer']} })
    closed_by: Optional[list[RowRef]] = Field(default=None, description="""For contrast: the role's rows of every relation that closes the start's relation (DerivedRelation.closes, decision W14) whose key is a prefix of the start's key, by relation, then key. Each states that no row holds there, and its grounds say why. Absent: no closing row the role reads matches, and the answer says only what lacks support (open world); a role that does not read a closing relation gets no hint whether one exists.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapAnswer']} })


class GapPremise(ConfiguredBaseModel):
    """
    The first item of a rule's schedule without a match, for one branch of the bindings.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    distance: int = Field(default=..., description="""The level of the start it fails for.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'GapPremise']} })
    node: RowRef = Field(default=..., description="""That start (a free column is null).""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise']} })
    rule: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'GapPremise']} })
    item: int = Field(default=..., description="""The item's place in the rule's schedule.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise']} })
    kind: GapItem = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSelector',
                       'SourceRecord',
                       'Source',
                       'ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise']} })
    index: int = Field(default=..., description="""Its place among the rule's items of that kind (the body for a literal).""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'GapPremise']} })
    relation: Optional[str] = Field(default=None, description="""The relation a literal or an aggregate reads.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    bindings: Optional[list[Binding]] = Field(default=None, description="""The variables bound before it, by name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'GapPremise']} })
    outside: Optional[bool] = Field(default=None, description="""Over a relation the role does not read in full: nothing more is said.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'GapPremise']} })
    more: Optional[bool] = Field(default=None, description="""A literal before it had more matches than the fanout; the others were not followed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'GapPremise']} })
    overflow: Optional[bool] = Field(default=None, description="""An assignment or a sum whose operand or result lies outside BIGINT: every engine stops there, so no change makes it hold.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise']} })


class GapCandidate(ConfiguredBaseModel):
    """
    A change to one base row that answers a failing premise.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    change: Change = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry', 'AnswerNode', 'GapCandidate']} })
    relation: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef',
                       'Aggregate',
                       'CalcStep',
                       'ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate']} })
    key: str = Field(default=..., description="""Canonical key text of the row's key columns; a column the user still chooses is null.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef', 'DifferenceEntry', 'AnswerNode', 'GapCandidate']} })
    status: CandidateStatus = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'SweepCheck', 'GapCandidate']} })
    premise: int = Field(default=..., description="""The premise it answers, by its place in premises.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['GapCandidate', 'AnswerStep']} })


class AnswerStep(ConfiguredBaseModel):
    """
    One edge of the role's proof graph (the relation step), between nodes of an answer.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    conclusion: RowRef = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness', 'AnswerStep']} })
    premise: RowRef = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GapCandidate', 'AnswerStep']} })
    how: StepHow = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep']} })
    position: int = Field(default=..., description="""The premise's place in the rule body, or for contributes the aggregate's place in the rule.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate', 'SourceRecord', 'Source', 'AnswerStep']} })
    value: Optional[str] = Field(default=None, description="""On a contributes step of a sum, min or max: what the premise's row contributes, the canonical text of its value with its state, as the witness's contributors_sha256 is taken over it (RV-C09). Absent on every other step, and where the published proof pieces state none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep']} })

    @field_validator('value')
    def pattern_value(cls, v):
        pattern=re.compile(r"^(known:.*|unknown|not_applicable|invalid)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid value format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid value format: {v}"
            raise ValueError(err_msg)
        return v


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
RowRef.model_rebuild()
Premise.model_rebuild()
Aggregate.model_rebuild()
Witness.model_rebuild()
Binding.model_rebuild()
CalcStep.model_rebuild()
CalcWitness.model_rebuild()
Proof.model_rebuild()
Value.model_rebuild()
Amount.model_rebuild()
Quantity.model_rebuild()
Ratio.model_rebuild()
SourceSidecar.model_rebuild()
SourceSelector.model_rebuild()
SourceRecord.model_rebuild()
Source.model_rebuild()
SourceEntry.model_rebuild()
SourceSet.model_rebuild()
Question.model_rebuild()
ReaderQuestion.model_rebuild()
ReaderColumn.model_rebuild()
ReaderContext.model_rebuild()
ReaderField.model_rebuild()
AppliesTo.model_rebuild()
Step.model_rebuild()
Trace.model_rebuild()
Filter.model_rebuild()
Suppose.model_rebuild()
Answer.model_rebuild()
AnswerExpression.model_rebuild()
ReckonDiagnostic.model_rebuild()
AnswerCounts.model_rebuild()
UndecidedRow.model_rebuild()
DeltaStart.model_rebuild()
Difference.model_rebuild()
RelationCount.model_rebuild()
DifferenceEntry.model_rebuild()
SeriesCell.model_rebuild()
BoundSweepList.model_rebuild()
BoundSweep.model_rebuild()
SweepCellRef.model_rebuild()
BoundSweepCell.model_rebuild()
SweepCheck.model_rebuild()
AnswerNode.model_rebuild()
GapAnswer.model_rebuild()
GapPremise.model_rebuild()
GapCandidate.model_rebuild()
AnswerStep.model_rebuild()
