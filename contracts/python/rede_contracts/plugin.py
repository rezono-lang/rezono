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
     'description': 'Deprecated alias for one wave (O12a): declare ports with '
                    'contracts/port.yaml (PC1). A digest-pinned boundary plugin '
                    'and the capabilities it declares (G2), and one invocation of '
                    'it identified by its input hash.',
     'id': 'https://rede.dev/contracts/plugin',
     'imports': ['linkml:types'],
     'name': 'rede_plugin',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'plugin.yaml',
     'title': 'Plugin declarations',
     'types': {'DeclarationName': {'description': 'A name of a declaration, '
                                                  'capability, secret reference or '
                                                  'pack requirement.',
                                   'from_schema': 'https://rede.dev/contracts/plugin',
                                   'name': 'DeclarationName',
                                   'pattern': '^[A-Za-z_][A-Za-z0-9_.-]*$',
                                   'typeof': 'string'},
               'InputSha256': {'description': 'SHA-256 in lowercase hexadecimal '
                                              'over the canonical JSON of an '
                                              "invocation's input "
                                              '(docs/contracts.md#canonical-hash).',
                               'from_schema': 'https://rede.dev/contracts/plugin',
                               'name': 'InputSha256',
                               'pattern': '^[0-9a-f]{64}$',
                               'typeof': 'string'},
               'PinnedImage': {'description': 'A container image reference pinned '
                                              'by a SHA-256 digest.',
                               'from_schema': 'https://rede.dev/contracts/plugin',
                               'name': 'PinnedImage',
                               'pattern': '^[^@\\s]+@sha256:[0-9a-f]{64}$',
                               'typeof': 'string'},
               'PluginName': {'description': 'A stable name for a plugin in the '
                                             'catalogue.',
                              'from_schema': 'https://rede.dev/contracts/plugin',
                              'name': 'PluginName',
                              'pattern': '^[a-z][a-z0-9]*([-_][a-z0-9]+)*$',
                              'typeof': 'string'}}} )


class Plugin(ConfiguredBaseModel):
    """
    The static declaration of a plugin. Each invocation carries its own input identity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'deprecated': 'Deprecated alias for one wave (O12a): declare ports with '
                       'contracts/port.yaml (PC1). Port, PortEffect and PortInvocation '
                       'replace it.',
         'from_schema': 'https://rede.dev/contracts/plugin',
         'rules': [{'description': 'Declaring an effect requires the out direction.',
                    'postconditions': {'slot_conditions': {'effect': {'name': 'effect',
                                                                      'value_presence': 'ABSENT'}}},
                    'preconditions': {'slot_conditions': {'direction': {'equals_string_in': ['in',
                                                                                             'compute'],
                                                                        'name': 'direction'}}}}],
         'tree_root': True})

    name: str = Field(default=..., description="""Plugin identity in the catalogue.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })
    version: str = Field(default=..., description="""The declared implementation version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })
    image: str = Field(default=..., description="""The digest-pinned container for this implementation.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin', 'PluginInvocation']} })
    direction: list[Literal["in", "compute", "out"]] = Field(default=..., description="""The directions served by this plugin.""", min_length=1, json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin'], 'equals_string_in': ['in', 'compute', 'out']} })
    effect: Optional[PluginEffect] = Field(default=None, description="""Declared operations for an effect in the out direction.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })
    consumes: Optional[list[str]] = Field(default=None, description="""Names of the sources, relations or Output schemas read.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })
    produces: Optional[list[str]] = Field(default=None, description="""Names of the declared deltas, results or observations returned.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })
    capabilities: Optional[list[str]] = Field(default=None, description="""Additional capability names declared by this plugin.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })
    secrets: Optional[list[str]] = Field(default=None, description="""Names of secret references resolved by the plugin.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })
    requires: Optional[list[str]] = Field(default=None, description="""Pack requirements checked before applying an effect.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin']} })

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


class PluginEffect(ConfiguredBaseModel):
    """
    The three capability names for a planned effect.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'deprecated': 'Deprecated alias for one wave (O12a): declare ports with '
                       'contracts/port.yaml (PC1). Port, PortEffect and PortInvocation '
                       'replace it.',
         'from_schema': 'https://rede.dev/contracts/plugin'})

    plan: str = Field(default=..., description="""Produces the dry-run difference.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PluginEffect']} })
    apply: str = Field(default=..., description="""Applies the accepted plan.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PluginEffect']} })
    status: str = Field(default=..., description="""Reconciles the result of an attempt.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PluginEffect']} })


class PluginInvocation(ConfiguredBaseModel):
    """
    One call of a declared plugin. The input hash is required in every direction and, with the plugin image, operation and unit, identifies the attempt: what was called, on which unit, with which input. For an effect, plan runs before any plan exists, so its input hash is the hash of the canonical export; apply and status take the accepted plan, so theirs is the plan hash of the EffectPlan (contracts/effect.yaml). This record describes an attempt and guarantees nothing at runtime; the effect journal claims the attempt durably and reconciles its result.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'deprecated': 'Deprecated alias for one wave (O12a): declare ports with '
                       'contracts/port.yaml (PC1). Port, PortEffect and PortInvocation '
                       'replace it.',
         'from_schema': 'https://rede.dev/contracts/plugin'})

    plugin: str = Field(default=..., description="""The name of the declared Plugin.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PluginInvocation']} })
    image: str = Field(default=..., description="""The digest-pinned image that ran, as declared.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Plugin', 'PluginInvocation']} })
    operation: str = Field(default=..., description="""The operation called, which fixes the direction: read (in), submit (compute), or an effect's plan, apply or status name (out).""", json_schema_extra = { "linkml_meta": {'domain_of': ['PluginInvocation']} })
    unit: str = Field(default=..., description="""The unit the call is about: the source for in, the step unit for compute, the effect unit for out.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PluginInvocation']} })
    input_sha256: str = Field(default=..., description="""The hash of the call's input: for in the source and position read, for compute the step input, for an effect's plan the canonical export, for its apply and status the plan hash of the EffectPlan.""", json_schema_extra = { "linkml_meta": {'domain_of': ['PluginInvocation']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Plugin.model_rebuild()
PluginEffect.model_rebuild()
PluginInvocation.model_rebuild()
