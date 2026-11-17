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
     'description': 'What the compiler gives the viewer: the olog of one pack, its '
                    'labels and messages, its page templates and its part of the '
                    'key. The compiler writes exactly this '
                    '(bundle/schema-bundle.json); the viewer reads it only through '
                    'viewer/src/lib/contract/bundle.ts. Element ids are language '
                    'neutral: a kind (`task`), a slot (`task.project`), a key or '
                    'path equation (`task.same_project`), an enum (`task_status`) '
                    'and its values (`task_status.open`). Integers cross this '
                    'boundary as decimal text.',
     'id': 'https://rede.dev/contracts/bundle',
     'imports': ['linkml:types', 'view', 'explain'],
     'name': 'rede_bundle',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'bundle.yaml',
     'title': 'Schema bundle',
     'types': {'DecimalInteger': {'description': 'A whole number as canonical '
                                                 'decimal text, so JavaScript '
                                                 'never loses precision.',
                                  'from_schema': 'https://rede.dev/contracts/bundle',
                                  'name': 'DecimalInteger',
                                  'pattern': '^-?(0|[1-9][0-9]*)$',
                                  'typeof': 'string'}}} )

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


class Theme(str, Enum):
    """
    Display themes.
    """
    light = "light"
    dark = "dark"
    print = "print"
    forced_colors = "forced_colors"


class HouseStyleTheme(str, Enum):
    """
    The display themes a house style may give colours for. Never forced_colors: there the reader's system colours stay.
    """
    light = "light"
    dark = "dark"
    print = "print"


class Shape(str, Enum):
    """
    Node shapes.
    """
    rect = "rect"
    pill = "pill"
    ellipse = "ellipse"
    diamond = "diamond"
    bar = "bar"


class Typography(str, Enum):
    """
    Type styles that separate facts from conclusions.
    """
    upright = "upright"
    italic = "italic"


class StatusName(str, Enum):
    """
    Statuses that have a sign.
    """
    valid = "valid"
    changed = "changed"
    violated = "violated"
    unknown = "unknown"
    not_applicable = "not_applicable"
    absent = "absent"
    """
    Checked and not there: a negative premise of a proof, a row that holds by being absent from its snapshot. Never the sign of a present fact.
    """


class Tone(str, Enum):
    """
    Evaluation, distinct from nominal hue. Unknown is not a numeric rank.
    """
    positive = "positive"
    neutral = "neutral"
    caution = "caution"
    negative = "negative"
    unknown = "unknown"


class SignName(str, Enum):
    """
    The reserved signs of the epistemic legend (docs/gui.md, Reserved channels): what is known about a value, before what domain it belongs to. Each has one meaning in every pack and every theme; a pack may restyle a sign, never rename it or give it another meaning. A sign is drawn only where the bundle provides its fact.
    """
    origin_decision = "origin_decision"
    """
    A base fact whose origin is a decision: someone decided it.
    """
    origin_vendor = "origin_vendor"
    """
    A base fact whose origin is a publication of a vendor or a legislator.
    """
    origin_design = "origin_design"
    """
    A base fact whose origin is a design choice.
    """
    origin_observation = "origin_observation"
    """
    A base fact whose origin is an observation.
    """
    derived = "derived"
    """
    A conclusion of a rule, not a base fact; its text takes conclusion_typography.
    """
    assumption = "assumption"
    """
    A value taken as given until its source answers.
    """
    drift = "drift"
    """
    What Rede derives beside what a reference source says (decision R13); always two lines, never one.
    """
    screened = "screened"
    """
    Present, and not visible for the reader's role: no content and no size.
    """
    proposal = "proposal"
    """
    A proposed value: the other side of the fold.
    """
    sealed = "sealed"
    """
    Closed by a seal: it no longer changes.
    """
    supposed = "supposed"
    """
    A what-if value beside the current one it replaces.
    """


class DifferenceName(str, Enum):
    """
    What a difference does to one value, between the state a sheet shows and the state it is compared with (a proposal, a supposition, an older manifest): the published per-role difference's three changes.
    """
    added = "added"
    """
    The value is there only in the state compared with.
    """
    removed = "removed"
    """
    The value is there only in the state the sheet compares against.
    """
    changed = "changed"
    """
    The value is on both sides and differs.
    """


class SignForm(str, Enum):
    """
    How a legend sign is drawn. No form depends on colour: each is a glyph, a line pattern, a frame, a bar or a struck value, and keeps that form in the palette's system colours when colours are forced. That is its forced-colours form.
    """
    glyph = "glyph"
    """
    The sign's glyph before the value.
    """
    underline = "underline"
    """
    A line under the value, in the sign's dash.
    """
    double_line = "double_line"
    """
    Two parallel lines: the first solid, the second in the sign's dash.
    """
    bar = "bar"
    """
    A solid bar of one fixed length in the place of the value, whatever the value's length.
    """
    frame = "frame"
    """
    A frame around the value in the sign's dash, with the glyph before the value.
    """
    stamp = "stamp"
    """
    The sign's label in capitals in a frame, beside the value.
    """
    replaced = "replaced"
    """
    The old value struck through, then the new value.
    """


class Placement(str, Enum):
    top = "top"
    bottom = "bottom"
    start = "start"
    end = "end"


class BlockEdge(str, Enum):
    """
    Above or below the rest of the sheet.
    """
    top = "top"
    bottom = "bottom"


class InlineEdge(str, Enum):
    """
    Before or after the value, in reading direction.
    """
    start = "start"
    end = "end"


class CartoucheField(str, Enum):
    title = "title"
    pack = "pack"
    manifest = "manifest"
    knowledge_time = "knowledge_time"
    zoom = "zoom"


class ChannelType(str, Enum):
    """
    Free channels (docs/gui.md, Vrije kanalen). A pack's channel table gives each one a meaning; tone carries evaluation and hue a nominal category. Accent, hatching and selection are not free.
    """
    lane = "lane"
    """
    A named band or column in a fixed reading order.
    """
    ink = "ink"
    """
    Neutral lightness steps, always with a label or rank.
    """
    shape = "shape"
    """
    A shape with a kind word, small enough to tell apart.
    """
    stroke_style = "stroke_style"
    """
    A line style that stays visible in print.
    """
    size = "size"
    """
    A quantity, with scale, zero and the exact value as text.
    """
    elevation = "elevation"
    """
    Height on a relief, drawn as contour lines, with scale, zero and the exact value as text.
    """
    badge = "badge"
    """
    A sign plus a word, outside the selection outline.
    """
    weight = "weight"
    """
    Text weight; upright and italic stay reserved.
    """
    presence = "presence"
    """
    Opacity, supporting only; never for unknown, absent or screened.
    """
    tone = "tone"
    """
    Evaluation; pack bindings are not drawn yet (V1b).
    """
    hue = "hue"
    """
    Nominal category; pack bindings are not drawn yet (V1b).
    """


class ScaleLevel(str, Enum):
    """
    The level of measurement of a meaning.
    """
    nominal = "nominal"
    ordered = "ordered"
    quantitative = "quantitative"


class VerbName(str, Enum):
    """
    The six verbs a reader has on a value, the same in every pack and on every sheet (the verb bar). A verb that cannot answer for a value in its context is not shown there.
    """
    why = "why"
    """
    What the value rests on: its proof.
    """
    depends = "depends"
    """
    What depends on the value.
    """
    missing = "missing"
    """
    What is missing for the value.
    """
    suppose = "suppose"
    """
    What if: the value under a supposed change.
    """
    compare = "compare"
    """
    The value beside another state: another time, a proposal or a reference.
    """
    propose = "propose"
    """
    Propose a change of the value.
    """


class NestFlow(str, Enum):
    """
    How a container of a Nest lays out its parts: `row`, side by side; `column`, below each other.
    """
    row = "row"
    column = "column"


class FlowDirection(str, Enum):
    """
    How a Flow lays out its lanes: `down`, lanes as rows; `right`, lanes as columns.
    """
    down = "down"
    right = "right"


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


class World(str, Enum):
    """
    Decision W6.
    """
    closed = "closed"
    """
    A missing row is not true.
    """
    open = "open"
    """
    A row that is there is true; a missing row is unknown.
    """


class Layer(str, Enum):
    source = "source"
    facts = "facts"
    conclusions = "conclusions"
    plan = "plan"
    output = "output"
    observation = "observation"


class Plane(str, Enum):
    """
    Decision O13 and DV1: the plane of a kind. Only control is ever written; a data-plane kind leaves `plane` out.
    """
    control = "control"
    """
    Decided values: rows a reviewed proposal sets, each naming its decision. Admission refuses a direct delta on them.
    """


class ValueType(str, Enum):
    """
    The type of a value in the engine. Arrows carry the id type of their target.
    """
    text = "text"
    integer = "integer"
    boolean = "boolean"
    date = "date"
    enum = "enum"


class Derivation(str, Enum):
    fact = "fact"
    conclusion = "conclusion"


class SemanticCase(str, Enum):
    """
    The S3 case of a value (B09, `rede_compiler.types.Type.case`). Derived wins over money and quantity; its unit or currency stays on the type.
    """
    scalar = "scalar"
    quantity = "quantity"
    money = "money"
    date = "date"
    enum = "enum"
    ref = "ref"
    derived = "derived"


class SemanticBase(str, Enum):
    """
    What a value is stored as: a scalar, or `number` for a calculation's exact fraction.
    """
    string = "string"
    integer = "integer"
    boolean = "boolean"
    date = "date"
    number = "number"


class Check(str, Enum):
    identification = "identification"
    totality = "totality"
    functionality = "functionality"
    reference = "reference"
    value_range = "value_range"
    unique = "unique"
    path_equation = "path_equation"
    pattern = "pattern"
    cardinality = "cardinality"
    rule = "rule"


class RuleColumnType(str, Enum):
    string = "string"
    integer = "integer"


class ExplainMode(str, Enum):
    materialize = "materialize"
    on_demand = "on_demand"


class AggregateFunction(str, Enum):
    count = "count"
    sum = "sum"
    min = "min"
    max = "max"


class RuleLiteralKind(str, Enum):
    """
    What one literal of a rule body is (MOD14).
    """
    atom = "atom"
    """
    A relation read with `terms`; `negative` for `!relation(…)`.
    """
    comparison = "comparison"
    """
    `op` over its two `terms`.
    """
    assignment = "assignment"
    """
    `result` bound to `op` over its two `terms`.
    """
    aggregate = "aggregate"
    """
    `result` bound to `function` over the rows of `relation` that match `terms`.
    """


class RuleTermKind(str, Enum):
    variable = "variable"
    """
    `?name`. A `_` in a positive atom is a variable of its own (`?anon_<n>`), as in the rule IR.
    """
    constant = "constant"
    """
    Text, or a whole number as decimal text, as in the rule IR.
    """
    wildcard = "wildcard"
    """
    `_`: in an aggregate only, a column the aggregate neither groups on nor folds.
    """


class RulePolarity(str, Enum):
    positive = "positive"
    negative = "negative"
    """
    Negation as failure; only an atom.
    """


class RuleOperator(str, Enum):
    """
    The operator of a comparison (eq, ne, lt, le, gt, ge) or an assignment (add, sub, mul, div, days), as in the rule IR (contracts/rules.yaml).
    """
    eq = "eq"
    ne = "ne"
    lt = "lt"
    le = "le"
    gt = "gt"
    ge = "ge"
    add = "add"
    sub = "sub"
    mul = "mul"
    div = "div"
    days = "days"



class Question(ConfiguredBaseModel):
    """
    One explanation question, as the schema bundle carries it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    term: str = Field(default=..., description="""The name in code; its label is the message explain.<term>, its sentence explain.<term>.question.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question']} })
    start: QuestionStart = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer', 'TimelineSheet']} })
    applies_to: Optional[AppliesTo] = Field(default=None, description="""Absent means every value the start allows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question']} })
    steps: list[Step] = Field(default=..., description="""In order: the rows a step ends on are the start of the next.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer', 'CalcWitness']} })
    answer: AnswerShape = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'LensGlyph']} })
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

    id: str = Field(default=..., description="""Kebab case: the page's address and the REPL name; once in the import closure.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    title_message: str = Field(default=..., description="""Message id of the question as the reader asks it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })
    about_message: str = Field(default=..., description="""Message id of one sentence: what the answer holds.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion']} })
    relation: str = Field(default=..., description="""A derived relation of the pack.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    proof: str = Field(default=..., description="""The term of the question that opens a row's proof: the one written, or the first a row of the relation offers in bundle order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion']} })
    columns: list[ReaderColumn] = Field(default=..., description="""The columns shown, in order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion', 'MatrixSheet', 'DerivedRelation']} })
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

    column: str = Field(default=..., description="""The relation's column.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'Span']} })
    message: str = Field(default=..., description="""Message id of its heading.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'Sentence', 'Rule']} })
    element: Optional[str] = Field(default=None, description="""A kind: the column is text and holds an id of that kind, shown by its name. Absent: the value is never looked up.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'CalcStep', 'Label']} })
    reading: Optional[DayReading] = Field(default=None, description="""The column is a whole number that is no amount, read as a day, shown as a date; a value that is no calendar day is shown as the number. Until a column carries a date type (M3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'ReaderField']} })


