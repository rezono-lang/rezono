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
     'description': 'The index of one render (issue 356 section 2, P7.11; seam '
                    'S12): for every field of every generated file, where it is (a '
                    'line, a JSON pointer or both) and where it came from. A field '
                    'is `knowledge` (a published row, by the RowRef of the '
                    'conclusion whose witness grounds it), `chart_default` (a '
                    "value the template took from the chart's own values file) or "
                    '`chart_constant` (text of a template). Generators, renderers, '
                    "the Lens, the gate route to a field's grounds and the "
                    'controls all read this one index. It is bound to the manifest '
                    "whose rows were rendered and to the hash of the render's "
                    'input, so an index never describes other output. Nothing '
                    'emits it yet (B21); the render step (P7.10) and publication '
                    'with each generated pull request (P7.11b) do.',
     'id': 'https://rede.dev/contracts/output-index',
     'imports': ['linkml:types'],
     'name': 'rede_output_index',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'output-index.yaml',
     'title': 'Output index',
     'types': {'JsonPointer': {'description': 'An RFC 6901 JSON pointer into the '
                                              "file's parsed document; the empty "
                                              'pointer is the whole document.',
                               'from_schema': 'https://rede.dev/contracts/output-index',
                               'name': 'JsonPointer',
                               'pattern': '^(/([^~/]|~[01])*)*$',
                               'typeof': 'string'},
               'Name': {'from_schema': 'https://rede.dev/contracts/output-index',
                        'name': 'Name',
                        'pattern': '^[a-z][a-z0-9]*(_[a-z0-9]+)*$',
                        'typeof': 'string'},
               'RelativePath': {'description': 'A path relative to the output root '
                                               '(or to the chart), with forward '
                                               'slashes, no `.` or `..` segment.',
                                'from_schema': 'https://rede.dev/contracts/output-index',
                                'name': 'RelativePath',
                                'pattern': '^(?!/)(?!.*(^|/)\\.{1,2}(/|$))[^\\\\:]+$',
                                'typeof': 'string'},
               'Sha256': {'from_schema': 'https://rede.dev/contracts/output-index',
                          'name': 'Sha256',
                          'pattern': '^[0-9a-f]{64}$',
                          'typeof': 'string'}}} )

class FieldOrigin(str, Enum):
    """
    Where a field of a generated file came from (issue 356, P7.10d).
    """
    knowledge = "knowledge"
    """
    A value of a published row: `witness` names the conclusion that grounds it.
    """
    chart_default = "chart_default"
    """
    A value the template took from the chart's values file: `default` names the file and the pointer of the default in it.
    """
    chart_constant = "chart_constant"
    """
    Text of the template itself: `template` names its file and line.
    """



