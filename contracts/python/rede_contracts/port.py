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
     'description': 'One contract for every boundary port (decision O12a, PC1), '
                    'with three kinds. `in`: what arrives is an observation, never '
                    'a curated fact; it becomes one only through a proposal '
                    '(lifting, I29). `out`: runs only on a published epoch the '
                    'checker accepted, and writes a projection of it per role with '
                    'its own loss list. `effect`: changes the world exactly once '
                    'per approved plan hash through the effect journal (A03), and '
                    'its result returns as an observation. Each call is a '
                    'PortInvocation identified by its input hash (A02). This '
                    'contract replaces the contract parts of A02 '
                    '(contracts/plugin.yaml, a deprecated alias for one wave), I16 '
                    'and M01; I16 keeps the mapping format and the first out-port, '
                    'M01 the connector checklist and the loss-list format.',
     'id': 'https://rede.dev/contracts/port',
     'imports': ['linkml:types', 'connector'],
     'name': 'rede_port',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'port.yaml',
     'title': 'Port declarations',
     'types': {'DeclarationName': {'description': 'A name of a kind consumed or '
                                                  'produced, an operation, a '
                                                  'secret reference or a pack '
                                                  'requirement.',
                                   'from_schema': 'https://rede.dev/contracts/port',
                                   'name': 'DeclarationName',
                                   'pattern': '^[A-Za-z_][A-Za-z0-9_.-]*$',
                                   'typeof': 'string'},
               'InputSha256': {'description': 'SHA-256 in lowercase hexadecimal '
                                              'over the canonical JSON of an '
                                              "invocation's input "
                                              '(docs/contracts.md#canonical-hash).',
                               'from_schema': 'https://rede.dev/contracts/port',
                               'name': 'InputSha256',
                               'pattern': '^[0-9a-f]{64}$',
                               'typeof': 'string'},
               'PinnedImage': {'description': 'A container image reference pinned '
                                              'by a SHA-256 digest.',
                               'from_schema': 'https://rede.dev/contracts/port',
                               'name': 'PinnedImage',
                               'pattern': '^[^@\\s]+@sha256:[0-9a-f]{64}$',
                               'typeof': 'string'},
               'PortName': {'description': 'A stable name for a port in the '
                                           'catalogue.',
                            'from_schema': 'https://rede.dev/contracts/port',
                            'name': 'PortName',
                            'pattern': '^[a-z][a-z0-9]*([-_][a-z0-9]+)*$',
                            'typeof': 'string'}}} )

class LossDirection(str, Enum):
    """
    Which way the mapping runs, and so who loses.
    """
    out = "out"
    """
    From a published epoch to the standard. A reader that knows only the standard loses what is listed.
    """
    in_ = "in"
    """
    From a document in the standard to Rede. Rede does not take over what is listed.
    """


class LossSubject(str, Enum):
    """
    The part of the meaning that is lost. For `out` these are the parts of Rede's model (docs/concepts.md, "The model"); for `in` the entry names the standard's own construct in `what` and the nearest part here. A new part is a change of this contract.
    """
    state = "state"
    """
    Whether there is a value: unknown, not applicable or invalid, beside known.
    """
    reason = "reason"
    """
    The reason code of a value that is not known.
    """
    proof = "proof"
    """
    Why a row holds: its witnesses, with premises, polarity, bindings and aggregates.
    """
    source = "source"
    """
    Where a fact comes from: file, row and pinned revision.
    """
    rule = "rule"
    """
    How a conclusion follows: derivation, calculation and allocation rules.
    """
    check = "check"
    """
    What must hold: integrity checks and invariants.
    """
    unit = "unit"
    """
    The unit and dimension of a quantity, and its exact storage.
    """
    money = "money"
    """
    Exact money: the currency, the scale and the named rounding.
    """
    time = "time"
    """
    Validity and knowledge time of a row, and versions of an element.
    """
    world = "world"
    """
    Whether a kind or a relation is closed or open: what an absent row means.
    """
    access = "access"
    """
    Which role reads what, and that a role's view is complete for that role.
    """
    identity = "identity"
    """
    What names an element or an epoch: ids, IRIs, the schema id and hash pins.
    """
    structure = "structure"
    """
    The shape of the schema: kinds, arrows, cardinality, enums and their order, path equations.
    """
    text = "text"
    """
    Labels and sentences per language.
    """