class ReaderContext(ConfiguredBaseModel):
    """
    The role's rows of a kind, with fields of its page, as a Cards part names them. The compiled form: questions.yaml writes `fields` as a list of `<kind>.<slot>`, as a Cards part does, with a map `readings` beside it from a field to its reading; the compiler writes each field with its reading here.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    fields: list[ReaderField] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext', 'Cartouche', 'CardsPart', 'Page']} })


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

    derivation: Optional[QuestionDerivation] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Attribute']} })
    kinds: Optional[list[str]] = Field(default=None, description="""Kind ids.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Key', 'Bundle', 'Channels']} })
    relations: Optional[list[str]] = Field(default=None, description="""Relation names.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Bundle']} })


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

    direction: Direction = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Trace', 'FlowSheet']} })
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

    kinds: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Key', 'Bundle', 'Channels']} })
    relations: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Bundle']} })
    rules: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Filter', 'Bundle']} })
    layers: Optional[list[str]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Filter', 'Bundle']} })


class Suppose(ConfiguredBaseModel):
    """
    A counterfactual step; exactly one of delta and over.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    delta: Optional[SupposeDelta] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose', 'Answer']} })
    over: Optional[str] = Field(default=None, description="""A sweep of the pack (sweeps.yaml), each variant in turn.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose', 'RuleLiteral', 'RuleAggregate']} })


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

    format: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Bundle']} })
    question: str = Field(default=..., description="""The term asked.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Verb']} })
    manifest_id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'BoundSweepList', 'Proof']} })
    start: Optional[RowRef] = Field(default=None, description="""The row the question starts from; absent for a delta or a sweep (delta).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer', 'TimelineSheet']} })
    delta: Optional[DeltaStart] = Field(default=None, description="""The delta or sweep the question starts from; absent for a row.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose', 'Answer']} })
    nodes: list[AnswerNode] = Field(default=..., description="""The nodes on this page; the start, at distance 0, on the first.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'FlowSheet']} })
    steps: Optional[list[AnswerStep]] = Field(default=None, description="""The edges that reach a node on this page, from a node the answer shows (on this page or an earlier one); by conclusion, how, position and premise.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer', 'CalcWitness']} })
    witnesses: Optional[list[Witness]] = Field(default=None, description="""The chosen witness of each conclusion on this page, in page order: the captions.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Proof']} })
    calc_witnesses: Optional[list[CalcWitness]] = Field(default=None, description="""The witness of each calculated row on this page, in page order (decision W12): its version, definition and steps, unchanged. Each premise is also an edge of the answer (positive, at its index in premises); absent when the page has none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Proof']} })
    next: Optional[str] = Field(default=None, description="""The cursor of the next page, <distance>,<relation>,<key> (the query parameter after); absent on the last page.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer']} })
    more: Optional[list[RowRef]] = Field(default=None, description="""The nodes on this page where the walk stopped before its depth, to stay within the limit: each continues with the same question from that node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'GapPremise']} })
    gap: Optional[GapAnswer] = Field(default=None, description="""For a question through the rules (gap): the failing premises and the candidates.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Metrics']} })
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
    text: str = Field(default=..., description="""The question in its normal form, as the printer writes it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerExpression', 'Label']} })

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

    code: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic', 'ReasonIri']} })
    span: Optional[Any] = Field(default=None, description="""Its place in the text: {text, start, end}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })
    args: Optional[list[str]] = Field(default=None, description="""The values its sentence needs.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic', 'Sentence']} })
    hint: Optional[Any] = Field(default=None, description="""What to write instead: a sentence by its id, with its values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic']} })
    suggest: Optional[list[str]] = Field(default=None, description="""The names it may have meant, nearest first.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic']} })


class AnswerCounts(ConfiguredBaseModel):
    """
    The counts of an ask ... where answer over all its pages (P10.2a §8a): rows where the condition is true, undecided rows, and rows left out because the condition is not_applicable there. Missing is never zero: each count is given.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    rows: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerCounts', 'MatrixSheet', 'TimelineSheet', 'SourceSidecar']} })
    undecided: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'AnswerCounts']} })
    not_applicable: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerCounts']} })


class UndecidedRow(ConfiguredBaseModel):
    """
    A binder row whose condition the answer cannot decide (S1 §3.3, P10.2a §8a, cases E42, E43). In the answer dataset it is an Undecided row; its cause there is cause_relation and cause_key, both \"\" where cause is absent here.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    binder: str = Field(default=..., description="""The binder row's id, its key in the answer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow']} })
    state: UndecidedState = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })
    reason: Optional[str] = Field(default=None, description="""A reason code (S1 §2.3: the least code, A.4); left out when there is none, never free text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })
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

    kind: DeltaKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    id: str = Field(default=..., description="""The proposal id, the variant's manifest id or the sweep's name, as asked; for a supposition, the sha256 of its delta.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
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

    relation: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    added: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['RelationCount']} })
    removed: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['RelationCount']} })
    changed: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['RelationCount']} })


class DifferenceEntry(ConfiguredBaseModel):
    """
    One changed row; keys are canonical key text, as in the snapshots.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    relation: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    key: str = Field(default=..., description="""The row in the target (added, changed) or in the base (removed).""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'Verb',
                       'RowRef']} })
    change: DifferenceChange = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'DifferenceSign']} })
    was: Optional[str] = Field(default=None, description="""For changed: the row in the base.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry', 'AnswerNode']} })


class SeriesCell(ConfiguredBaseModel):
    """
    One grid value of a sweep, with the counts of its variant's difference where one was published.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    index: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'GapPremise']} })
    value: str = Field(default=..., description="""The value as decimal text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })
    status: SeriesStatus = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'SweepCheck',
                       'GapCandidate',
                       'StatusSign']} })
    manifest: Optional[str] = Field(default=None, description="""The variant's manifest, if it is green or warning.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DeltaStart', 'SeriesCell', 'BoundSweepCell']} })
    diagnosis: Optional[str] = Field(default=None, description="""The variant's diagnosis, if it is red.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell']} })
    counts: Optional[list[RelationCount]] = Field(default=None, description="""The counts of its difference for the role; absent where none was published.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Difference', 'SeriesCell']} })


class BoundSweepList(ConfiguredBaseModel):
    """
    The opt-in GET /<pack>/sweeps?m=<main> response for one verified role, bound to exactly manifest_id. A stale main, missing grid or unreadable swept cell gives the same generic 404; the gate never substitutes a newer main. The route without m keeps its legacy array.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    manifest_id: str = Field(default=..., description="""The exact selected main manifest, checked before grid or variant metadata is read.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'BoundSweepList', 'Proof']} })
    sweeps: list[BoundSweep] = Field(default=..., description="""The current pack contract allows one sweep; only a sweep whose cell the role reads appears.""", min_length=1, max_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweepList']} })


class BoundSweep(ConfiguredBaseModel):
    """
    A published grid and its actual swept fact-cell identity, not a fabricated proof row.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    cell: SweepCellRef = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep', 'ReliefLayout']} })
    min: str = Field(default=..., description="""Exact whole-number decimal text, including values beyond JavaScript's safe integer range.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })
    max: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })
    step: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep']} })
    cells: list[BoundSweepCell] = Field(default=..., description="""The complete fixed grid in index order; no interpolation or computed intermediate values.""", min_length=1, max_length=64, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep', 'MatrixSheet']} })

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

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    slot: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SweepCellRef',
                       'ChannelBinding',
                       'ImageBinding',
                       'TimelineMark',
                       'WaterfallPart',
                       'SourceSelector']} })


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
    value: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })
    status: SeriesStatus = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'SweepCheck',
                       'GapCandidate',
                       'StatusSign']} })
    checks: Optional[list[SweepCheck]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweepCell', 'Bundle', 'DerivedRelation']} })
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

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    status: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'SweepCheck',
                       'GapCandidate',
                       'StatusSign']} })

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

    relation: Optional[str] = Field(default=None, description="""Absent on an anonymous node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    key: Optional[str] = Field(default=None, description="""Canonical key text, as in the snapshots; absent on an anonymous node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'Verb',
                       'RowRef']} })
    distance: int = Field(default=..., description="""The number of steps from the start, which is 0.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'GapPremise']} })
    outside: Optional[bool] = Field(default=None, description="""An anonymous node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'GapPremise']} })
    change: Optional[NodeChange] = Field(default=None, description="""For impact: what the delta did to this row for the role; every node of an impact answer has one.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'DifferenceSign']} })
    was: Optional[str] = Field(default=None, description="""For impact, a changed cell: its row in the base, as canonical key text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry', 'AnswerNode']} })
    sources: Optional[list[Source]] = Field(default=None, description="""A base row's sources (S25), from the role's own source set and by today's rights, as the publisher sorted them: where a walk back ends. Absent on a conclusion, and on every node of a manifest without source sets. A locator, not proof that the row is true.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'SourceEntry', 'Channels']} })


class GapAnswer(ConfiguredBaseModel):
    """
    What is missing for an absent start (docs/gui.md, \"gap\"), in the walk's order.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    premises: list[GapPremise] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GapAnswer', 'Witness', 'CalcWitness']} })
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
    rule: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise', 'CalcWitness']} })
    item: int = Field(default=..., description="""The item's place in the rule's schedule.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise']} })
    kind: GapItem = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    index: int = Field(default=..., description="""Its place among the rule's items of that kind (the body for a literal).""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell', 'BoundSweepCell', 'GapPremise']} })
    relation: Optional[str] = Field(default=None, description="""The relation a literal or an aggregate reads.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    bindings: Optional[list[Binding]] = Field(default=None, description="""The variables bound before it, by name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise', 'Witness']} })
    outside: Optional[bool] = Field(default=None, description="""Over a relation the role does not read in full: nothing more is said.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'GapPremise']} })
    more: Optional[bool] = Field(default=None, description="""A literal before it had more matches than the fanout; the others were not followed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'GapPremise']} })
    overflow: Optional[bool] = Field(default=None, description="""An assignment or a sum whose operand or result lies outside BIGINT: every engine stops there, so no change makes it hold.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise']} })


class GapCandidate(ConfiguredBaseModel):
    """
    A change to one base row that answers a failing premise.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    change: Change = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'DifferenceSign']} })
    relation: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    key: str = Field(default=..., description="""Canonical key text of the row's key columns; a column the user still chooses is null.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'Verb',
                       'RowRef']} })
    status: CandidateStatus = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'SweepCheck',
                       'GapCandidate',
                       'StatusSign']} })
    premise: int = Field(default=..., description="""The premise it answers, by its place in premises.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['GapCandidate', 'AnswerStep']} })


class AnswerStep(ConfiguredBaseModel):
    """
    One edge of the role's proof graph (the relation step), between nodes of an answer.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/explain'})

    conclusion: RowRef = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep', 'Witness', 'CalcWitness']} })
    premise: RowRef = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GapCandidate', 'AnswerStep']} })
    how: StepHow = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep']} })
    position: int = Field(default=..., description="""The premise's place in the rule body, or for contributes the aggregate's place in the rule.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep',
                       'Aggregate',
                       'SourceRecord',
                       'Source',
                       'RuleLiteral',
                       'RuleAggregate']} })
    value: Optional[str] = Field(default=None, description="""On a contributes step of a sum, min or max: what the premise's row contributes, the canonical text of its value with its state, as the witness's contributors_sha256 is taken over it (RV-C09). Absent on every other step, and where the published proof pieces state none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })

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


class Key(ConfiguredBaseModel):
    """
    The visual language of the viewer as data.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    palettes: list[Palette] = Field(default=..., description="""One palette per theme.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key', 'HouseStyle']} })
    statuses: list[StatusSign] = Field(default=..., description="""One sign per status.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    kinds: Optional[list[KindSign]] = Field(default=None, description="""Shape per kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Key', 'Bundle', 'Channels']} })
    arrows: Optional[list[ArrowSign]] = Field(default=None, description="""Line style per arrow.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key', 'Bundle', 'Channels']} })
    proof_role: str = Field(default=..., description="""Legacy alias of accent_role; when both occur they must agree.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    accent_role: Optional[str] = Field(default=None, description="""Colour role for the reader's current focus, route, proof or hover; defaults to proof_role.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    tones: Optional[list[ToneSign]] = Field(default=None, description="""Evaluation signs. Legacy keys without these keep their status colour roles.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    hues: Optional[list[HueRole]] = Field(default=None, description="""Nominal palette places, not ranks or pack bindings. More than eight warns, never truncates.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    signs: Optional[list[LegendSign]] = Field(default=None, description="""The epistemic legend: at most one entry per reserved sign. A key without it draws none of them.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    differences: Optional[list[DifferenceSign]] = Field(default=None, description="""One sign per difference, the same on every sheet that draws one (RV-C02). A key without them draws no difference.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    fact_typography: Typography = Field(default=..., description="""Type style for facts.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    conclusion_typography: Typography = Field(default=..., description="""Type style for conclusions.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    strokes: Optional[list[StrokeToken]] = Field(default=None, description="""Line widths per role: line, proof, hairline, frame, selection.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    hatch: Optional[Hatch] = Field(default=None, description="""The hatching that marks unknown.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    typefaces: Optional[list[TypefaceToken]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    arrowhead: Arrowhead = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Key']} })
    channels: Optional[list[ChannelGrammar]] = Field(default=None, description="""The levels each free channel can carry.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Key', 'Bundle']} })


class Palette(ConfiguredBaseModel):
    """
    The colour tokens for one theme.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    theme: Theme = Field(default=..., description="""The theme this palette is for.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Palette', 'HouseStylePalette']} })
    tokens: list[ColorToken] = Field(default=..., description="""The colour tokens.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Palette', 'HouseStylePalette']} })


class ColorToken(ConfiguredBaseModel):
    """
    One colour role with its value.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    role: str = Field(default=..., description="""For example status.valid, proof, ink, paper.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ColorToken',
                       'StrokeToken',
                       'SizeToken',
                       'TypefaceToken',
                       'HouseStyleColor',
                       'SourceSet']} })
    value: str = Field(default=..., description="""A hex colour, or a CSS system colour for the forced_colors theme.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })

    @field_validator('value')
    def pattern_value(cls, v):
        pattern=re.compile(r"^(#[0-9a-fA-F]{6}|Canvas|CanvasText|LinkText|GrayText|Highlight|HighlightText|ButtonFace|ButtonText|ButtonBorder|Mark|MarkText)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid value format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid value format: {v}"
            raise ValueError(err_msg)
        return v


class StatusSign(ConfiguredBaseModel):
    """
    How one status is drawn.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    status: StatusName = Field(default=..., description="""The status.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'SweepCheck',
                       'GapCandidate',
                       'StatusSign']} })
    tone: Optional[Tone] = Field(default=None, description="""Evaluation sign supplying the colour; absent in legacy keys.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'LegendSign', 'DifferenceSign']} })
    color_role: str = Field(default=..., description="""Colour role used for the status.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'HueRole', 'Hatch']} })
    glyph: str = Field(default=..., description="""Glyph shown next to the value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'LensGlyph']} })
    label_message: str = Field(default=..., description="""Message id in the i18n catalogue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'Verb',
                       'NestPerspective']} })
    hatched: Optional[bool] = Field(default=None, description="""Whether the fill is hatched.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign']} })


class ToneSign(ConfiguredBaseModel):
    """
    One evaluation sign in the shared visual language.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    tone: Tone = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'LegendSign', 'DifferenceSign']} })
    color_role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'HueRole', 'Hatch']} })
    glyph: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'LensGlyph']} })
    label_message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'Verb',
                       'NestPerspective']} })


class HueRole(ConfiguredBaseModel):
    """
    A named nominal palette place; its meaning is supplied by a future pack binding.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    color_role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'HueRole', 'Hatch']} })


