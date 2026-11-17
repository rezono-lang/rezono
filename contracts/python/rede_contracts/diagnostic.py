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
     'description': 'One error model for every component that judges what an '
                    'author wrote (D15, #394 A6; milestone MOD principle 5): the '
                    'compiler, admission, and later the Reckon parser, the '
                    "checker, the gate's model check (MOD6), the REPL and a "
                    'language server. A diagnostic is a code, a severity, where it '
                    'was found (a logical place and, where the text is known, a '
                    "span in the form of the schema bundle's MOD2 spans) and a "
                    'hint. The code names the diagnostic; its sentence for a '
                    'reader comes from the message files where it has one, and '
                    "`message` is the component's own English sentence.",
     'id': 'https://rede.dev/contracts/diagnostic',
     'imports': ['linkml:types'],
     'name': 'rede_diagnostic',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'diagnostic.yaml',
     'title': 'Diagnostics',
     'types': {'DiagnosticCode': {'description': 'A snake_case code of the '
                                                 'compiler or admission '
                                                 "(admission's refusal codes, in "
                                                 'the form of Reckon Data L0), or '
                                                 'a Reckon code: R and three '
                                                 'digits for an error, W and three '
                                                 'digits for a warning '
                                                 '(docs/reckon/v0.md §10).',
                                  'from_schema': 'https://rede.dev/contracts/diagnostic',
                                  'name': 'DiagnosticCode',
                                  'pattern': '^([a-z][a-z0-9_]*|[RW][0-9]{3})$',
                                  'typeof': 'string'},
               'Position': {'description': 'A line or a column, counted from 1, as '
                                           'decimal text (as the schema bundle '
                                           'writes a span).',
                            'from_schema': 'https://rede.dev/contracts/diagnostic',
                            'name': 'Position',
                            'pattern': '^[1-9][0-9]*$',
                            'typeof': 'string'},
               'Text': {'description': 'One or more words; never empty.',
                        'from_schema': 'https://rede.dev/contracts/diagnostic',
                        'name': 'Text',
                        'pattern': '\\S',
                        'typeof': 'string'}}} )

class Severity(str, Enum):
    """
    What a diagnostic does to the run (AGENTS.md rule 5: correctness blocks, taste warns).
    """
    error = "error"
    """
    The run stops: nothing is compiled, admitted or published.
    """
    warning = "warning"
    """
    The run goes on; the reader is told.
    """



class Span(ConfiguredBaseModel):
    """
    Where a diagnostic points in a file: the schema bundle's Span (contracts/bundle.yaml, MOD2) with the same fields and the same meaning, and an optional end. The file is named as a rule origin names it (relative to its pack, `<pack>:` before a file of an imported pack); line and column count from 1.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/diagnostic',
         'rules': [{'description': 'An end is a line and a column.',
                    'postconditions': {'slot_conditions': {'end_column': {'name': 'end_column',
                                                                          'required': True}}},
                    'preconditions': {'slot_conditions': {'end_line': {'name': 'end_line',
                                                                       'value_presence': 'PRESENT'}}}},
                   {'description': 'An end column has its line.',
                    'postconditions': {'slot_conditions': {'end_line': {'name': 'end_line',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'end_column': {'name': 'end_column',
                                                                         'value_presence': 'PRESENT'}}}}]})

    file: str = Field(default=..., description="""The file, as a rule origin names it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Span']} })
    line: str = Field(default=..., description="""The line where the span starts.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Span']} })
    column: str = Field(default=..., description="""The column where the span starts, in characters.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Span']} })
    end_line: Optional[str] = Field(default=None, description="""The line of the first character after the span; left out when only the start is known.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Span']} })
    end_column: Optional[str] = Field(default=None, description="""The column of the first character after the span; given with end_line.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Span']} })


class Diagnostic(ConfiguredBaseModel):
    """
    One thing a component found in what an author wrote.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/diagnostic'})

    code: str = Field(default=..., description="""What was found; a reader's sentence for it is in the message files.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Diagnostic']} })
    severity: Severity = Field(default=..., description="""error or warning.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Diagnostic']} })
    message: Optional[str] = Field(default=None, description="""The component's own English sentence, for a log and a reader without the message files.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Diagnostic']} })
    where: Optional[str] = Field(default=None, description="""The logical place, as a path of keys and positions in the component's form: a view key such as `views[t].arrows[a].paths[0].steps[1]`, an admission place such as `Host[3].memory`. Left out when the diagnostic is about the whole input.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Diagnostic']} })
    span: Optional[Span] = Field(default=None, description="""Where it is in a file. Left out when no file text is known, as for a fact document given to admission as data: then `where` is the place.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Diagnostic']} })
    hint: Optional[str] = Field(default=None, description="""What to write instead, or how to resolve it, where the component knows.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Diagnostic']} })


class DiagnosticList(ConfiguredBaseModel):
    """
    The diagnostics of one run, in the order the component found them. `diagnostics` is required and is empty only when nothing was found.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/diagnostic', 'tree_root': True})

    diagnostics: list[Diagnostic] = Field(default=..., description="""One entry per diagnostic.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DiagnosticList']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Span.model_rebuild()
Diagnostic.model_rebuild()
DiagnosticList.model_rebuild()