class LossFate(str, Enum):
    """
    What happens to the part on the way.
    """
    dropped = "dropped"
    """
    Not written at all. The other side cannot recover it from what the connector wrote.
    """
    weakened = "weakened"
    """
    Written with less meaning, in a member of the target that `carried_by` names; `what` says what is left out.
    """
    extension = "extension"
    """
    Written in full in terms outside the standard, named in `carried_by`. A reader that knows those terms loses nothing; one that knows only the standard loses the part.
    """


class PortKind(str, Enum):
    """
    What a port does at the boundary (O12a).
    """
    in_ = "in"
    """
    Reads a source; what arrives is an observation. A stream arrives as deltas (RD6).
    """
    out = "out"
    """
    Writes a projection of a checked, published epoch per role, with its loss list.
    """
    effect = "effect"
    """
    Changes the world once per approved plan hash through the effect journal; its result returns as an observation.
    """


class PortInput(str, Enum):
    """
    What a run of the port starts from. Each kind has exactly one.
    """
    source = "source"
    """
    A source and a position in it, outside Rede (kind in).
    """
    checked_epoch = "checked_epoch"
    """
    A published epoch the checker accepted, read per role by hash (kind out).
    """
    approved_plan = "approved_plan"
    """
    The plan hash the approver accepted; the effect journal claims it once (kind effect).
    """


class PortOutput(str, Enum):
    """
    What a port writes. There is no value for curated facts: no port writes them. A curated fact changes only through a proposal that a person or a gate accepts.
    """
    observation = "observation"
    """
    Rows of the observation layer, each with its source, observed time and knowledge time (kind in).
    """
    projection = "projection"
    """
    A target outside Rede made from a checked epoch: files, a table, an artifact or a descriptor (kind out).
    """
    world = "world"
    """
    A change outside Rede, once per plan hash (kind effect). Its result is read back as an observation.
    """


class PortRowSource(str, Enum):
    """
    How each row a port writes names where it comes from ("a source per row").
    """
    source = "source"
    """
    Each observation carries a Source (contracts/source.yaml) with its event time.
    """
    output_index = "output_index"
    """
    Each written line names its rows and proof hashes (contracts/output-index.yaml).
    """
    journal = "journal"
    """
    Each change is bound to its plan hash in the effect journal; what it created is listed by that tag.
    """


class PortRuntime(str, Enum):
    """
    Where the port runs.
    """
    in_process = "in_process"
    """
    On the operator's host or in the core's process, until ports run as Jobs (M6).
    """
    job = "job"
    """
    As a container Job; the image is pinned by digest.
    """


class Cadence(str, Enum):
    """
    The desired freshness of what the port reads or writes (O11).
    """
    live = "live"
    """
    As it changes; the delay bound is max_delay_seconds.
    """
    hourly = "hourly"
    """
    Once an hour.
    """
    daily = "daily"
    """
    Once a day.
    """
    on_request = "on_request"
    """
    Only when a person or a pipeline asks for it.
    """