class LegendSign(ConfiguredBaseModel):
    """
    How one reserved sign of the epistemic legend is drawn: its form, its glyph where it has one, its label and its colour. Without `tone` or `accent` the mark is in ink.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view',
         'rules': [{'description': 'The form glyph has a glyph.',
                    'postconditions': {'slot_conditions': {'glyph': {'name': 'glyph',
                                                                     'required': True}}},
                    'preconditions': {'slot_conditions': {'form': {'equals_string': 'glyph',
                                                                   'name': 'form'}}}}]})

    sign: SignName = Field(default=..., description="""The reserved sign.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LegendSign']} })
    form: SignForm = Field(default=..., description="""How the sign is drawn.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LegendSign']} })
    glyph: Optional[str] = Field(default=None, description="""The sign's glyph; required for the form glyph.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'LensGlyph']} })
    label_message: str = Field(default=..., description="""Message id in the i18n catalogue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'Verb',
                       'NestPerspective']} })
    tone: Optional[Tone] = Field(default=None, description="""The evaluation that colours the mark, through the key's tone signs.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'LegendSign', 'DifferenceSign']} })
    accent: Optional[bool] = Field(default=None, description="""The mark takes the accent colour: the reader follows or moves this value. Never together with tone.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LegendSign']} })
    dash: Optional[str] = Field(default=None, description="""SVG dash array of the form's broken line, or none; in running text it is a dashed line.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LegendSign', 'ArrowSign']} })


class DifferenceSign(ConfiguredBaseModel):
    """
    How one difference is drawn on every sheet: a sign before the value and its label, and the tone that colours the sign. Never colour alone: the sign and the label say it in forced colours too.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    change: DifferenceName = Field(default=..., description="""The difference.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'DifferenceSign']} })
    glyph: str = Field(default=..., description="""The sign before the value, for example + or −.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'LensGlyph']} })
    label_message: str = Field(default=..., description="""Message id in the i18n catalogue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'Verb',
                       'NestPerspective']} })
    tone: Optional[Tone] = Field(default=None, description="""The evaluation that colours the sign, through the key's tone signs; without it the sign is in ink.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'LegendSign', 'DifferenceSign']} })


class KindSign(ConfiguredBaseModel):
    """
    How one kind is drawn.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    kind: str = Field(default=..., description="""Kind id from a schema.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    shape: Shape = Field(default=..., description="""Shape of the node.""", json_schema_extra = { "linkml_meta": {'domain_of': ['KindSign']} })
    icon: Optional[str] = Field(default=None, description="""Icon of the kind, beside its shape (decision B10). In channels.yaml an .svg file under the pack's icons/, listed in icons/sources.yaml; in the schema bundle the sha256 of that file, which names an entry of Channels.icons.""", json_schema_extra = { "linkml_meta": {'domain_of': ['KindSign']} })


class ArrowSign(ConfiguredBaseModel):
    """
    How one arrow is drawn.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    arrow: str = Field(default=..., description="""Arrow id from a schema, or a derived relation that a Flow draws as lines.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ArrowSign', 'TrackDepends', 'EdgeSource']} })
    dash: str = Field(default=..., description="""SVG dash array, or none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LegendSign', 'ArrowSign']} })


class StrokeToken(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ColorToken',
                       'StrokeToken',
                       'SizeToken',
                       'TypefaceToken',
                       'HouseStyleColor',
                       'SourceSet']} })
    width: int = Field(default=..., description="""Width in CSS pixels.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['StrokeToken', 'Hatch', 'Arrowhead']} })


class Hatch(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    color_role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign', 'ToneSign', 'HueRole', 'Hatch']} })
    spacing: int = Field(default=..., ge=2, json_schema_extra = { "linkml_meta": {'domain_of': ['Hatch']} })
    angle: int = Field(default=..., description="""Degrees.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Hatch']} })
    width: int = Field(default=..., ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['StrokeToken', 'Hatch', 'Arrowhead']} })


class Arrowhead(ConfiguredBaseModel):
    """
    A triangle at the end of a line, in units of the line width.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    length: int = Field(default=..., ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Arrowhead']} })
    width: int = Field(default=..., ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['StrokeToken', 'Hatch', 'Arrowhead']} })


class SizeToken(ConfiguredBaseModel):
    """
    A size in CSS pixels per role: space.*, type.*, leading.*, tracking.*, sample.*, sign.*, focus.*, selection.*, page.*.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ColorToken',
                       'StrokeToken',
                       'SizeToken',
                       'TypefaceToken',
                       'HouseStyleColor',
                       'SourceSet']} })
    px: int = Field(default=..., ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['SizeToken']} })


class TypefaceToken(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    role: str = Field(default=..., description="""For example text or figures.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ColorToken',
                       'StrokeToken',
                       'SizeToken',
                       'TypefaceToken',
                       'HouseStyleColor',
                       'SourceSet']} })
    family: str = Field(default=..., description="""A CSS font-family list.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TypefaceToken']} })


class Sheets(ConfiguredBaseModel):
    """
    Sheet layout (sheets.yaml) - frame, cartouche, key extract, fold and Lens.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    frame_stroke_role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })
    metrics: Metrics = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })
    sizes: list[SizeToken] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })
    cartouche: Cartouche = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })
    key_extract: KeyExtract = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })
    fold: Fold = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets', 'SheetSign', 'Kind', 'DerivedRelation']} })
    lens: LensLayout = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })
    verbs: Optional[list[Verb]] = Field(default=None, description="""The verb bar, in its fixed order; each verb at most once. Without it a sheet has no verb bar.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })
    relief: Optional[ReliefLayout] = Field(default=None, description="""Sizes for Landscape as relief.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets', 'SheetBindings', 'Channels']} })
    sheets: list[SheetSign] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets']} })


class Metrics(ConfiguredBaseModel):
    """
    Sizes in CSS pixels that the deterministic layout uses; text is measured by character count.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    font_size: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Metrics']} })
    char_width: int = Field(default=..., description="""Average glyph advance used to size node boxes.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Metrics']} })
    line_height: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Metrics']} })
    padding: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Metrics']} })
    gap: int = Field(default=..., description="""Spacing between nodes and between layers.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Metrics']} })
    bar_width: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Metrics']} })
    chart_height: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Metrics']} })
    narrow_width: int = Field(default=..., description="""Below this viewport width a sheet stacks in one column.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Metrics']} })


class Cartouche(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    placement: BlockEdge = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Cartouche', 'KeyExtract', 'LensLayout']} })
    fields: list[CartoucheField] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext', 'Cartouche', 'CardsPart', 'Page']} })


class KeyExtract(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    placement: Placement = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Cartouche', 'KeyExtract', 'LensLayout']} })
    title_message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })


class Fold(ConfiguredBaseModel):
    """
    The double hairline on an Impact sheet, current on the start side, proposal on the end side.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    current_message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Fold']} })
    proposal_message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Fold']} })
    stroke_role: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Fold']} })


class LensLayout(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    placement: InlineEdge = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Cartouche', 'KeyExtract', 'LensLayout']} })
    glyphs: list[LensGlyph] = Field(default=..., description="""One glyph per answer shape: every question with that shape gets it, a pack's own too.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LensLayout']} })


class LensGlyph(ConfiguredBaseModel):
    """
    The glyph of the questions whose answer has this shape (contracts/explain.yaml).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    answer: AnswerShape = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'LensGlyph']} })
    glyph: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'LensGlyph']} })


class Verb(ConfiguredBaseModel):
    """
    One verb of the verb bar: its label, its key, and the question of the bundle that answers it where it is one.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    verb: VerbName = Field(default=..., description="""The verb.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Verb']} })
    label_message: str = Field(default=..., description="""Message id in the i18n catalogue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'Verb',
                       'NestPerspective']} })
    key: str = Field(default=..., description="""The key that opens the verb: one letter, the same on every sheet.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'Verb',
                       'RowRef']} })
    question: Optional[str] = Field(default=None, description="""Term of the question that answers the verb (contracts/explain.yaml, Question.term); absent where the verb is no question.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Verb']} })
    primary: Optional[bool] = Field(default=None, description="""The verb that changes something, drawn as the filled button. At most one.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Verb']} })

    @field_validator('key')
    def pattern_key(cls, v):
        pattern=re.compile(r"^[a-z]$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid key format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid key format: {v}"
            raise ValueError(err_msg)
        return v


class SheetSign(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    sheet: str = Field(default=..., description="""Sheet name: index, kind, answer or impact.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetSign', 'MatrixPart']} })
    title_message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })
    fold: Optional[bool] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets', 'SheetSign', 'Kind', 'DerivedRelation']} })


class ReliefLayout(ConfiguredBaseModel):
    """
    Sizes in CSS pixels for Landscape as relief, and the number of contour steps.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    levels: int = Field(default=..., description="""Contour lines from the coast to the highest summit on the sheet.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefLayout', 'ChannelGrammar', 'NestSheet']} })
    radius: int = Field(default=..., description="""Radius of the summit of an island.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefLayout']} })
    cell: int = Field(default=..., description="""Grid step for the contour lines.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep', 'ReliefLayout']} })
    count_scale: VisualScale = Field(default=..., description="""The scale of an island's height when it is its number of members: a relief without a height binding, or an island of a kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefLayout']} })


class ChannelGrammar(ConfiguredBaseModel):
    """
    The levels of measurement one free channel can carry. A binding at another level is refused.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    channel: ChannelType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ChannelGrammar', 'ChannelBinding']} })
    levels: list[ScaleLevel] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefLayout', 'ChannelGrammar', 'NestSheet']} })


class VisualScale(ConfiguredBaseModel):
    """
    How a quantity maps to a channel: (value - zero) to the power numerator/denominator, as a share of the largest value on the sheet. Integers only, so the scale itself is exact (AGENTS.md rule 3). The zero is in the value's own units (minor units for an amount). A value below the zero is outside the scale and stops the sheet, never drawn as zero.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    zero: int = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['VisualScale']} })
    exponent_numerator: int = Field(default=..., ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['VisualScale']} })
    exponent_denominator: int = Field(default=..., ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['VisualScale']} })
    unit_message: str = Field(default=..., description="""Message id of the unit, shown with the exact value of an integer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['VisualScale']} })


class ChannelBinding(ConfiguredBaseModel):
    """
    A free channel bound to one slot, with the meaning the pack gives it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view',
         'rules': [{'description': 'A quantitative meaning has a unit, a scale and a '
                                   'zero.',
                    'postconditions': {'slot_conditions': {'scale': {'name': 'scale',
                                                                     'required': True}}},
                    'preconditions': {'slot_conditions': {'level': {'equals_string': 'quantitative',
                                                                    'name': 'level'}}}}]})

    channel: ChannelType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ChannelGrammar', 'ChannelBinding']} })
    slot: str = Field(default=..., description="""The relation (`<kind>__<slot>`) the channel shows: an attribute or an arrow.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SweepCellRef',
                       'ChannelBinding',
                       'ImageBinding',
                       'TimelineMark',
                       'WaterfallPart',
                       'SourceSelector']} })
    level: ScaleLevel = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ChannelBinding']} })
    meaning_message: str = Field(default=..., description="""Message id of the meaning, for the key.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ChannelBinding']} })
    scale: Optional[VisualScale] = Field(default=None, description="""Required for a quantitative meaning.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ChannelBinding', 'Quantity']} })


class ImageBinding(ConfiguredBaseModel):
    """
    An image per element (decision B10, docs/gui.md#icons-and-images): a single-valued text slot of the kind, or of a kind above it, whose value names a file in the pack's assets/. The binding makes the slot an image, one per kind; a subkind's own binding wins for its elements. Its meaning is the pack's.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    kind: str = Field(default=..., description="""Kind id from a schema.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    slot: str = Field(default=..., description="""The slot, by element id (`<kind>.<slot>`, the kind that declares it).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SweepCellRef',
                       'ChannelBinding',
                       'ImageBinding',
                       'TimelineMark',
                       'WaterfallPart',
                       'SourceSelector']} })


class ReliefSheet(ConfiguredBaseModel):
    """
    Landscape as relief. Every row of `region` is an island. Its height is `height`, or its number of members; the rows that point to it with `member` shape its coast and make its ring of status shares.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    region: str = Field(default=..., description="""The kind whose rows are the islands.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet']} })
    member: str = Field(default=..., description="""Arrow from the member kind to the region kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet']} })
    label: Optional[str] = Field(default=None, description="""Text attribute of the region kind that names an island; without it, the id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet',
                       'TrackSheet',
                       'FlowNode',
                       'TimelineSheet',
                       'NestLevel']} })
    height: Optional[ChannelBinding] = Field(default=None, description="""An elevation binding on an attribute of the region kind; without it, the number of members on std-view's count scale.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet']} })


class TrackDepends(ConfiguredBaseModel):
    """
    The rails of a Track: one arrow from station to station (`arrow`), or a link kind (`via`) with an arrow to the station that waits (`from`) and one to the station it waits for (`to`).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    arrow: Optional[str] = Field(default=None, description="""Arrow from the station kind to the station kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ArrowSign', 'TrackDepends', 'EdgeSource']} })
    via: Optional[str] = Field(default=None, description="""Link kind, for more than one dependency per station.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackDepends', 'EdgeSource']} })
    from_: Optional[str] = Field(default=None, alias="from", description="""Arrow from the link kind to the station that waits.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackDepends', 'EdgeSource']} })
    to: Optional[str] = Field(default=None, description="""Arrow from the link kind to the station it waits for.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackDepends', 'EdgeSource']} })


class TrackSheet(ConfiguredBaseModel):
    """
    Track as rail map: one sheet per plan row. A wave is a column of stations, a dependency is rail, the time of a wave is the kilometre marker at the bottom, and `line` gives the bands. The waves stand in the order of the wave kind's order role, or by `time` where it is bound; every rail runs with that order, so a station never waits on anything after it, and a dependency against the order stops the sheet. Inline place is order, not calendar time. Without `line`, block place means nothing.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    station: str = Field(default=..., description="""The kind whose rows are the stations.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })
    plan: str = Field(default=..., description="""Arrow from the station kind to the plan kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })
    wave: str = Field(default=..., description="""Arrow from the station kind to the wave kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })
    time: Optional[str] = Field(default=None, description="""ISO date attribute of the wave kind; where bound it orders the waves (then their order role and id) and labels the markers.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })
    label: Optional[str] = Field(default=None, description="""Text attribute of the station kind that names a station; without it, the id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet',
                       'TrackSheet',
                       'FlowNode',
                       'TimelineSheet',
                       'NestLevel']} })
    line: Optional[ChannelBinding] = Field(default=None, description="""A lane binding on an attribute or arrow of the station kind: the rows. Without it the layout places the stations across the rails and that place means nothing.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet', 'Span', 'RuleOrigin']} })
    depends: TrackDepends = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })
    critical: Optional[EdgeSource] = Field(default=None, description="""A derived relation edge source whose rows are the dependencies on the critical path: `from` the column of the station that waits, `to` the column of the station it waits for, both of the station kind. Such a rail is drawn in the accent, on top; the sheet never works out a critical path itself.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })
    duration: Optional[str] = Field(default=None, description="""A single-valued attribute of the station kind shown under its mark: how long the step takes. An unknown cell is hatched and written as unknown, never zero.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })
    done: Optional[str] = Field(default=None, description="""A single-valued boolean attribute of the station kind: the step is finished. A finished station carries the key's positive sign; the reference date stands between the finished stations and the rest, where one line parts them.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet']} })


