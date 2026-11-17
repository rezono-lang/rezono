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
     'description': 'What the engine produces and the checker verifies. A '
                    'conclusion is separate from its witnesses. A proof is an '
                    'acyclic graph of witnesses, checked against one manifest.',
     'id': 'https://rede.dev/contracts/proof',
     'imports': ['linkml:types', 'value'],
     'name': 'rede_proof',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'proof.yaml',
     'title': 'Witnesses and proofs'} )

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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    value: Optional[str] = Field(default=None, description="""Canonical text form; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Binding', 'CalcStep', 'CalcWitness']} })
    state: ValueState = Field(default=..., description="""State of the value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })

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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    minor_units: Optional[int] = Field(default=None, description="""Integer minor units; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'Quantity']} })
    currency: str = Field(default=..., description="""ISO 4217 currency code.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount']} })
    state: ValueState = Field(default=..., description="""State of the amount.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })

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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    minor_units: Optional[int] = Field(default=None, description="""Integer minor units; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Amount', 'Quantity']} })
    scale: Optional[int] = Field(default=None, description="""Number of decimals in minor_units: kg with scale 0, g with scale 3.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Quantity']} })
    unit: str = Field(default=..., description="""UCUM unit.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Quantity']} })
    state: ValueState = Field(default=..., description="""State of the quantity.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })

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

    reason: Optional[str] = Field(default=None, description="""Why the value has its state: a reason code, never free text. Core codes need no declaration (no_version_applies, versions_overlap, exception_conflict, no_row_applies, ambiguous_date, empty, added_later); a pack declares its own. Absent when no reason is given: a writer omits an empty reason. A known value carries none, except added_later (docs/semantics/values.md §2.3).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    numerator: Optional[int] = Field(default=None, description="""Numerator; absent unless state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Ratio']} })
    denominator: Optional[int] = Field(default=None, description="""Denominator of at least 1; absent unless state is known.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Ratio']} })
    state: ValueState = Field(default=..., description="""State of the ratio.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })

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


class RowRef(ConfiguredBaseModel):
    """
    A reference to one row of one relation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    relation: str = Field(default=..., description="""Relation name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef', 'Aggregate', 'CalcStep']} })
    key: str = Field(default=..., description="""Canonical key of the row: stable and deterministic.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef']} })


class Premise(ConfiguredBaseModel):
    """
    One body atom of a witness, with its polarity and stratum.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    row: RowRef = Field(default=..., description="""The row the premise refers to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise']} })
    polarity: Polarity = Field(default=..., description="""Whether the row must be present or absent.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise']} })
    stratum: int = Field(default=..., description="""Stratum of the premise relation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Premise']} })


class Aggregate(ConfiguredBaseModel):
    """
    Evidence for an aggregate premise; the checker recomputes it over the group.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    relation: str = Field(default=..., description="""Relation that is aggregated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef', 'Aggregate', 'CalcStep']} })
    position: Optional[int] = Field(default=None, description="""The place of this aggregate in the rule (from 0). Two aggregates over the same relation and group (a count and a sum) are told apart by it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    group_key: str = Field(default=..., description="""Canonical key of the group.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    count: int = Field(default=..., description="""Number of contributing rows in the group.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    contributors_sha256: str = Field(default=..., description="""Hash over the sorted keys and values of all contributing rows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })
    result: str = Field(default=..., description="""Canonical text of the aggregate value with its state.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Aggregate']} })


class Witness(ConfiguredBaseModel):
    """
    One rule instance that derives a conclusion.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    conclusion: RowRef = Field(default=..., description="""The row this witness derives.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness']} })
    rule_id: str = Field(default=..., description="""Identifier of the rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness']} })
    bindings: Optional[list[Binding]] = Field(default=None, description="""The substitution of the rule variables.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness']} })
    premises: Optional[list[Premise]] = Field(default=None, description="""The instantiated body atoms.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness']} })
    aggregates: Optional[list[Aggregate]] = Field(default=None, description="""Evidence for the aggregate body atoms.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness']} })


class Binding(ConfiguredBaseModel):
    """
    One variable of the rule bound to a canonical value.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    variable: str = Field(default=..., description="""Variable name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Binding']} })
    value: str = Field(default=..., description="""Canonical value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Binding', 'CalcStep', 'CalcWitness']} })


class CalcStep(ConfiguredBaseModel):
    """
    One evaluated node of a calculation (docs/compiler.md, \"Design M3: calculation witnesses\"). A constant has no step; an untaken branch of an `if` and the value of a definition that does not apply are not evaluated.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    path: str = Field(default=..., description="""The node: <definition>/when or <definition>/value, then one argument index per level.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })
    op: str = Field(default=..., description="""What the node is, as the program has it: fact, parameter or rule for a leaf, else the operator (add, if, round, ...).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })
    ref: Optional[str] = Field(default=None, description="""For a leaf: the fact, the parameter or the rule (rule or rule@version) it names, so an explanation can name and link it. Absent for an operator.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })
    relation: Optional[str] = Field(default=None, description="""For a leaf: the table or view it is read from (the attribute table, the derived relation, the parameter table, the rule's view). Absent for an operator and for an input concept.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef', 'Aggregate', 'CalcStep']} })
    value: Optional[str] = Field(default=None, description="""Canonical text of the value (a number as n or n/d in lowest terms, a boolean as true or false); empty unless the state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Binding', 'CalcStep', 'CalcWitness']} })
    state: ValueState = Field(default=..., description="""State of the value.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    reason: Optional[str] = Field(default=None, description="""Why the value is not known; empty when it is.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    element: Optional[str] = Field(default=None, description="""For a parameter leaf: the id of the parameter element it read, so an explanation reaches the row and its source. Absent when no row was read or chosen.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcStep']} })

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

    conclusion: RowRef = Field(default=..., description="""The row it explains, (subject, value, state, reason), in the rule's view (or a version's view, for a version named as rule@version).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness']} })
    rule: str = Field(default=..., description="""The calculation rule.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    version: Optional[str] = Field(default=None, description="""The chosen version; empty when none was chosen.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    valid_at: Optional[str] = Field(default=None, description="""The evaluation date the version was chosen on (ISO date); empty when there is none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    known_at: Optional[str] = Field(default=None, description="""The knowledge date the version was chosen on (ISO date); empty when there is none.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    definition: Optional[str] = Field(default=None, description="""The name of the definition that applies; empty when none applies.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    value: Optional[str] = Field(default=None, description="""Canonical text of the result; empty unless the state is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value', 'Binding', 'CalcStep', 'CalcWitness']} })
    state: ValueState = Field(default=..., description="""State of the result.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    reason: Optional[str] = Field(default=None, description="""Why the result is not known; empty when it is.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Value',
                       'Amount',
                       'Quantity',
                       'Ratio',
                       'CalcStep',
                       'CalcWitness']} })
    premises: Optional[list[RowRef]] = Field(default=None, description="""The other conclusions it read: rows of derived relations and the results of other calculation rules.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Witness', 'CalcWitness']} })
    reads: list[str] = Field(default=..., description="""Every relation the evaluation reads, sorted: absences decide states there (a missing fact is unknown or not_applicable, two values invalid), so a role sees the result only while it reads each in full (decision O8).""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })
    steps: Optional[list[CalcStep]] = Field(default=None, description="""The evaluated nodes, in evaluation order: the conditions of all definitions in program order, then the value of the definition that applies; a node before its arguments.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CalcWitness']} })


class Proof(ConfiguredBaseModel):
    """
    The chosen proof for one conclusion; acyclic, shortest first, then lexicographic.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proof'})

    root: RowRef = Field(default=..., description="""The conclusion this proof explains.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })
    manifest_id: str = Field(default=..., description="""The manifest this proof is checked against.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })
    witnesses: Optional[list[Witness]] = Field(default=None, description="""The witnesses of the proof graph.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })
    calc_witnesses: Optional[list[CalcWitness]] = Field(default=None, description="""The calculation witnesses of the proof graph (decision W12).""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })
    hidden: Optional[list[RowRef]] = Field(default=None, description="""Conclusions whose witnesses the viewer may not see. The witnesses stay in the proof and are checked; the explainer redacts them afterwards.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proof']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Value.model_rebuild()
Amount.model_rebuild()
Quantity.model_rebuild()
Ratio.model_rebuild()
RowRef.model_rebuild()
Premise.model_rebuild()
Aggregate.model_rebuild()
Witness.model_rebuild()
Binding.model_rebuild()
CalcStep.model_rebuild()
CalcWitness.model_rebuild()
Proof.model_rebuild()