class Loss(ConfiguredBaseModel):
    """
    One part of the meaning that the mapping does not carry, and what happens to it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/connector',
         'rules': [{'description': 'An extension names its terms.',
                    'postconditions': {'slot_conditions': {'carried_by': {'name': 'carried_by',
                                                                          'required': True}}},
                    'preconditions': {'slot_conditions': {'fate': {'equals_string': 'extension',
                                                                   'name': 'fate'}}}},
                   {'description': 'A weakened part names the member that keeps the '
                                   'rest.',
                    'postconditions': {'slot_conditions': {'carried_by': {'name': 'carried_by',
                                                                          'required': True}}},
                    'preconditions': {'slot_conditions': {'fate': {'equals_string': 'weakened',
                                                                   'name': 'fate'}}}},
                   {'description': 'What is dropped is carried by nothing.',
                    'postconditions': {'slot_conditions': {'carried_by': {'name': 'carried_by',
                                                                          'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'fate': {'equals_string': 'dropped',
                                                                   'name': 'fate'}}}}]})

    subject: LossSubject = Field(default=..., description="""The part of the meaning that is lost.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Loss']} })
    what: str = Field(default=..., description="""What exactly the reader on the other side does not get, in one or two sentences.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Loss']} })
    fate: LossFate = Field(default=..., description="""Dropped, weakened or carried by an extension.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Loss']} })
    carried_by: Optional[list[str]] = Field(default=None, description="""For `extension` the terms outside the standard that carry the part; for `weakened` the member of the target that keeps what is left. Absent for `dropped`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Loss']} })


class LossList(ConfiguredBaseModel):
    """
    The loss list of one connector in one direction, as published beside what the connector writes. `losses` is required and is empty only when nothing is lost.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/connector', 'tree_root': True})

    connector: str = Field(default=..., description="""The connector the list belongs to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'Port']} })
    standard: str = Field(default=..., description="""The standard, for example PROV-O, SHACL, ODCS or DCAT.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'PortConnector']} })
    standard_version: str = Field(default=..., description="""The version of the standard the mapping is written against.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'PortConnector']} })
    direction: LossDirection = Field(default=..., description="""out or in.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList']} })
    losses: list[Loss] = Field(default=..., description="""One entry per loss.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'Port']} })


class Port(ConfiguredBaseModel):
    """
    The static declaration of a port. The kind fixes what a run starts from, what it writes and how each row names its source; the declaration states all three so a port that would write curated facts, or an out-port that would run on an unchecked epoch, cannot be declared.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/port',
         'rules': [{'description': 'An in-port reads a source and writes observations '
                                   'with a source each; it has no effect beyond its '
                                   'declared footprint.',
                    'postconditions': {'slot_conditions': {'effect': {'name': 'effect',
                                                                      'value_presence': 'ABSENT'},
                                                           'row_source': {'equals_string': 'source',
                                                                          'name': 'row_source'},
                                                           'runs_on': {'equals_string': 'source',
                                                                       'name': 'runs_on'},
                                                           'writes': {'equals_string': 'observation',
                                                                      'name': 'writes'}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'in',
                                                                   'name': 'kind'}}}},
                   {'description': 'An out-port runs only on a checked, published '
                                   'epoch and writes a projection with an output '
                                   'index; it has no effect.',
                    'postconditions': {'slot_conditions': {'effect': {'name': 'effect',
                                                                      'value_presence': 'ABSENT'},
                                                           'row_source': {'equals_string': 'output_index',
                                                                          'name': 'row_source'},
                                                           'runs_on': {'equals_string': 'checked_epoch',
                                                                       'name': 'runs_on'},
                                                           'writes': {'equals_string': 'projection',
                                                                      'name': 'writes'}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'out',
                                                                   'name': 'kind'}}}},
                   {'description': 'An effect port runs on an approved plan through '
                                   'the journal and names plan, apply and status.',
                    'postconditions': {'slot_conditions': {'effect': {'name': 'effect',
                                                                      'required': True},
                                                           'row_source': {'equals_string': 'journal',
                                                                          'name': 'row_source'},
                                                           'runs_on': {'equals_string': 'approved_plan',
                                                                       'name': 'runs_on'},
                                                           'writes': {'equals_string': 'world',
                                                                      'name': 'writes'}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'effect',
                                                                   'name': 'kind'}}}},
                   {'description': 'An out-port makes nothing in a source: it has no '
                                   'footprint.',
                    'postconditions': {'slot_conditions': {'footprint': {'name': 'footprint',
                                                                         'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'out',
                                                                   'name': 'kind'}}}},
                   {'description': 'What an effect makes goes through the journal: it '
                                   'has no footprint.',
                    'postconditions': {'slot_conditions': {'footprint': {'name': 'footprint',
                                                                         'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'kind': {'equals_string': 'effect',
                                                                   'name': 'kind'}}}},
                   {'description': 'A port that runs as a Job is pinned by digest.',
                    'postconditions': {'slot_conditions': {'image': {'name': 'image',
                                                                     'required': True}}},
                    'preconditions': {'slot_conditions': {'runtime': {'equals_string': 'job',
                                                                      'name': 'runtime'}}}},
                   {'description': 'A port that runs in-process names no image; its '
                                   'invocation has none either.',
                    'postconditions': {'slot_conditions': {'image': {'name': 'image',
                                                                     'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'runtime': {'equals_string': 'in_process',
                                                                      'name': 'runtime'}}}}],
         'tree_root': True})

    name: str = Field(default=..., description="""Port identity in the catalogue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    version: str = Field(default=..., description="""The declared implementation version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    kind: PortKind = Field(default=..., description="""in, out or effect.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port', 'PortInvocation']} })
    runs_on: PortInput = Field(default=..., description="""What each run starts from; fixed by the kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    writes: PortOutput = Field(default=..., description="""What each run writes; fixed by the kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    row_source: PortRowSource = Field(default=..., description="""How each written row names its source; fixed by the kind.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    runtime: PortRuntime = Field(default=..., description="""Where the port runs.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    image: Optional[str] = Field(default=None, description="""The digest-pinned container; required when the port runs as a Job.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port', 'PortInvocation']} })
    connector: Optional[PortConnector] = Field(default=None, description="""The external standard, when the port is a connector.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'Port']} })
    consumes: list[str] = Field(default=..., description="""The kinds read: sources, Output schemas, files or plans.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    produces: list[str] = Field(default=..., description="""The kinds written: observations, projections, or the results of an effect.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    freshness: PortFreshness = Field(default=..., description="""The port's freshness facts (O11).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    mapping_owner: str = Field(default=..., description="""Who answers for the mapping between Rede's kinds and the outside: a role or a team, never a person's account.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    losses: list[Loss] = Field(default=..., description="""What the mapping loses, one entry per lost part; empty only when nothing is lost. An entry is a Loss of contracts/connector.yaml (M01), the format a connector's published loss list uses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'Port']} })
    effect: Optional[PortEffect] = Field(default=None, description="""The operations of an effect; required for kind effect only.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    footprint: Optional[PortFootprint] = Field(default=None, description="""What an in-port makes in its source for the length of a run; absent when it makes nothing. Kind in only.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    secrets: Optional[list[str]] = Field(default=None, description="""Names of secret references the port resolves; never values.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })
    requires: Optional[list[str]] = Field(default=None, description="""Pack requirements checked before a run.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port']} })

    @field_validator('version')
    def pattern_version(cls, v):
        pattern=re.compile(r"^\S+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid version format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid version format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('mapping_owner')
    def pattern_mapping_owner(cls, v):
        pattern=re.compile(r"^\S+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid mapping_owner format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid mapping_owner format: {v}"
            raise ValueError(err_msg)
        return v


class PortFootprint(ConfiguredBaseModel):
    """
    What an in-port makes in its source to be able to read it, such as a probe (ruling of 12-11-2026 on O12a). Allowed only when the source itself was made by an approved effect plan of Rede: every resource the port makes carries that plan's hash under `plan_label`, the port removes it in the same run, and what it could not remove is reported by the run, which then fails (PC11). The approval is that plan's, so the footprint needs no journal row of its own. A port that makes something in a source no approved plan of Rede made, or that leaves something behind on purpose, is a port of kind effect.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/port'})

    makes: list[str] = Field(default=..., description="""The kinds of resource the port makes in its source; each is removed in the same run.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['PortFootprint']} })
    plan_label: str = Field(default=..., description="""The label or tag every such resource carries; its value is the hash of the approved effect plan that made the source.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortFootprint']} })

    @field_validator('plan_label')
    def pattern_plan_label(cls, v):
        pattern=re.compile(r"^\S+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid plan_label format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid plan_label format: {v}"
            raise ValueError(err_msg)
        return v


class PortConnector(ConfiguredBaseModel):
    """
    The external standard a connector port maps to, and the fixture its mapping round-trips on.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/port'})

    standard: str = Field(default=..., description="""The standard, for example ODCS, DCAT, SHACL, DTDL, Iceberg or OCI.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'PortConnector']} })
    standard_version: str = Field(default=..., description="""The version of the standard.""", json_schema_extra = { "linkml_meta": {'domain_of': ['LossList', 'PortConnector']} })
    round_trip: str = Field(default=..., description="""The fixture the mapping is tested on: out and back with only the declared losses.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortConnector']} })

    @field_validator('standard')
    def pattern_standard(cls, v):
        pattern=re.compile(r"^\S+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid standard format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid standard format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('standard_version')
    def pattern_standard_version(cls, v):
        pattern=re.compile(r"^\S+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid standard_version format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid standard_version format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('round_trip')
    def pattern_round_trip(cls, v):
        pattern=re.compile(r"^\S+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid round_trip format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid round_trip format: {v}"
            raise ValueError(err_msg)
        return v


class PortFreshness(ConfiguredBaseModel):
    """
    The freshness facts of a port (O11): the desired cadence and the largest delay. Rows carry their own observed time and knowledge time; rules may read those, never the cadence.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/port'})

    cadence: Cadence = Field(default=..., description="""How often the port should read or write: live, hourly, daily or on request.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortFreshness']} })
    max_delay_seconds: Optional[int] = Field(default=None, description="""The largest delay between a change and its row, when bounded.""", ge=0, json_schema_extra = { "linkml_meta": {'domain_of': ['PortFreshness']} })


class PortEffect(ConfiguredBaseModel):
    """
    The three operations of an effect (A02, A03).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/port'})

    plan: str = Field(default=..., description="""Produces the dry-run difference and the plan hash; changes nothing.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortEffect']} })
    apply: str = Field(default=..., description="""Applies the approved plan once, through the effect journal.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortEffect']} })
    status: str = Field(default=..., description="""Reconciles the attempt by the plan-hash tag; changes nothing.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortEffect']} })


class PortInvocation(ConfiguredBaseModel):
    """
    One call of a declared port. The input hash is required for every kind and, with the port, its image, the operation and the unit, identifies the attempt. For an in-port it covers the source and position read; for an out-port the checked epoch read; for an effect's plan the canonical export, and for its apply and status the plan hash of the EffectPlan (contracts/effect.yaml). This record describes an attempt and guarantees nothing at runtime; the effect journal claims an attempt durably.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/port'})

    port: str = Field(default=..., description="""The name of the declared Port.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortInvocation']} })
    kind: PortKind = Field(default=..., description="""The kind of the declared Port.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port', 'PortInvocation']} })
    image: Optional[str] = Field(default=None, description="""The digest-pinned image that ran; absent for a port that runs in-process.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Port', 'PortInvocation']} })
    operation: str = Field(default=..., description="""The operation called: read (in), write (out), or the effect's plan, apply or status name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortInvocation']} })
    unit: str = Field(default=..., description="""What the call is about: the source for in, the epoch and role for out, the effect unit for effect.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortInvocation']} })
    input_sha256: str = Field(default=..., description="""The hash of the call's input.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PortInvocation']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Loss.model_rebuild()
LossList.model_rebuild()
Port.model_rebuild()
PortFootprint.model_rebuild()
PortConnector.model_rebuild()
PortFreshness.model_rebuild()
PortEffect.model_rebuild()
PortInvocation.model_rebuild()