class EdgeSource(ConfiguredBaseModel):
    """
    What a sheet draws as lines (docs/gui.md, Edge source): an arrow (`arrow`); a link kind and its arrow to each end (`via`, `from`, `to`); or a derived relation and two of its symbol columns (`relation`, `from`, `to`), with the node kinds the ids in each column belong to (`from_kinds`, `to_kinds`). Exactly one of `arrow`, `via` and `relation`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    arrow: Optional[str] = Field(default=None, description="""An arrow from one node kind to another.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ArrowSign', 'TrackDepends', 'EdgeSource']} })
    via: Optional[str] = Field(default=None, description="""A link kind (a kind whose first unique key holds only single-valued arrows) whose rows are the lines; `from` and `to` are arrows of that key.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackDepends', 'EdgeSource']} })
    relation: Optional[str] = Field(default=None, description="""A derived relation of the rules whose rows are the lines.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    from_: Optional[str] = Field(default=None, alias="from", description="""With `via`, the arrow to the start; with `relation`, the column of the start.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackDepends', 'EdgeSource']} })
    to: Optional[str] = Field(default=None, description="""With `via`, the arrow to the end; with `relation`, the column of the end.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TrackDepends', 'EdgeSource']} })
    from_kinds: Optional[list[str]] = Field(default=None, description="""With `relation`: the node kinds an id in `from` can be.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EdgeSource']} })
    to_kinds: Optional[list[str]] = Field(default=None, description="""With `relation`: the node kinds an id in `to` can be.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EdgeSource']} })
    quantity: Optional[ChannelBinding] = Field(default=None, description="""With `relation` or `via`: a size binding at level quantitative on an integer column of the relation (its slot is the column's name) or an integer attribute of the link kind. The line is a band, its width the sum over the pair's rows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['EdgeSource']} })


class FlowNode(ConfiguredBaseModel):
    """
    One node kind of a Flow. It is one lane, or with `lane` one lane per value. At level `ordered` the lanes stand in a declared order: an arrow's targets by the order role of their kind (S26; until every pack carries it, their integer attribute `lane_order`), and the compiler refuses the binding where the kind has none; an enum's values as the bundle gives them. At level `nominal` the lanes are categories. With `group`, its nodes stand in a box per target of that arrow.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    label: Optional[str] = Field(default=None, description="""Text attribute of the kind that names a node; without it, the element's name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet',
                       'TrackSheet',
                       'FlowNode',
                       'TimelineSheet',
                       'NestLevel']} })
    lane: Optional[ChannelBinding] = Field(default=None, description="""A lane binding on a single-valued enum attribute or arrow of the kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FlowNode', 'MatrixAxis']} })
    group: Optional[str] = Field(default=None, description="""A single-valued arrow of the kind to a kind that is no node kind: the box, within the lane, the node stands in (one level).""", json_schema_extra = { "linkml_meta": {'domain_of': ['FlowNode']} })


class FlowSheet(ConfiguredBaseModel):
    """
    Flow: typed nodes in ordered lanes, with lines from edge sources (docs/gui.md, Flow). One sheet per binding, at `/<pack>/flow/<id>`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    title_message: str = Field(default=..., description="""Message id of the sheet's title.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })
    nodes: list[FlowNode] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'FlowSheet']} })
    edges: list[EdgeSource] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['FlowSheet']} })
    direction: Optional[FlowDirection] = Field(default=None, description="""Without it, `right`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Trace', 'FlowSheet']} })
    routes: Optional[EdgeSource] = Field(default=None, description="""A relation edge source whose rows are routes, listed by their start (`from` is its first column). A route is no line; a chosen one draws its proof (`grounds`) over the lines.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FlowSheet']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class MatrixAxis(ConfiguredBaseModel):
    """
    One axis of a Matrix: the elements of a kind (and its subkinds), in the kind's order where it has one, else in name order (docs/gui.md, Names). With `lane`, on `columns` only, the Matrix is a Board (docs/gui.md, Board): the sheet has one column per value of the lane, in the enum's declared order, and a cell holds the elements of the kind with that value that the cells' source pairs with the row, each as a chip. An element without a value stands in a strip of unknown, never in a column.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    lane: Optional[ChannelBinding] = Field(default=None, description="""On `columns` only: a lane binding on a single-valued enum attribute of the kind. Its values are the sheet's columns.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FlowNode', 'MatrixAxis']} })


class MatrixSheet(ConfiguredBaseModel):
    """
    Matrix: the elements of one kind as rows, of another (or the same) as columns, and a cell per pair that an edge source gives (docs/gui.md, Matrix). A cell is the rows behind its pair, each with its proof; an empty cell is blank where the source is closed and unknown (hatched) where it is open (W6). One sheet per binding, at `/<pack>/matrix/<id>`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    title_message: str = Field(default=..., description="""Message id of the sheet's title.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })
    rows: MatrixAxis = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerCounts', 'MatrixSheet', 'TimelineSheet', 'SourceSidecar']} })
    columns: MatrixAxis = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion', 'MatrixSheet', 'DerivedRelation']} })
    cells: EdgeSource = Field(default=..., description="""From the row kind to the column kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep', 'MatrixSheet']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class TimelineMark(ConfiguredBaseModel):
    """
    A dated event on a row of a Timeline: a single-valued date attribute of the row kind, drawn as a mark at that date with the attribute's label and the date. An element without that date has no mark. The mark takes the legend sign of the fact's origin where the bundle provides it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    slot: str = Field(default=..., description="""A single-valued date attribute of the row kind, by its relation (`<kind>__<slot>`).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SweepCellRef',
                       'ChannelBinding',
                       'ImageBinding',
                       'TimelineMark',
                       'WaterfallPart',
                       'SourceSelector']} })


class TimelineSheet(ConfiguredBaseModel):
    """
    Timeline (Intervals): validity in time (docs/gui.md, Intervals). One row per element of a kind on one date axis. A row has a main phase, from `start` to `end`, and optionally an extension, from `end` to `extension`; each is half-open (valid from its first date up to, not on, its last). A date whose cell is unknown is drawn hatched and written as unknown, never as \"no end\". Rows stand in the order of the kind's order role where it has one, else by start (unknown last), then by name and id. The reference date is the reader's (the date of the context; until a context has one, the date of the manifest's knowledge time), never a field of the binding. One sheet per binding, at `/<pack>/timeline/<id>`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view',
         'rules': [{'description': 'An extension has a name.',
                    'postconditions': {'slot_conditions': {'extension_message': {'name': 'extension_message',
                                                                                 'required': True}}},
                    'preconditions': {'slot_conditions': {'extension': {'name': 'extension',
                                                                        'required': True}}}}]})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    title_message: str = Field(default=..., description="""Message id of the sheet's title.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })
    rows: str = Field(default=..., description="""The kind whose elements are the rows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerCounts', 'MatrixSheet', 'TimelineSheet', 'SourceSidecar']} })
    label: Optional[str] = Field(default=None, description="""Text attribute of the row kind that names a row; without it, the element's name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet',
                       'TrackSheet',
                       'FlowNode',
                       'TimelineSheet',
                       'NestLevel']} })
    start: str = Field(default=..., description="""A single-valued date attribute of the row kind (`<kind>__<slot>`): the first date of the main phase.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer', 'TimelineSheet']} })
    end: str = Field(default=..., description="""A single-valued date attribute of the row kind: the end of the main phase.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TimelineSheet']} })
    extension: Optional[str] = Field(default=None, description="""A single-valued date attribute of the row kind: the end of the extension. Without it, a row ends at `end`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TimelineSheet']} })
    main_message: str = Field(default=..., description="""Message id of the main phase's name, for the key and the table twin.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TimelineSheet']} })
    extension_message: Optional[str] = Field(default=None, description="""Message id of the extension's name; required with `extension`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TimelineSheet']} })
    judgement: Optional[ChannelBinding] = Field(default=None, description="""A tone binding at level ordered on a single-valued attribute of the row kind: what the pack's rules conclude about a row. The sheet never judges a row by where its bar ends. Drawn once a tone binding has an encoding of its values (as a Matrix's `value`).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TimelineSheet']} })
    marks: Optional[list[TimelineMark]] = Field(default=None, description="""Dated events on a row, each a date attribute of the row kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['TimelineSheet']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class NestLevel(ConfiguredBaseModel):
    """
    One level of a Nest, from the outside in: the kind whose elements are the parts at this depth, the arrow that says what each is part of, and how an element of this level lays out its own parts.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    kind: str = Field(default=..., description="""The kind whose elements are the parts at this level.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    part_of: Optional[str] = Field(default=None, description="""A single-valued arrow from this kind to the kind of the level before it: what an element is part of. Required on every level but the first, and never on the first.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestLevel']} })
    label: Optional[str] = Field(default=None, description="""Text attribute of the kind that names a part; without it, the element's name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefSheet',
                       'TrackSheet',
                       'FlowNode',
                       'TimelineSheet',
                       'NestLevel']} })
    flow: Optional[NestFlow] = Field(default=None, description="""How an element of this level lays out its parts: side by side or below each other, in the order of the next level's kind (its order role). Required on every level but the last.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestLevel', 'HomeHero']} })
    order_message: Optional[str] = Field(default=None, description="""Message id of what that order means, for the key.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestLevel']} })


class NestPerspective(ConfiguredBaseModel):
    """
    A perspective on a Nest: another set of bindings on the same parts. It changes no geometry. Without `relation` it is the nest as it is. With `relation`, a derived relation of the rules gives a part its state: `part` is the column that holds the part, `state` binds a tone to one more column, and `origin` is the column of the element the perspective starts from (what the reader supposes), drawn with the legend sign for supposed. A part the role may not read gets no state.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view',
         'rules': [{'description': 'A perspective over a relation names the column of '
                                   'the part and the state it binds.',
                    'postconditions': {'slot_conditions': {'part': {'name': 'part',
                                                                    'required': True},
                                                           'state': {'name': 'state',
                                                                     'required': True}}},
                    'preconditions': {'slot_conditions': {'relation': {'name': 'relation',
                                                                       'required': True}}}}]})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    label_message: str = Field(default=..., description="""Message id of the perspective's name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['StatusSign',
                       'ToneSign',
                       'LegendSign',
                       'DifferenceSign',
                       'Verb',
                       'NestPerspective']} })
    relation: Optional[str] = Field(default=None, description="""A derived relation of the rules whose rows say what holds for a part in this perspective.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    part: Optional[str] = Field(default=None, description="""With `relation`: the symbol column that holds the part.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestPerspective']} })
    origin: Optional[str] = Field(default=None, description="""With `relation`: the symbol column of the element the perspective starts from; the reader chooses it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestPerspective', 'Rule']} })
    state: Optional[ChannelBinding] = Field(default=None, description="""With `relation`: a tone binding at level ordered on a column of the relation (its slot is the column's name). Drawn once a tone binding has an encoding of its values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class NestSheet(ConfiguredBaseModel):
    """
    Nest: containment (docs/gui.md, Nest). Inside means part of: an element of a level is drawn inside the element its `part_of` arrow points to. Place within a container is the order of the level's kind, as a row or a column, and nothing else; box size carries no meaning. A level's arrow is single-valued and points one level out, so the parts form a tree. An element whose container is unknown stands in no container: the sheet names it apart, as unknown. One sheet per element of the first level, at `/<pack>/nest/<id>/<element>`; a perspective is chosen in the address.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    title_message: str = Field(default=..., description="""Message id of the sheet's title.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })
    part_message: str = Field(default=..., description="""Message id of what nesting means in this pack, for the key.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestSheet']} })
    levels: list[NestLevel] = Field(default=..., description="""The levels from the outside in; at least two.""", min_length=2, json_schema_extra = { "linkml_meta": {'domain_of': ['ReliefLayout', 'ChannelGrammar', 'NestSheet']} })
    perspectives: Optional[list[NestPerspective]] = Field(default=None, description="""In reading order; the first is shown when none is chosen. Without any, the nest as it is.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestSheet']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class CardsPart(ConfiguredBaseModel):
    """
    A Report part: one card per row of a kind, each the head of its page per kind with the named fields of the kind's page template, in that order, and a link to that page (docs/gui.md, Cards). The cards are read a page at a time, in id order, from the role's rows.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    fields: list[str] = Field(default=..., description="""Slots of the kind's page template, by element id (`<kind>.<slot>`), in the order shown.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext', 'Cartouche', 'CardsPart', 'Page']} })


class WaterfallPart(ConfiguredBaseModel):
    """
    A paged series of existing Waterfalls for the role's elements of an amount attribute's declaring kind, using the same rowsPage selection and cursor as Cards. No instance ids or new selector in the binding. Without a role-visible derivation proof an item is unavailable, never a raw amount value.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    slot: str = Field(default=..., description="""An amount attribute by element id (`<kind>.<slot>`); its declaring kind is paged through the Report's published manifest and role.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SweepCellRef',
                       'ChannelBinding',
                       'ImageBinding',
                       'TimelineMark',
                       'WaterfallPart',
                       'SourceSelector']} })