class OutputIndex(ConfiguredBaseModel):
    """
    The index of one render of one manifest.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/output-index'})

    format: Literal["rede.output-index/1"] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['OutputIndex'], 'equals_string': 'rede.output-index/1'} })
    pack: str = Field(default=..., description="""The pack whose rows were rendered.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputIndex']} })
    manifest: str = Field(default=..., description="""The manifest id whose rows were rendered; the index belongs to it and to no other.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputIndex']} })
    render: RenderStep = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['OutputIndex']} })
    files: list[OutputFile] = Field(default=..., description="""Every generated file, sorted by path; each path once.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputIndex']} })


class RenderStep(ConfiguredBaseModel):
    """
    The render step that made the files (an offload step, contracts/offload.yaml; P7.10).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/output-index'})

    step: str = Field(default=..., description="""The step name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RenderStep']} })
    input_sha256: str = Field(default=..., description="""The hash of the render's input (chart reference, values, tool versions): the same input gives the same files.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RenderStep']} })


class OutputFile(ConfiguredBaseModel):
    """
    One generated file and the fields in it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/output-index'})

    path: str = Field(default=..., description="""The file, relative to the output root.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputFile']} })
    sha256: str = Field(default=..., description="""The hash of the published bytes of the file.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputFile']} })
    fields: list[OutputField] = Field(default=..., description="""Sorted by line, then pointer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputFile']} })


class OutputField(ConfiguredBaseModel):
    """
    One field of a generated file: a scalar the renderer wrote. It is found by its line, its JSON pointer or both. Its origin decides which one place it names: `knowledge` a witness, `chart_constant` a template line, `chart_default` a pointer into the values file; the other two are absent.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'any_of': [{'slot_conditions': {'line': {'name': 'line', 'required': True}}},
                    {'slot_conditions': {'pointer': {'name': 'pointer',
                                                     'required': True}}}],
         'from_schema': 'https://rede.dev/contracts/output-index',
         'rules': [{'description': 'A knowledge field names the conclusion that '
                                   'grounds it, and no template line.',
                    'postconditions': {'slot_conditions': {'template': {'name': 'template',
                                                                        'value_presence': 'ABSENT'},
                                                           'witness': {'name': 'witness',
                                                                       'required': True}}},
                    'preconditions': {'slot_conditions': {'origin': {'equals_string': 'knowledge',
                                                                     'name': 'origin'}}}},
                   {'description': 'A knowledge field names no values pointer.',
                    'postconditions': {'slot_conditions': {'default': {'name': 'default',
                                                                       'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'origin': {'equals_string': 'knowledge',
                                                                     'name': 'origin'}}}},
                   {'description': 'A chart constant names its template line, and no '
                                   'witness.',
                    'postconditions': {'slot_conditions': {'template': {'name': 'template',
                                                                        'required': True},
                                                           'witness': {'name': 'witness',
                                                                       'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'origin': {'equals_string': 'chart_constant',
                                                                     'name': 'origin'}}}},
                   {'description': 'A chart constant names no values pointer.',
                    'postconditions': {'slot_conditions': {'default': {'name': 'default',
                                                                       'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'origin': {'equals_string': 'chart_constant',
                                                                     'name': 'origin'}}}},
                   {'description': 'A chart default names its pointer in the values '
                                   'file, and no witness.',
                    'postconditions': {'slot_conditions': {'default': {'name': 'default',
                                                                       'required': True},
                                                           'witness': {'name': 'witness',
                                                                       'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'origin': {'equals_string': 'chart_default',
                                                                     'name': 'origin'}}}},
                   {'description': 'A chart default names no template line.',
                    'postconditions': {'slot_conditions': {'template': {'name': 'template',
                                                                        'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'origin': {'equals_string': 'chart_default',
                                                                     'name': 'origin'}}}}]})

    line: Optional[int] = Field(default=None, description="""The 1-based line of the field in the published bytes.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField', 'TemplateLine']} })
    pointer: Optional[str] = Field(default=None, description="""The field in the parsed document (a YAML or JSON output file).""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField', 'ValuesPointer']} })
    origin: FieldOrigin = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField']} })
    witness: Optional[RowRef] = Field(default=None, description="""For `knowledge`: the conclusion row whose witness grounds the value (contracts/proof.yaml, RowRef).""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField']} })
    template: Optional[TemplateLine] = Field(default=None, description="""For `chart_constant`: the template file and line.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField']} })
    default: Optional[ValuesPointer] = Field(default=None, description="""For `chart_default`: the values file and the pointer of the default.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField']} })


class RowRef(ConfiguredBaseModel):
    """
    A reference to one row of one relation, as in contracts/proof.yaml.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/output-index'})

    relation: str = Field(default=..., description="""Relation name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef']} })
    key: str = Field(default=..., description="""Canonical key of the row: stable and deterministic.""", json_schema_extra = { "linkml_meta": {'domain_of': ['RowRef']} })


class TemplateLine(ConfiguredBaseModel):
    """
    A line of a chart template, the place of a chart constant.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/output-index'})

    file: str = Field(default=..., description="""The template, relative to the chart root (`templates/...`).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TemplateLine', 'ValuesPointer']} })
    line: int = Field(default=..., description="""The 1-based line in that file.""", ge=1, json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField', 'TemplateLine']} })


class ValuesPointer(ConfiguredBaseModel):
    """
    A default in the chart's values file, the place of a chart default.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/output-index'})

    file: str = Field(default=..., description="""The values file, relative to the chart root (`values.yaml`).""", json_schema_extra = { "linkml_meta": {'domain_of': ['TemplateLine', 'ValuesPointer']} })
    pointer: str = Field(default=..., description="""The default in that file.""", json_schema_extra = { "linkml_meta": {'domain_of': ['OutputField', 'ValuesPointer']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
OutputIndex.model_rebuild()
RenderStep.model_rebuild()
OutputFile.model_rebuild()
OutputField.model_rebuild()
RowRef.model_rebuild()
TemplateLine.model_rebuild()
ValuesPointer.model_rebuild()