class MatrixPart(ConfiguredBaseModel):
    """
    One existing Matrix binding's published overview in this Report's manifest and role; no instance, file or context selector.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    sheet: str = Field(default=..., description="""ID of a Matrix binding in this pack's channel table.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetSign', 'MatrixPart']} })

    @field_validator('sheet')
    def pattern_sheet(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid sheet format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid sheet format: {v}"
            raise ValueError(err_msg)
        return v


class ComparisonPart(ConfiguredBaseModel):
    """
    A Report part (docs/gui.md, Comparison; RV-U19): one derived relation that compares the pack with a reference source (decision R13), counted in three classes by the verdict column of its rows, each count a link to the rows of that class with their proofs. The mapping of verdicts to classes is pack data; the compiler stops a pack whose rules can give a verdict that no class names (unknown is explicit).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    relation: str = Field(default=..., description="""A derived relation of the pack's rules.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    verdict: str = Field(default=..., description="""The column of the relation that holds its verdict.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ComparisonPart']} })
    equal: Optional[list[str]] = Field(default=None, description="""The verdicts that count as equal.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ComparisonPart']} })
    different: Optional[list[str]] = Field(default=None, description="""The verdicts that count as different.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ComparisonPart']} })
    not_compared: Optional[list[str]] = Field(default=None, description="""The verdicts that count as not compared (a row whose two sides have one source, decision Q11, among them).""", json_schema_extra = { "linkml_meta": {'domain_of': ['ComparisonPart']} })

    @field_validator('relation')
    def pattern_relation(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid relation format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid relation format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('verdict')
    def pattern_verdict(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid verdict format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid verdict format: {v}"
            raise ValueError(err_msg)
        return v


class ReportPart(ConfiguredBaseModel):
    """
    One part of a Report, in composition order; exactly one of cards, a Waterfall, a Matrix or a comparison.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'exactly_one_of': [{'slot_conditions': {'cards': {'name': 'cards',
                                                           'required': True}}},
                            {'slot_conditions': {'waterfall': {'name': 'waterfall',
                                                               'required': True}}},
                            {'slot_conditions': {'matrix': {'name': 'matrix',
                                                            'required': True}}},
                            {'slot_conditions': {'comparison': {'name': 'comparison',
                                                                'required': True}}}],
         'from_schema': 'https://rede.dev/contracts/view'})

    cards: Optional[CardsPart] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReportPart']} })
    waterfall: Optional[WaterfallPart] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReportPart']} })
    matrix: Optional[MatrixPart] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReportPart']} })
    comparison: Optional[ComparisonPart] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReportPart']} })


class ReportSheet(ConfiguredBaseModel):
    """
    Report: a fixed composition of parts from one published manifest (docs/gui.md, Report; decision B5). One sheet per binding, at `/<pack>/reports/<id>`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    title_message: str = Field(default=..., description="""Message id of the report's title.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'KeyExtract',
                       'SheetSign',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestSheet',
                       'ReportSheet']} })
    parts: list[ReportPart] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReportSheet']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class HomeHero(ConfiguredBaseModel):
    """
    The hero of a pack home: one sheet the pack declares, by its form and id. Exactly one form, which the compiler checks; today the only form is a Flow.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    flow: Optional[str] = Field(default=None, description="""The id of a Flow of the pack.""", json_schema_extra = { "linkml_meta": {'domain_of': ['NestLevel', 'HomeHero']} })


class HomeSheet(ConfiguredBaseModel):
    """
    What a pack declares for its home (docs/gui.md, The hero of a pack home): the hero, the picture under the claim and above the attention cards, and the claim it proves; each is optional. One home per pack. Without it the home is the cards alone.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    hero: Optional[HomeHero] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['HomeSheet']} })
    claim: Optional[list[str]] = Field(default=None, description="""Derived relations of the rules, each with exactly one rule and its message in every language of the pack. The home's claim is the sentences of the relations of which the role reads exactly one row, in this order, each with its `grounds`; a relation with no row or more than one gives no sentence. With none left the home keeps the claim of its cards.""", json_schema_extra = { "linkml_meta": {'domain_of': ['HomeSheet']} })


class HouseStyle(ConfiguredBaseModel):
    """
    A pack's house style (docs/gui.md, House style): its own values for colour roles that std-view defines, per display theme. It gives values only. It adds no role and changes no sign, glyph, dash, stroke, hatching or label, so the legend reads the same in every house style. One house style per pack; a pack without one is drawn in std-view's colours.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    palettes: list[HouseStylePalette] = Field(default=..., description="""At most one palette per display theme, which the compiler checks. A theme without one keeps std-view's palette.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Key', 'HouseStyle']} })


class HouseStylePalette(ConfiguredBaseModel):
    """
    The house style's colours for one display theme.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    theme: HouseStyleTheme = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Palette', 'HouseStylePalette']} })
    tokens: list[HouseStyleColor] = Field(default=..., description="""At most one value per role, which the compiler checks. A role without one keeps std-view's value.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Palette', 'HouseStylePalette']} })


class HouseStyleColor(ConfiguredBaseModel):
    """
    One colour role of std-view with the house style's value.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    role: str = Field(default=..., description="""A colour role a house style may set: the ground, the inks, the rule and the accent. The colours of statuses, tones and hues are not in this list; they stay std-view's.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ColorToken',
                       'StrokeToken',
                       'SizeToken',
                       'TypefaceToken',
                       'HouseStyleColor',
                       'SourceSet']} })
    value: str = Field(default=..., description="""A hex colour.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })

    @field_validator('role')
    def pattern_role(cls, v):
        pattern=re.compile(r"^(paper|ink|ink\.muted|rule|proof)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid role format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid role format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('value')
    def pattern_value(cls, v):
        pattern=re.compile(r"^#[0-9a-fA-F]{6}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid value format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid value format: {v}"
            raise ValueError(err_msg)
        return v


class SheetBindings(ConfiguredBaseModel):
    """
    The sheet part of a pack's channel table: which kinds and slots a map sheet draws, and with which free channels. Optional per sheet; a pack without it keeps the plain Map.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/view'})

    home: Optional[HomeSheet] = Field(default=None, description="""The pack home's hero and claim.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    relief: Optional[ReliefSheet] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets', 'SheetBindings', 'Channels']} })
    track: Optional[TrackSheet] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings']} })
    flows: Optional[list[FlowSheet]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    matrices: Optional[list[MatrixSheet]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    timelines: Optional[list[TimelineSheet]] = Field(default=None, description="""Timelines, each at `/<pack>/timeline/<id>`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    nests: Optional[list[NestSheet]] = Field(default=None, description="""Nests, each at `/<pack>/nest/<id>/<element>`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    reports: Optional[list[ReportSheet]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })


class RowRef(ConfiguredBaseModel):
    """
    A reference to one row of one relation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    relation: str = Field(default=..., description="""Relation name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    key: str = Field(default=..., description="""Canonical key of the row: stable and deterministic.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DifferenceEntry',
                       'AnswerNode',
                       'GapCandidate',
                       'Verb',
                       'RowRef']} })


class Premise(ConfiguredBaseModel):
    """
    One body atom of a witness, with its polarity and stratum.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    row: RowRef = Field(default=..., description="""The row the premise refers to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise', 'SourceEntry']} })
    polarity: Polarity = Field(default=..., description="""Whether the row must be present or absent.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise', 'RuleLiteral']} })
    stratum: int = Field(default=..., description="""Stratum of the premise relation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise']} })


class Aggregate(ConfiguredBaseModel):
    """
    Evidence for an aggregate premise; the checker recomputes it over the group.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    relation: str = Field(default=..., description="""Relation that is aggregated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    position: Optional[int] = Field(default=None, description="""The place of this aggregate in the rule (from 0). Two aggregates over the same relation and group (a count and a sum) are told apart by it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep',
                       'Aggregate',
                       'SourceRecord',
                       'Source',
                       'RuleLiteral',
                       'RuleAggregate']} })
    group_key: str = Field(default=..., description="""Canonical key of the group.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    count: int = Field(default=..., description="""Number of contributing rows in the group.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    contributors_sha256: str = Field(default=..., description="""Hash over the sorted keys and values of all contributing rows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    result: str = Field(default=..., description="""Canonical text of the aggregate value with its state.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate', 'RuleLiteral']} })


class Witness(ConfiguredBaseModel):
    """
    One rule instance that derives a conclusion.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    conclusion: RowRef = Field(default=..., description="""The row this witness derives.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep', 'Witness', 'CalcWitness']} })
    rule_id: str = Field(default=..., description="""Identifier of the rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness']} })
    bindings: Optional[list[Binding]] = Field(default=None, description="""The substitution of the rule variables.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise', 'Witness']} })
    premises: Optional[list[Premise]] = Field(default=None, description="""The instantiated body atoms.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapAnswer', 'Witness', 'CalcWitness']} })
    aggregates: Optional[list[Aggregate]] = Field(default=None, description="""Evidence for the aggregate body atoms.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'Rule']} })


class Binding(ConfiguredBaseModel):
    """
    One variable of the rule bound to a canonical value.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    variable: str = Field(default=..., description="""Variable name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding']} })
    value: str = Field(default=..., description="""Canonical value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })


class CalcStep(ConfiguredBaseModel):
    """
    One evaluated node of a calculation (docs/compiler.md, \"Design M3: calculation witnesses\"). A constant has no step; an untaken branch of an `if` and the value of a definition that does not apply are not evaluated.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    path: str = Field(default=..., description="""The node: <definition>/when or <definition>/value, then one argument index per level.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep', 'CheckView', 'Page']} })
    op: str = Field(default=..., description="""What the node is, as the program has it: fact, parameter or rule for a leaf, else the operator (add, if, round, ...).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep', 'RuleLiteral']} })
    ref: Optional[str] = Field(default=None, description="""For a leaf: the fact, the parameter or the rule (rule or rule@version) it names, so an explanation can name and link it. Absent for an operator.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })
    relation: Optional[str] = Field(default=None, description="""For a leaf: the table or view it is read from (the attribute table, the derived relation, the parameter table, the rule's view). Absent for an operator and for an input concept.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    value: Optional[str] = Field(default=None, description="""Canonical text of the value (a number as n or n/d in lowest terms, a boolean as true or false); empty unless the state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })
    state: ValueState = Field(default=..., description="""State of the value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })
    reason: Optional[str] = Field(default=None, description="""Why the value is not known; empty when it is.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })
    element: Optional[str] = Field(default=None, description="""For a parameter leaf: the id of the parameter element it read, so an explanation reaches the row and its source. Absent when no row was read or chosen.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'CalcStep', 'Label']} })

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

    conclusion: RowRef = Field(default=..., description="""The row it explains, (subject, value, state, reason), in the rule's view (or a version's view, for a version named as rule@version).""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep', 'Witness', 'CalcWitness']} })
    rule: str = Field(default=..., description="""The calculation rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapPremise', 'CalcWitness']} })
    version: Optional[str] = Field(default=None, description="""The chosen version; empty when none was chosen.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'PackInfo', 'ImportedPack']} })
    valid_at: Optional[str] = Field(default=None, description="""The evaluation date the version was chosen on (ISO date); empty when there is none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    known_at: Optional[str] = Field(default=None, description="""The knowledge date the version was chosen on (ISO date); empty when there is none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    definition: Optional[str] = Field(default=None, description="""The name of the definition that applies; empty when none applies.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    value: Optional[str] = Field(default=None, description="""Canonical text of the result; empty unless the state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })
    state: ValueState = Field(default=..., description="""State of the result.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })
    reason: Optional[str] = Field(default=None, description="""Why the result is not known; empty when it is.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })
    premises: Optional[list[RowRef]] = Field(default=None, description="""The other conclusions it read: rows of derived relations and the results of other calculation rules.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GapAnswer', 'Witness', 'CalcWitness']} })
    reads: list[str] = Field(default=..., description="""Every relation the evaluation reads, sorted: absences decide states there (a missing fact is unknown or not_applicable, two values invalid), so a role sees the result only while it reads each in full (decision O8).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    steps: Optional[list[CalcStep]] = Field(default=None, description="""The evaluated nodes, in evaluation order: the conditions of all definitions in program order, then the value of the definition that applies; a node before its arguments.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Question', 'Answer', 'CalcWitness']} })


class Proof(ConfiguredBaseModel):
    """
    The chosen proof for one conclusion; acyclic, shortest first, then lexicographic.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    root: RowRef = Field(default=..., description="""The conclusion this proof explains.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })
    manifest_id: str = Field(default=..., description="""The manifest this proof is checked against.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'BoundSweepList', 'Proof']} })
    witnesses: Optional[list[Witness]] = Field(default=None, description="""The witnesses of the proof graph.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Proof']} })
    calc_witnesses: Optional[list[CalcWitness]] = Field(default=None, description="""The calculation witnesses of the proof graph (decision W12).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Proof']} })
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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })
    value: Optional[str] = Field(default=None, description="""Canonical text form; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })
    state: ValueState = Field(default=..., description="""State of the value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })

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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })
    minor_units: Optional[int] = Field(default=None, description="""Integer minor units; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'Quantity']} })
    currency: str = Field(default=..., description="""ISO 4217 currency code.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'SemanticType', 'Attribute', 'RuleColumn']} })
    state: ValueState = Field(default=..., description="""State of the amount.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })

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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })
    minor_units: Optional[int] = Field(default=None, description="""Integer minor units; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'Quantity']} })
    scale: Optional[int] = Field(default=None, description="""Number of decimals in minor_units: kg with scale 0, g with scale 3.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ChannelBinding', 'Quantity']} })
    unit: str = Field(default=..., description="""UCUM unit.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Quantity', 'SemanticType']} })
    state: ValueState = Field(default=..., description="""State of the quantity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })

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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })
    numerator: Optional[int] = Field(default=None, description="""Numerator; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ratio']} })
    denominator: Optional[int] = Field(default=None, description="""Denominator of at least 1; absent unless state is known.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Ratio']} })
    state: ValueState = Field(default=..., description="""State of the ratio.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'NestPerspective',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio']} })

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
    rows: Optional[list[SourceEntry]] = Field(default=None, description="""Exact RowRefs with complete sources; keys must be canonical and actually occur in the companion fact file.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerCounts', 'MatrixSheet', 'TimelineSheet', 'SourceSidecar']} })


class SourceSelector(ConfiguredBaseModel):
    """
    A record, or one cell of it, using the fact file's typed kind and identifier.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    id: Union[int, str] = Field(default=..., description="""The identifier in the root kind's SQL type; a boolean is never an integer identifier.""", json_schema_extra = { "linkml_meta": {'any_of': [{'range': 'string'}, {'range': 'integer'}],
         'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    slot: Optional[str] = Field(default=None, description="""When present, a slot of this kind, including inherited slots.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SweepCellRef',
                       'ChannelBinding',
                       'ImageBinding',
                       'TimelineMark',
                       'WaterfallPart',
                       'SourceSelector']} })

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
    kind: Optional[SourceKind] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    name: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    revision: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    position: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep',
                       'Aggregate',
                       'SourceRecord',
                       'Source',
                       'RuleLiteral',
                       'RuleAggregate']} })
    url: Optional[str] = Field(default=None, description="""Absolute HTTP(S) document or API/resource URL; a locator, never fetched by contract validation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    retrieved_at: Optional[datetime ] = Field(default=None, description="""When the document bytes were retrieved; required for a document without a version. This is not an observation's event_time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    fragment_sha256: Optional[str] = Field(default=None, description="""SHA-256 of the exact UTF-8 bytes of the cited short fragment; no fragment text is stored in this contract.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    ownership: Optional[SourceOwnership] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    licence: Optional[str] = Field(default=None, description="""The declared SPDX id, LicenseRef or licence file in the pack, verified by the importer; validation makes no claim about legal permission.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source', 'Icon']} })
    attribution: Optional[str] = Field(default=None, description="""The required name/credit for the third-party source.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    reason: Optional[str] = Field(default=None, description="""Message key explaining why this row remains a fact instead of being derived.""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })

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

    kind: SourceKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    name: str = Field(default=..., description="""The repository, file, proposal, query, tool or register.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    revision: Optional[str] = Field(default=None, description="""The pinned revision: required for a Git commit or a proposal manifest; a document version or a query's API/schema version when supplied.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    position: str = Field(default=..., description="""Where in the source: Git path#section or path#L12-L24, a document section/paragraph anchor, a query's resource version or date, a JSON pointer, line, row and column, offset or delta step. Existing locators stay valid.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep',
                       'Aggregate',
                       'SourceRecord',
                       'Source',
                       'RuleLiteral',
                       'RuleAggregate']} })
    url: Optional[str] = Field(default=None, description="""Absolute HTTP(S) document or API/resource URL; a locator, never fetched by contract validation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    retrieved_at: Optional[datetime ] = Field(default=None, description="""When the document bytes were retrieved; required for a document without a version. This is not an observation's event_time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    fragment_sha256: Optional[str] = Field(default=None, description="""SHA-256 of the exact UTF-8 bytes of the cited short fragment; no fragment text is stored in this contract.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    ownership: Optional[SourceOwnership] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source']} })
    licence: Optional[str] = Field(default=None, description="""The declared SPDX id, LicenseRef or licence file in the pack, verified by the importer; validation makes no claim about legal permission.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source', 'Icon']} })
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
    sources: list[Source] = Field(default=..., description="""Every source of the row; a writer sorts and deduplicates them.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'SourceEntry', 'Channels']} })
    reason: Optional[str] = Field(default=None, description="""Message key explaining why this row remains a fact instead of being derived (S29).""", json_schema_extra = { "linkml_meta": {'domain_of': ['UndecidedRow',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'SourceRecord',
                       'SourceEntry']} })


class SourceSet(ConfiguredBaseModel):
    """
    The manifest's reference to a role's file of source entries.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/source'})

    role: str = Field(default=..., description="""The role whose base rows the entries describe.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ColorToken',
                       'StrokeToken',
                       'SizeToken',
                       'TypefaceToken',
                       'HouseStyleColor',
                       'SourceSet']} })
    uri: str = Field(default=..., description="""The location of the source-entry file.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSet']} })
    sha256: str = Field(default=..., description="""SHA-256 of the source-entry file bytes.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSet', 'ImportedPack', 'Icon']} })

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


class Bundle(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle', 'tree_root': True})

    format: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Answer', 'Bundle']} })
    pack: PackInfo = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'SchemaFile']} })
    imports: Optional[list[ImportedPack]] = Field(default=None, description="""Every pack this pack imports, also indirectly, by name; each pinned on its hash.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    schemas: list[SchemaFile] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    layers: list[Layer] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Filter', 'Bundle']} })
    order: list[str] = Field(default=..., description="""Kind ids by layer, then by id. Map layouts read left to right in this order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'SlotRoles']} })
    kinds: list[Kind] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Key', 'Bundle', 'Channels']} })
    arrows: Optional[list[Arrow]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Key', 'Bundle', 'Channels']} })
    attributes: Optional[list[Attribute]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Icon', 'IconElement']} })
    enums: Optional[list[PackEnum]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    unique_keys: Optional[list[UniqueKey]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    path_equations: Optional[list[PathEquation]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    rules: Optional[list[Rule]] = Field(default=None, description="""Derivation rules; from M2 on.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Filter', 'Bundle']} })
    relations: Optional[list[DerivedRelation]] = Field(default=None, description="""Relations derived by rules (sets, contracts/rules.yaml); from M2 on.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Bundle']} })
    checks: Optional[list[CheckView]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweepCell', 'Bundle', 'DerivedRelation']} })
    pages: Optional[list[Page]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    labels: Optional[list[Label]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    messages: list[MessageResource] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    channels: Channels = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Key', 'Bundle']} })
    jurisdictions: Optional[list[str]] = Field(default=None, description="""Reserved for std-jurisdiction; empty in M1.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    questions: Optional[list[Question]] = Field(default=None, description="""The explanation questions (contracts/explain.yaml): imported ones first, then the pack's own. Absent when there are none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    reader_questions: Optional[list[ReaderQuestion]] = Field(default=None, description="""The reader questions (contracts/explain.yaml, RV-C04): imported ones first, then the pack's own. Absent when there are none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })
    reasons: Optional[list[ReasonIri]] = Field(default=None, description="""The IRI of every reason code of the pack's named outcomes, by code (docs/ring2/iris.md section 4). Only when pack.yaml declares `iri:` (contracts/pack.yaml, PackIri); absent otherwise.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle']} })

    @field_validator('format')
    def pattern_format(cls, v):
        pattern=re.compile(r"^rede\.schema-bundle/1$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid format format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid format format: {v}"
            raise ValueError(err_msg)
        return v


class PackInfo(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    version: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'PackInfo', 'ImportedPack']} })
    default_language: str = Field(default=..., description="""BCP 47 code.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PackInfo']} })
    base: Optional[str] = Field(default=None, description="""The pack's `base` as pack.yaml `iri:` declares it (contracts/pack.yaml, PackIri): the IRI under which one publication's names hang (docs/ring2/iris.md section 4). Absent: the pack declares none, and a reader takes its stand-in.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PackInfo', 'SemanticType']} })

    @field_validator('base')
    def pattern_base(cls, v):
        pattern=re.compile(r"^https://[^ #?]+/$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid base format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid base format: {v}"
            raise ValueError(err_msg)
        return v


class ReasonIri(ConfiguredBaseModel):
    """
    A reason code and its IRI, `<namespace>reason/<code>`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    code: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic', 'ReasonIri']} })
    iri: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReasonIri', 'Kind']} })

    @field_validator('code')
    def pattern_code(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid code format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid code format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('iri')
    def pattern_iri(cls, v):
        pattern=re.compile(r"^https://[^ #?]+/reason/[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid iri format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid iri format: {v}"
            raise ValueError(err_msg)
        return v


class ImportedPack(ConfiguredBaseModel):
    """
    A pack whose schema modules are part of this pack, pinned on the hash of its files.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    version: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness', 'PackInfo', 'ImportedPack']} })
    sha256: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSet', 'ImportedPack', 'Icon']} })

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v

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


class SchemaFile(ConfiguredBaseModel):
    """
    One schema module, a LinkML file of this pack or of an imported pack.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    file: str = Field(default=..., description="""The path within its own pack.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Span', 'RuleOrigin', 'Icon']} })
    module: str = Field(default=..., description="""`<path under schema/>`, or `<pack>:<path>` for a module of an imported pack.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Kind', 'Rule', 'DerivedRelation']} })
    pack: str = Field(default=..., description="""The pack the module belongs to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'SchemaFile']} })


class Sentence(ConfiguredBaseModel):
    """
    A message id and its arguments. Every argument value is an element id; the viewer fills `$name` with that element's label and `$name_gender` with its gender, or `other`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'Sentence', 'Rule']} })
    args: Any = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic', 'Sentence']} })
    id: Optional[str] = Field(default=None, description="""MOD2: `sentence:` and the stable id of the element it is said of. Present on the sentence of a kind, a slot, a unique key and a path equation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    span: Optional[Span] = Field(default=None, description="""MOD2: where that element is declared.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })


class Span(ConfiguredBaseModel):
    """
    MOD2: where an element is written. The file as a rule origin names it (relative to its pack, `<pack>:` before a file of an imported pack); line and column count from 1, as decimal text.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    file: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Span', 'RuleOrigin', 'Icon']} })
    line: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet', 'Span', 'RuleOrigin']} })
    column: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'Span']} })

    @field_validator('line')
    def pattern_line(cls, v):
        pattern=re.compile(r"^[1-9][0-9]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid line format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid line format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('column')
    def pattern_column(cls, v):
        pattern=re.compile(r"^[1-9][0-9]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid column format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid column format: {v}"
            raise ValueError(err_msg)
        return v


class Kind(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle',
         'rules': [{'postconditions': {'slot_conditions': {'ends': {'name': 'ends',
                                                                    'required': True}}},
                    'preconditions': {'slot_conditions': {'relationship': {'name': 'relationship',
                                                                           'value_presence': 'PRESENT'}}}},
                   {'postconditions': {'slot_conditions': {'owner': {'name': 'owner',
                                                                     'required': True}}},
                    'preconditions': {'slot_conditions': {'plane': {'name': 'plane',
                                                                    'value_presence': 'PRESENT'}}}},
                   {'postconditions': {'slot_conditions': {'plane': {'name': 'plane',
                                                                     'required': True}}},
                    'preconditions': {'slot_conditions': {'owner': {'name': 'owner',
                                                                    'value_presence': 'PRESENT'}}}}]})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    stable_id: str = Field(default=..., description="""MOD2: the id that a rename and an added element leave as it is (docs/compiler.md#stable-ids-and-spans). `id` stays the name the engine, labels and messages use.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'Rule']} })
    span: Span = Field(default=..., description="""MOD2: where it is declared.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })
    renamed_from: Optional[str] = Field(default=None, description="""MOD2: the first name of a renamed class (annotation `renamed_from`), which its stable id keeps.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    class_: str = Field(default=..., alias="class", description="""The LinkML class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    layer: Layer = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    parent: Optional[str] = Field(default=None, description="""The kind this one is a part of (is_a).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    abstract: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    identifier: Optional[str] = Field(default=None, description="""The identifying slot; none for a kind that only exists inlined.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    id_type: ValueType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    identifier_patterns: Optional[list[str]] = Field(default=None, description="""Regular expressions every id must match (pattern on the identifier or its type).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    module: str = Field(default=..., description="""The schema module that declares the class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Kind', 'Rule', 'DerivedRelation']} })
    table: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    world: Optional[World] = Field(default=None, description="""What a missing row means (decision W6): closed, not true; open, unknown. Left out: closed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'DerivedRelation']} })
    sentence: Optional[Sentence] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'UniqueKey', 'PathEquation', 'CheckView']} })
    name_attribute: Optional[str] = Field(default=None, description="""The attribute whose value names an element of this kind: its slot with `slot_uri: rdfs:label`, declared here or inherited. Left out: the kind has none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    name_arrows: Optional[list[str]] = Field(default=None, description="""For a kind without a name attribute that is identified by its ends (a unique key of single-valued arrows only, the first one): those arrows, in the key's order, if one of their ends has a name. An element is named by the names of its ends. Left out: it is named by its id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    slot_roles: Optional[SlotRoles] = Field(default=None, description="""Recognised slot_uri roles, declared here or inherited, as slot element ids (S26). Left out when none exist. name_attribute remains for existing readers.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    relationship: Optional[bool] = Field(default=None, description="""Present as true for a kind declared with represents_relationship (S27); its ends name it. Left out: an ordinary kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    ends: Optional[list[str]] = Field(default=None, description="""For a relationship: the distinct single-valued arrows of its identifying unique key, in key order, as slot element ids (S27).""", min_length=2, json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    plane: Optional[Plane] = Field(default=None, description="""control for a kind of decided values (DV1; Reckon Data L0 section 3.7): it has a required, single-valued slot `decision`, and admission takes its rows only from a reviewed proposal. Declared on this class; its subkinds are control kinds too. Left out: a data-plane kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    owner: Optional[str] = Field(default=None, description="""For a control kind: the role or team that reviews a change to it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind']} })
    iri: Optional[str] = Field(default=None, description="""The kind's lasting IRI, `<namespace><class>`, from pack.yaml `iri:` of the pack that declares it, else of the compiled pack (contracts/pack.yaml, PackIri; docs/ring2/iris.md section 4). Absent when neither declares the block: a reader takes `<base><class>`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReasonIri', 'Kind']} })
    fold: Optional[bool] = Field(default=None, description="""Present as true for a helper kind the pack folds (`annotations: {explain: fold}`): an explanation shows no step of its own for it. Display only. Left out: not folded.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets', 'SheetSign', 'Kind', 'DerivedRelation']} })

    @field_validator('stable_id')
    def pattern_stable_id(cls, v):
        pattern=re.compile(r"^([a-z0-9_:/-]+/)?[A-Za-z][A-Za-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid stable_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid stable_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('iri')
    def pattern_iri(cls, v):
        pattern=re.compile(r"^https://[^ #?]+/[A-Z][A-Za-z0-9]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid iri format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid iri format: {v}"
            raise ValueError(err_msg)
        return v


class SlotRoles(ConfiguredBaseModel):
    """
    One single-valued attribute per recognised role of a kind (S26).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    name: Optional[str] = Field(default=None, description="""rdfs:label: the text that names an element.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    description: Optional[str] = Field(default=None, description="""schema:description: the element's description, as text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SlotRoles']} })
    image: Optional[str] = Field(default=None, description="""schema:image: the attribute naming a file in assets/ (B10).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SlotRoles']} })
    order: Optional[str] = Field(default=None, description="""schema:position: a whole-number ordering value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'SlotRoles']} })
    valid_from: Optional[str] = Field(default=None, description="""schema:validFrom: the start of validity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SlotRoles']} })
    valid_until: Optional[str] = Field(default=None, description="""schema:validThrough: the end of validity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SlotRoles']} })
    known_from: Optional[str] = Field(default=None, description="""prov:generatedAtTime: when the row became known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SlotRoles']} })


class Slot(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True, 'from_schema': 'https://rede.dev/contracts/bundle'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    stable_id: str = Field(default=..., description="""MOD2: the id that a rename and an added element leave as it is (docs/compiler.md#stable-ids-and-spans). `id` stays the name the engine, labels and messages use.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'Rule']} })
    span: Span = Field(default=..., description="""MOD2: where it is declared.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })
    renamed_from: Optional[str] = Field(default=None, description="""MOD2: the first name of a renamed slot (annotation `renamed_from`), which its stable id keeps.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    kind: str = Field(default=..., description="""The kind that declares the slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    required: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    table: str = Field(default=..., description="""The engine relation `<kind>__<slot>`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    multivalued: bool = Field(default=..., description="""A multivalued slot is a link kind: any number of rows per element, without a functionality check.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    minimum_cardinality: Optional[str] = Field(default=None, description="""Least number of distinct values; only on a multivalued slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    maximum_cardinality: Optional[str] = Field(default=None, description="""Most number of distinct values; only on a multivalued slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    world: Optional[World] = Field(default=None, description="""What a missing row means (decision W6): closed, not true; open, unknown. Left out: closed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'DerivedRelation']} })
    semantic: SemanticType = Field(default=..., description="""What the slot's value means (B10, S3b), so a consumer reads it instead of guessing. Cardinality and world stay on the slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot', 'DerivedRelation']} })
    sentence: Sentence = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'UniqueKey', 'PathEquation', 'CheckView']} })

    @field_validator('stable_id')
    def pattern_stable_id(cls, v):
        pattern=re.compile(r"^.+#[A-Za-z][A-Za-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid stable_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid stable_id format: {v}"
            raise ValueError(err_msg)
        return v


class SemanticType(ConfiguredBaseModel):
    """
    The meaning of one value (B10, S3b), projected from the compiler's one type model (B09, `rede_compiler.types.Type`). Only what the model knows is written; a field without a value is left out, and nothing is inferred from a name. A dimension is not modelled yet (P10.3).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    case: SemanticCase = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType']} })
    base: SemanticBase = Field(default=..., description="""What is stored. A reference stores its target root's identifier type.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PackInfo', 'SemanticType']} })
    range: Optional[str] = Field(default=None, description="""The schema's name as written: the LinkML type, enum or class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType']} })
    enum: Optional[str] = Field(default=None, description="""An enum value: the enum it belongs to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType', 'Attribute']} })
    open: Optional[bool] = Field(default=None, description="""Present as true for an open enum: values beyond the declared ones.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType']} })
    target: Optional[str] = Field(default=None, description="""A reference: the kind of the element it names.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType', 'Arrow']} })
    currency: Optional[str] = Field(default=None, description="""Money: whole minor units of this ISO 4217 currency.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'SemanticType', 'Attribute', 'RuleColumn']} })
    unit: Optional[str] = Field(default=None, description="""A quantity: a number of this unit, as written; no conversion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Quantity', 'SemanticType']} })
    derived: Optional[str] = Field(default=None, description="""A derived value: the calc rule (or `rule@version`) or derived relation that computes it, its binding.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType']} })

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


class Arrow(Slot):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    target: str = Field(default=..., description="""The kind the arrow points to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType', 'Arrow']} })
    inlined: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Arrow']} })
    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    stable_id: str = Field(default=..., description="""MOD2: the id that a rename and an added element leave as it is (docs/compiler.md#stable-ids-and-spans). `id` stays the name the engine, labels and messages use.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'Rule']} })
    span: Span = Field(default=..., description="""MOD2: where it is declared.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })
    renamed_from: Optional[str] = Field(default=None, description="""MOD2: the first name of a renamed slot (annotation `renamed_from`), which its stable id keeps.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    kind: str = Field(default=..., description="""The kind that declares the slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    required: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    table: str = Field(default=..., description="""The engine relation `<kind>__<slot>`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    multivalued: bool = Field(default=..., description="""A multivalued slot is a link kind: any number of rows per element, without a functionality check.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    minimum_cardinality: Optional[str] = Field(default=None, description="""Least number of distinct values; only on a multivalued slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    maximum_cardinality: Optional[str] = Field(default=None, description="""Most number of distinct values; only on a multivalued slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    world: Optional[World] = Field(default=None, description="""What a missing row means (decision W6): closed, not true; open, unknown. Left out: closed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'DerivedRelation']} })
    semantic: SemanticType = Field(default=..., description="""What the slot's value means (B10, S3b), so a consumer reads it instead of guessing. Cardinality and world stay on the slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot', 'DerivedRelation']} })
    sentence: Sentence = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'UniqueKey', 'PathEquation', 'CheckView']} })

    @field_validator('stable_id')
    def pattern_stable_id(cls, v):
        pattern=re.compile(r"^.+#[A-Za-z][A-Za-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid stable_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid stable_id format: {v}"
            raise ValueError(err_msg)
        return v


class Attribute(Slot):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    type: ValueType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute', 'RuleTerm', 'RuleVariable', 'RuleColumn']} })
    schema_type: str = Field(default=..., description="""The LinkML range, for example a pack type such as Cents.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute']} })
    derivation: Derivation = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Attribute']} })
    enum: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['SemanticType', 'Attribute']} })
    minimum: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute']} })
    maximum: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute']} })
    patterns: Optional[list[str]] = Field(default=None, description="""Regular expressions every value must match (pattern on the slot or its type); see docs/compiler.md for the portable subset.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute']} })
    constant: Optional[str] = Field(default=None, description="""The one allowed value (equals_string or equals_number); an integer as decimal text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute']} })
    currency: Optional[str] = Field(default=None, description="""An amount: the integer values are whole minor units of this ISO 4217 currency (annotation `currency` on the slot or its type). The viewer shows them as money, exactly (contracts/value.yaml, Amount).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'SemanticType', 'Attribute', 'RuleColumn']} })
    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    stable_id: str = Field(default=..., description="""MOD2: the id that a rename and an added element leave as it is (docs/compiler.md#stable-ids-and-spans). `id` stays the name the engine, labels and messages use.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'Rule']} })
    span: Span = Field(default=..., description="""MOD2: where it is declared.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })
    renamed_from: Optional[str] = Field(default=None, description="""MOD2: the first name of a renamed slot (annotation `renamed_from`), which its stable id keeps.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    kind: str = Field(default=..., description="""The kind that declares the slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    required: bool = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    table: str = Field(default=..., description="""The engine relation `<kind>__<slot>`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot']} })
    multivalued: bool = Field(default=..., description="""A multivalued slot is a link kind: any number of rows per element, without a functionality check.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    minimum_cardinality: Optional[str] = Field(default=None, description="""Least number of distinct values; only on a multivalued slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    maximum_cardinality: Optional[str] = Field(default=None, description="""Most number of distinct values; only on a multivalued slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot']} })
    world: Optional[World] = Field(default=None, description="""What a missing row means (decision W6): closed, not true; open, unknown. Left out: closed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'DerivedRelation']} })
    semantic: SemanticType = Field(default=..., description="""What the slot's value means (B10, S3b), so a consumer reads it instead of guessing. Cardinality and world stay on the slot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot', 'DerivedRelation']} })
    sentence: Sentence = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'UniqueKey', 'PathEquation', 'CheckView']} })

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

    @field_validator('stable_id')
    def pattern_stable_id(cls, v):
        pattern=re.compile(r"^.+#[A-Za-z][A-Za-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid stable_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid stable_id format: {v}"
            raise ValueError(err_msg)
        return v


class PackEnum(ConfiguredBaseModel):
    """
    An enum of the pack with its values. Not named Enum: generated Python would shadow enum.Enum.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    values: list[str] = Field(default=..., description="""Element ids of the permissible values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PackEnum']} })


class UniqueKey(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    slots: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['UniqueKey']} })
    sentence: Sentence = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'UniqueKey', 'PathEquation', 'CheckView']} })


class PathEquation(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    left: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PathEquation']} })
    right: list[str] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['PathEquation']} })
    sentence: Sentence = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'UniqueKey', 'PathEquation', 'CheckView']} })


class Rule(ConfiguredBaseModel):
    """
    A derivation rule as the viewer needs it. The message `rule.<id>` is optional in a pack; the viewer then shows the rule id. Its variables are named without '?' in the message.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    id: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    stable_id: str = Field(default=..., description="""MOD2: the id that a rename and an added element leave as it is (docs/compiler.md#stable-ids-and-spans). `id` stays the name the engine, labels and messages use.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'Rule']} })
    span: Span = Field(default=..., description="""MOD2: where its head is written; for a rule a view generates, the view in views.yaml.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })
    message: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'Sentence', 'Rule']} })
    relation: Optional[str] = Field(default=None, description="""The derived relation of the head.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    module: Optional[str] = Field(default=None, description="""The rule module (rules/<module>.dl).""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Kind', 'Rule', 'DerivedRelation']} })
    variables: Optional[list[RuleVariable]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    aggregates: Optional[list[RuleAggregate]] = Field(default=None, description="""The aggregates of the rule, in the order of the rule IR (contracts/rules.yaml), which the checker reads: what each folds. Left out for a rule without aggregates. A witness names its aggregate by `position` (contracts/proof.yaml), so a reader never guesses the function from the numbers.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'Rule']} })
    head: RuleAtom = Field(default=..., description="""The head of the rule (MOD14): its relation and terms, each typed by its column.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    body: list[RuleLiteral] = Field(default=..., description="""Every literal of the body in source order (MOD14), from the rule IR: atoms, comparisons, assignments and aggregates. A rule a view generates has no order as written; its body is its atoms, then its aggregates, assignments and comparisons, each in the order of the rule IR. Published for every role (O10).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Rule']} })
    origin: Optional[RuleOrigin] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['NestPerspective', 'Rule']} })

    @field_validator('stable_id')
    def pattern_stable_id(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9_]*~[0-9a-f]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid stable_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid stable_id format: {v}"
            raise ValueError(err_msg)
        return v


class RuleAtom(ConfiguredBaseModel):
    """
    A relation and its terms.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    relation: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    terms: list[RuleTerm] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['RuleAtom', 'RuleLiteral']} })


class RuleTerm(ConfiguredBaseModel):
    """
    One term, as the rule IR writes it, with its type: an atom's term that of its column; another a variable's own, a constant compared with a variable that variable's, any other constant that of its own form.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    kind: RuleTermKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    value: str = Field(default=..., description="""The term as in the rule IR: `?name`, `_` or the constant.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })
    type: RuleColumnType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute', 'RuleTerm', 'RuleVariable', 'RuleColumn']} })


class RuleLiteral(ConfiguredBaseModel):
    """
    One literal of a rule body (MOD14). The rule IR (contracts/rules.yaml) holds atoms, aggregates, assignments and comparisons in four lists; here they are one list, in the order the rule was written. Filtered to atoms, it is the IR's `body`; to aggregates, its `aggregates`.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle',
         'rules': [{'postconditions': {'slot_conditions': {'relation': {'name': 'relation',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'atom',
                                                                   'name': 'kind'}}}},
                   {'postconditions': {'slot_conditions': {'op': {'name': 'op',
                                                                  'required': True},
                                                           'polarity': {'equals_string': 'positive',
                                                                        'name': 'polarity'}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'comparison',
                                                                   'name': 'kind'}}}},
                   {'postconditions': {'slot_conditions': {'op': {'name': 'op',
                                                                  'required': True},
                                                           'polarity': {'equals_string': 'positive',
                                                                        'name': 'polarity'},
                                                           'result': {'name': 'result',
                                                                      'required': True}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'assignment',
                                                                   'name': 'kind'}}}},
                   {'postconditions': {'slot_conditions': {'aggregate_position': {'name': 'aggregate_position',
                                                                                  'required': True},
                                                           'function': {'name': 'function',
                                                                        'required': True},
                                                           'polarity': {'equals_string': 'positive',
                                                                        'name': 'polarity'},
                                                           'relation': {'name': 'relation',
                                                                        'required': True},
                                                           'result': {'name': 'result',
                                                                      'required': True}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'aggregate',
                                                                   'name': 'kind'}}}}]})

    kind: RuleLiteralKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    position: int = Field(default=..., description="""The place of the literal in the body, from 1.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep',
                       'Aggregate',
                       'SourceRecord',
                       'Source',
                       'RuleLiteral',
                       'RuleAggregate']} })
    polarity: RulePolarity = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Premise', 'RuleLiteral']} })
    relation: Optional[str] = Field(default=None, description="""The relation an atom or an aggregate reads.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    op: Optional[RuleOperator] = Field(default=None, description="""The operator of a comparison or an assignment.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep', 'RuleLiteral']} })
    terms: list[RuleTerm] = Field(default=..., description="""An atom's or an aggregate's terms, by column; a comparison's or an assignment's left and right.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RuleAtom', 'RuleLiteral']} })
    result: Optional[RuleTerm] = Field(default=None, description="""The variable an assignment or an aggregate binds; an integer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate', 'RuleLiteral']} })
    function: Optional[AggregateFunction] = Field(default=None, description="""The function of an aggregate.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RuleLiteral', 'RuleAggregate']} })
    over: Optional[str] = Field(default=None, description="""The column that an aggregate's `sum`, `min` or `max` folds; left out for `count`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose', 'RuleLiteral', 'RuleAggregate']} })
    aggregate_position: Optional[int] = Field(default=None, description="""An aggregate's place in `aggregates` (from 0), the `position` a witness names it by.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['RuleLiteral']} })


class RuleAggregate(ConfiguredBaseModel):
    """
    One aggregate of a rule, said once per rule and not per witness: the function is the rule's, not a row's.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    position: int = Field(default=..., description="""The place of the aggregate in the rule (from 0), as `position` on a witness's aggregate.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerStep',
                       'Aggregate',
                       'SourceRecord',
                       'Source',
                       'RuleLiteral',
                       'RuleAggregate']} })
    relation: str = Field(default=..., description="""The relation that is aggregated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    function: AggregateFunction = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['RuleLiteral', 'RuleAggregate']} })
    over: Optional[str] = Field(default=None, description="""The column that `sum`, `min` or `max` folds; left out for `count`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Suppose', 'RuleLiteral', 'RuleAggregate']} })


class RuleVariable(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    type: RuleColumnType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute', 'RuleTerm', 'RuleVariable', 'RuleColumn']} })

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^\?[a-z][a-z0-9_]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class RuleOrigin(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    file: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Span', 'RuleOrigin', 'Icon']} })
    line: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['TrackSheet', 'Span', 'RuleOrigin']} })

    @field_validator('line')
    def pattern_line(cls, v):
        pattern=re.compile(r"^(0|[1-9][0-9]*)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid line format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid line format: {v}"
            raise ValueError(err_msg)
        return v


class DerivedRelation(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    extend: Optional[bool] = Field(default=None, description="""True: the owning pack explicitly permits consumers to add rules (S28). Without rules the relation is empty.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DerivedRelation']} })
    id: str = Field(default=..., description="""The relation name; also the element id of its label.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    module: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Kind', 'Rule', 'DerivedRelation']} })
    explain: ExplainMode = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['DerivedRelation']} })
    columns: list[RuleColumn] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion', 'MatrixSheet', 'DerivedRelation']} })
    world: Optional[World] = Field(default=None, description="""What a missing row means (decision W6): closed, not true; open, unknown. Left out: closed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'DerivedRelation']} })
    absence: Optional[bool] = Field(default=None, description="""True: the relation says what is not recorded (`// @absence`); closed, and it may negate an open relation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DerivedRelation']} })
    semantic: Optional[SemanticType] = Field(default=None, description="""For a calculation's view (`calc`): the type of its value column, derived by the rule it names, with its unit (B10). Left out: not a calculation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Slot', 'DerivedRelation']} })
    outcome: Optional[str] = Field(default=None, description="""A named outcome (decision W7): the kind whose every element has one state (column `state`) and a reason (column `reason`, message `reason.<reason>`).""", json_schema_extra = { "linkml_meta": {'domain_of': ['DerivedRelation']} })
    closes: Optional[str] = Field(default=None, description="""The derived relation this one closes (decision W14, `// @closes <relation>`): a row states, for its key, that no row of that relation holds there, and its proof says why. The key is a prefix of that relation's columns. The invariant `<id>_closes_<relation>` holds the two apart.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DerivedRelation']} })
    checks: Optional[list[str]] = Field(default=None, description="""The engine views that check a named outcome (`<relation>__total`, `<relation>__state`); a row in one is a red check.""", json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweepCell', 'Bundle', 'DerivedRelation']} })
    fold: Optional[bool] = Field(default=None, description="""Present as true for a helper relation the pack folds (`// @explain fold`): an explanation shows the premises of its step in its place and no step named after it. Display only, and apart from `explain`, which says how its witnesses are kept; the rule IR does not carry it. Left out: not folded.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets', 'SheetSign', 'Kind', 'DerivedRelation']} })
    calc: Optional[str] = Field(default=None, description="""A calculation's view (decision W12): the rule, or rule@version for a version another rule names. Its rows are (subject, value, state, reason), each explained by a CalcWitness; module calc.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DerivedRelation']} })


class RuleColumn(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    type: RuleColumnType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Attribute', 'RuleTerm', 'RuleVariable', 'RuleColumn']} })
    currency: Optional[str] = Field(default=None, description="""An amount, where the rules determine it: whole minor units of this ISO 4217 currency, as `currency` on an Attribute. Derived, never declared: the column is bound to an amount attribute, or to a `sum`, `min` or `max` over an amount column, or to a sum or difference of such amounts, in every rule of the relation. A count, a product and a quotient have none. Two currencies in one variable or one column is a compiler error.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'SemanticType', 'Attribute', 'RuleColumn']} })

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


class CheckView(ConfiguredBaseModel):
    """
    One logical check: a check kind on one slot, key or rule. With decision E11 the engine holds the rows of all logical checks of one kind in one view (`relation`), and which slot has which check is a metadata row.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    view: str = Field(default=..., description="""The name of the logical check, `<kind>__<subject>__<check>` or `<kind>__<check>`: `validation_result.info` and the manifest's check name. Until E11 is built, also the engine view.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CheckView']} })
    relation: Optional[str] = Field(default=None, description="""The engine view that holds this check's rows, `rede__<check>` (E11). Absent until E11 step 2; then required.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'RelationCount',
                       'DifferenceEntry',
                       'AnswerNode',
                       'GapPremise',
                       'GapCandidate',
                       'EdgeSource',
                       'NestPerspective',
                       'ComparisonPart',
                       'RowRef',
                       'Aggregate',
                       'CalcStep',
                       'Rule',
                       'RuleAtom',
                       'RuleLiteral',
                       'RuleAggregate',
                       'CheckView']} })
    check: Check = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CheckView']} })
    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    subject: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CheckView']} })
    path: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep', 'CheckView', 'Page']} })
    sentence: Optional[Sentence] = Field(default=None, description="""`check.<check>` with the kind and slot as arguments (E11 step 5).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Kind', 'Slot', 'UniqueKey', 'PathEquation', 'CheckView']} })


class Page(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    kind: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext',
                       'DeltaStart',
                       'SweepCellRef',
                       'GapPremise',
                       'KindSign',
                       'ImageBinding',
                       'FlowNode',
                       'MatrixAxis',
                       'NestLevel',
                       'CardsPart',
                       'SourceSelector',
                       'SourceRecord',
                       'Source',
                       'Slot',
                       'UniqueKey',
                       'PathEquation',
                       'RuleTerm',
                       'RuleLiteral',
                       'CheckView',
                       'Page']} })
    path: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep', 'CheckView', 'Page']} })
    fields: Optional[list[str]] = Field(default=None, description="""Slot element ids, inherited slots included.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderContext', 'Cartouche', 'CardsPart', 'Page']} })


class Label(ConfiguredBaseModel):
    """
    One fact label(element, lang, text).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    element: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderColumn', 'CalcStep', 'Label']} })
    lang: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Label', 'MessageResource']} })
    text: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerExpression', 'Label']} })
    gender: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Label']} })


class MessageResource(ConfiguredBaseModel):
    """
    One MessageFormat 2 resource (`@locale`, `---`, then `id = message`).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    lang: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Label', 'MessageResource']} })
    resource: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['MessageResource']} })


class Channels(ConfiguredBaseModel):
    """
    The pack's part of the key; colour roles, glyphs and statuses come from std-view, and a house style gives the pack's own values for some of those roles.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    kinds: Optional[list[KindSign]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['AppliesTo', 'Filter', 'Key', 'Bundle', 'Channels']} })
    arrows: Optional[list[ArrowSign]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Key', 'Bundle', 'Channels']} })
    relief: Optional[ReliefSheet] = Field(default=None, description="""The pack's relief binding, by element id (`<kind>.<slot>`), checked by the compiler.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Sheets', 'SheetBindings', 'Channels']} })
    flows: Optional[list[FlowSheet]] = Field(default=None, description="""Flow sheets, by element id (`<kind>.<slot>`) and relation name, checked by the compiler.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    matrices: Optional[list[MatrixSheet]] = Field(default=None, description="""Matrix sheets, by element id (`<kind>.<slot>`) and relation name, checked by the compiler.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    timelines: Optional[list[TimelineSheet]] = Field(default=None, description="""Timeline sheets, by element id (`<kind>.<slot>`), checked by the compiler.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    nests: Optional[list[NestSheet]] = Field(default=None, description="""Nest sheets, by element id (`<kind>.<slot>`) and relation name, checked by the compiler.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    reports: Optional[list[ReportSheet]] = Field(default=None, description="""Reports, by element id (`<kind>.<slot>`), checked by the compiler.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    home: Optional[HomeSheet] = Field(default=None, description="""The pack home's hero and claim, from the pack's own channel table or one import's (one home per pack), checked by the compiler.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SheetBindings', 'Channels']} })
    house_style: Optional[HouseStyle] = Field(default=None, description="""The pack's house style, from the pack's own channel table or one import's (one house style per pack), checked by the compiler: palettes in the order light, dark, print, and in each the roles sorted by name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Channels']} })
    images: Optional[list[ImageBinding]] = Field(default=None, description="""The image slot per kind, by element id, sorted by kind (decision B10).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Channels']} })
    icons: Optional[list[Icon]] = Field(default=None, description="""The icons the kind signs name, by sha256, checked by the compiler against the safe list (docs/gui.md#icons-and-images).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Channels']} })
    sources: Optional[list[ChannelSource]] = Field(default=None, description="""MOD2: where each binding above is written, sorted by id. Left out when the pack binds nothing.""", json_schema_extra = { "linkml_meta": {'domain_of': ['AnswerNode', 'SourceEntry', 'Channels']} })


class ChannelSource(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    id: str = Field(default=..., description="""The binding: `<section>/<kind, arrow or sheet id>`, or the section of the one relief, home or house style.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ReaderQuestion',
                       'DeltaStart',
                       'SweepCellRef',
                       'HueRole',
                       'FlowSheet',
                       'MatrixSheet',
                       'TimelineSheet',
                       'NestPerspective',
                       'NestSheet',
                       'ReportSheet',
                       'SourceSelector',
                       'PackInfo',
                       'SchemaFile',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'PackEnum',
                       'UniqueKey',
                       'PathEquation',
                       'Rule',
                       'DerivedRelation',
                       'ChannelSource']} })
    span: Span = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ReckonDiagnostic',
                       'Sentence',
                       'Kind',
                       'Slot',
                       'Rule',
                       'ChannelSource']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^(relief|home|house_style|(kinds|arrows|flows|matrices|timelines|nests|reports|images)/.+)$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v


class Icon(ConfiguredBaseModel):
    """
    An icon of a kind (decision B10): an SVG of the pack, as a tree of safe elements, never as text. The viewer draws it in ink (currentColor) at icon.size; every paint in it is none or currentColor.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    sha256: str = Field(default=..., description="""SHA-256 of the file's bytes.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceSet', 'ImportedPack', 'Icon']} })
    file: str = Field(default=..., description="""The file in the pack that names it, such as icons/server.svg.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SchemaFile', 'Span', 'RuleOrigin', 'Icon']} })
    source: str = Field(default=..., description="""Where it comes from, pinned: <repository>@<commit>:<path>, or a URL.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Icon']} })
    licence: str = Field(default=..., description="""An SPDX id or a licence file in the pack.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SourceRecord', 'Source', 'Icon']} })
    view_box: str = Field(default=..., description="""The root's viewBox.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Icon']} })
    attributes: Optional[list[IconAttribute]] = Field(default=None, description="""The root's other attributes, such as stroke and stroke-width, sorted by name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Icon', 'IconElement']} })
    children: Optional[list[IconElement]] = Field(default=None, description="""The root's elements in document order.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Icon', 'IconElement']} })

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


class IconElement(ConfiguredBaseModel):
    """
    One element of an icon, from the safe list (g, path, circle, ellipse, rect, line, polyline, polygon).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    tag: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['IconElement']} })
    attributes: Optional[list[IconAttribute]] = Field(default=None, description="""Sorted by name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Bundle', 'Icon', 'IconElement']} })
    children: Optional[list[IconElement]] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['Icon', 'IconElement']} })


class IconAttribute(ConfiguredBaseModel):
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/bundle'})

    name: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['BoundSweep',
                       'SweepCheck',
                       'SourceRecord',
                       'Source',
                       'ImportedPack',
                       'SchemaFile',
                       'SlotRoles',
                       'Slot',
                       'RuleVariable',
                       'RuleColumn',
                       'IconAttribute']} })
    value: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['SeriesCell',
                       'BoundSweepCell',
                       'AnswerStep',
                       'ColorToken',
                       'HouseStyleColor',
                       'Binding',
                       'CalcStep',
                       'CalcWitness',
                       'Value',
                       'RuleTerm',
                       'IconAttribute']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
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
Key.model_rebuild()
Palette.model_rebuild()
ColorToken.model_rebuild()
StatusSign.model_rebuild()
ToneSign.model_rebuild()
HueRole.model_rebuild()
LegendSign.model_rebuild()
DifferenceSign.model_rebuild()
KindSign.model_rebuild()
ArrowSign.model_rebuild()
StrokeToken.model_rebuild()
Hatch.model_rebuild()
Arrowhead.model_rebuild()
SizeToken.model_rebuild()
TypefaceToken.model_rebuild()
Sheets.model_rebuild()
Metrics.model_rebuild()
Cartouche.model_rebuild()
KeyExtract.model_rebuild()
Fold.model_rebuild()
LensLayout.model_rebuild()
LensGlyph.model_rebuild()
Verb.model_rebuild()
SheetSign.model_rebuild()
ReliefLayout.model_rebuild()
ChannelGrammar.model_rebuild()
VisualScale.model_rebuild()
ChannelBinding.model_rebuild()
ImageBinding.model_rebuild()
ReliefSheet.model_rebuild()
TrackDepends.model_rebuild()
TrackSheet.model_rebuild()
EdgeSource.model_rebuild()
FlowNode.model_rebuild()
FlowSheet.model_rebuild()
MatrixAxis.model_rebuild()
MatrixSheet.model_rebuild()
TimelineMark.model_rebuild()
TimelineSheet.model_rebuild()
NestLevel.model_rebuild()
NestPerspective.model_rebuild()
NestSheet.model_rebuild()
CardsPart.model_rebuild()
WaterfallPart.model_rebuild()
MatrixPart.model_rebuild()
ComparisonPart.model_rebuild()
ReportPart.model_rebuild()
ReportSheet.model_rebuild()
HomeHero.model_rebuild()
HomeSheet.model_rebuild()
HouseStyle.model_rebuild()
HouseStylePalette.model_rebuild()
HouseStyleColor.model_rebuild()
SheetBindings.model_rebuild()
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
Bundle.model_rebuild()
PackInfo.model_rebuild()
ReasonIri.model_rebuild()
ImportedPack.model_rebuild()
SchemaFile.model_rebuild()
Sentence.model_rebuild()
Span.model_rebuild()
Kind.model_rebuild()
SlotRoles.model_rebuild()
Slot.model_rebuild()
SemanticType.model_rebuild()
Arrow.model_rebuild()
Attribute.model_rebuild()
PackEnum.model_rebuild()
UniqueKey.model_rebuild()
PathEquation.model_rebuild()
Rule.model_rebuild()
RuleAtom.model_rebuild()
RuleTerm.model_rebuild()
RuleLiteral.model_rebuild()
RuleAggregate.model_rebuild()
RuleVariable.model_rebuild()
RuleOrigin.model_rebuild()
DerivedRelation.model_rebuild()
RuleColumn.model_rebuild()
CheckView.model_rebuild()
Page.model_rebuild()
Label.model_rebuild()
MessageResource.model_rebuild()
Channels.model_rebuild()
ChannelSource.model_rebuild()
Icon.model_rebuild()
IconElement.model_rebuild()
IconAttribute.model_rebuild()
