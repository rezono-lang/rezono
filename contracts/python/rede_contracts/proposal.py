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
     'description': 'What the Git-host plugin gives back, the same for every host '
                    '(docs/architecture.md#the-git-host-plugin): a proposal (a '
                    'pull request) with its state and commits, and a host-neutral '
                    'event made from a signed webhook (push or pull_request) for '
                    'the Git ingest. Adapters: edge/githost. And what the gate '
                    'signs when it dispatches a proposal: the verified proposer '
                    'and exactly what they proposed (ProposerReceipt, defect F5), '
                    'so that four eyes can still be checked after the gate-to-Git '
                    'boundary.',
     'id': 'https://rede.dev/contracts/proposal',
     'imports': ['linkml:types'],
     'name': 'rede_proposal',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'rede': {'prefix_prefix': 'rede',
                           'prefix_reference': 'https://rede.dev/contracts/'}},
     'source_file': 'proposal.yaml',
     'title': 'Proposal on a Git host'} )

class ProposalState(str, Enum):
    open = "open"
    merged = "merged"
    """
    Merged into the base branch; the main pipeline takes the delta.
    """
    closed = "closed"
    """
    Closed without merging.
    """


class HostEventKind(str, Enum):
    push = "push"
    pull_request = "pull_request"


class GateKeyType(str, Enum):
    """
    JWK key types (RFC 7518, RFC 8037); public keys only, never oct.
    """
    OKP = "OKP"
    EC = "EC"


class GateKeyCurve(str, Enum):
    Ed25519 = "Ed25519"
    P_256 = "P-256"


class SignatureAlgorithm(str, Enum):
    """
    JWS algorithm names (RFC 7518, RFC 8037). Asymmetric only: whoever verifies a receipt needs the gate's public key, never a secret it shares with the gate.
    """
    EdDSA = "EdDSA"
    """
    Ed25519 (RFC 8037).
    """
    ES256 = "ES256"
    """
    ECDSA over P-256 with SHA-256 (RFC 7518).
    """



class Proposal(ConfiguredBaseModel):
    """
    open_proposal and proposal_status return this.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proposal', 'tree_root': True})

    id: str = Field(default=..., description="""The host's number for the pull request, as text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proposal']} })
    url: str = Field(default=..., description="""The pull request on the host, for people.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proposal']} })
    state: ProposalState = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Proposal']} })
    head: str = Field(default=..., description="""The commit of the proposal branch.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proposal']} })
    base: str = Field(default=..., description="""The commit of the base branch the host compares against.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Proposal']} })
    head_branch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Proposal']} })
    base_branch: str = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Proposal']} })

    @field_validator('id')
    def pattern_id(cls, v):
        pattern=re.compile(r"^[1-9][0-9]*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('head')
    def pattern_head(cls, v):
        pattern=re.compile(r"^[0-9a-f]{40}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid head format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid head format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('base')
    def pattern_base(cls, v):
        pattern=re.compile(r"^[0-9a-f]{40}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid base format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid base format: {v}"
            raise ValueError(err_msg)
        return v


class HostEvent(ConfiguredBaseModel):
    """
    A webhook after its signature is checked; other events are dropped.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proposal',
         'rules': [{'postconditions': {'slot_conditions': {'after': {'name': 'after',
                                                                     'required': True},
                                                           'before': {'name': 'before',
                                                                      'required': True},
                                                           'ref': {'name': 'ref',
                                                                   'required': True}}},
                    'preconditions': {'slot_conditions': {'event': {'equals_string': 'push',
                                                                    'name': 'event'}}}},
                   {'postconditions': {'slot_conditions': {'action': {'name': 'action',
                                                                      'required': True},
                                                           'proposal': {'name': 'proposal',
                                                                        'required': True}}},
                    'preconditions': {'slot_conditions': {'event': {'equals_string': 'pull_request',
                                                                    'name': 'event'}}}}]})

    event: HostEventKind = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['HostEvent']} })
    ref: Optional[str] = Field(default=None, description="""push: the ref, such as refs/heads/main.""", json_schema_extra = { "linkml_meta": {'domain_of': ['HostEvent']} })
    before: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['HostEvent']} })
    after: Optional[str] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['HostEvent']} })
    action: Optional[str] = Field(default=None, description="""pull_request: the action in GitHub's names (opened, synchronize, closed, reopened); Forgejo's synchronized becomes synchronize.""", json_schema_extra = { "linkml_meta": {'domain_of': ['HostEvent']} })
    proposal: Optional[Proposal] = Field(default=None, json_schema_extra = { "linkml_meta": {'domain_of': ['HostEvent']} })

    @field_validator('before')
    def pattern_before(cls, v):
        pattern=re.compile(r"^[0-9a-f]{40}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid before format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid before format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('after')
    def pattern_after(cls, v):
        pattern=re.compile(r"^[0-9a-f]{40}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid after format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid after format: {v}"
            raise ValueError(err_msg)
        return v


class VerifiedPrincipal(ConfiguredBaseModel):
    """
    Who proposed, as the gate's identity port verified it for this request (OIDC), never taken from the delta, the request body or the address. Nothing in it is specific to one identity provider, so a federated issuer fits as well.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proposal'})

    issuer: str = Field(default=..., description="""The namespace in which the subject is stable: the token's issuer (OIDC iss).""", json_schema_extra = { "linkml_meta": {'domain_of': ['VerifiedPrincipal']} })
    subject: str = Field(default=..., description="""The stable subject in that issuer (OIDC sub), not an e-mail address or a display name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['VerifiedPrincipal']} })
    role: str = Field(default=..., description="""The Rede role the gate served this request in; proposing needs it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['VerifiedPrincipal']} })
    verified_at: datetime  = Field(default=..., description="""When the gate verified the token, with a time zone.""", json_schema_extra = { "linkml_meta": {'domain_of': ['VerifiedPrincipal']} })

    @field_validator('subject')
    def pattern_subject(cls, v):
        pattern=re.compile(r"^\S(.*\S)?$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid subject format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid subject format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('role')
    def pattern_role(cls, v):
        pattern=re.compile(r"^[a-z][a-z0-9]*([_-][a-z0-9]+)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid role format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid role format: {v}"
            raise ValueError(err_msg)
        return v


class GateSignature(ConfiguredBaseModel):
    """
    The gate's signature over the canonical JSON (docs/contracts.md#canonical-hash) of the receipt without its member signature. A verifier trusts only the gate keys pinned in the target repository, in the file .rede/gate-keys.json (a GateKeySet), as it is on the base commit of the receipt: never a key that comes with the receipt, the pull request or the request. It refuses a key_id that the set does not list, and an algorithm that is not the alg of that key.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proposal'})

    key_id: str = Field(default=..., description="""The kid of the signing key in the pinned GateKeySet.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GateSignature']} })
    algorithm: SignatureAlgorithm = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GateSignature']} })
    value: str = Field(default=..., description="""The signature, base64url without padding (RFC 7515).""", json_schema_extra = { "linkml_meta": {'domain_of': ['GateSignature']} })

    @field_validator('key_id')
    def pattern_key_id(cls, v):
        pattern=re.compile(r"^[A-Za-z0-9._~:-]{1,128}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid key_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid key_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('value')
    def pattern_value(cls, v):
        pattern=re.compile(r"^[A-Za-z0-9_-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid value format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid value format: {v}"
            raise ValueError(err_msg)
        return v


class ProposerReceipt(ConfiguredBaseModel):
    """
    What the gate signs when it dispatches a proposal: the verified proposer, bound to exactly the proposal it dispatched. The Git host carries it with the proposal (pull request body and commit trailer) and verifies it there (B07); a receipt that does not verify is not a proposer.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proposal', 'tree_root': True})

    principal: VerifiedPrincipal = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ProposerReceipt']} })
    repository: str = Field(default=..., description="""The target repository the proposal is for, as its canonical clone URI (https, without .git and a trailing slash). It is the receipt's audience: a fork or another repository with the same history refuses it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProposerReceipt']} })
    pack_dir: str = Field(default=..., description="""The directory of the pack in the repository, as the gate dispatched it; no segment starts with a dot.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProposerReceipt']} })
    base_commit: str = Field(default=..., description="""The commit the delta was checked against and applies to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProposerReceipt']} })
    delta_sha256: str = Field(default=..., description="""The SHA-256 of the canonical delta text the gate dispatched.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProposerReceipt']} })
    key: str = Field(default=..., description="""The proposal key, which names the proposal branch: the SHA-256 of the UTF-8 text pack_dir, newline, base_commit, newline, the canonical delta text (proposalKey in edge/gate/src/dispatch.ts). A verifier recomputes it from the delta in the proposal.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProposerReceipt']} })
    signature: GateSignature = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['ProposerReceipt']} })

    @field_validator('pack_dir')
    def pattern_pack_dir(cls, v):
        pattern=re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*(/[A-Za-z0-9_][A-Za-z0-9._-]*)*$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid pack_dir format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid pack_dir format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('base_commit')
    def pattern_base_commit(cls, v):
        pattern=re.compile(r"^[0-9a-f]{40}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid base_commit format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid base_commit format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('delta_sha256')
    def pattern_delta_sha256(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid delta_sha256 format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid delta_sha256 format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('key')
    def pattern_key(cls, v):
        pattern=re.compile(r"^[0-9a-f]{64}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid key format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid key format: {v}"
            raise ValueError(err_msg)
        return v


class GateKey(ConfiguredBaseModel):
    """
    One public key of the gate, as a JWK (RFC 7517) with its intended algorithm. Public parts only: a set with a private member (d) or a symmetric key is refused.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proposal',
         'rules': [{'postconditions': {'slot_conditions': {'crv': {'equals_string': 'Ed25519',
                                                                   'name': 'crv'},
                                                           'kty': {'equals_string': 'OKP',
                                                                   'name': 'kty'}}},
                    'preconditions': {'slot_conditions': {'alg': {'equals_string': 'EdDSA',
                                                                  'name': 'alg'}}}},
                   {'postconditions': {'slot_conditions': {'crv': {'equals_string': 'P-256',
                                                                   'name': 'crv'},
                                                           'kty': {'equals_string': 'EC',
                                                                   'name': 'kty'},
                                                           'y': {'name': 'y',
                                                                 'required': True}}},
                    'preconditions': {'slot_conditions': {'alg': {'equals_string': 'ES256',
                                                                  'name': 'alg'}}}}]})

    kid: str = Field(default=..., description="""The key_id a receipt names.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GateKey']} })
    alg: SignatureAlgorithm = Field(default=..., description="""The only algorithm this key verifies.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GateKey']} })
    kty: GateKeyType = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GateKey']} })
    crv: GateKeyCurve = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GateKey']} })
    x: str = Field(default=..., description="""The public key (OKP) or its x coordinate (EC), base64url without padding.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GateKey']} })
    y: Optional[str] = Field(default=None, description="""EC only: the y coordinate, base64url without padding.""", json_schema_extra = { "linkml_meta": {'domain_of': ['GateKey']} })

    @field_validator('kid')
    def pattern_kid(cls, v):
        pattern=re.compile(r"^[A-Za-z0-9._~:-]{1,128}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid kid format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid kid format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('x')
    def pattern_x(cls, v):
        pattern=re.compile(r"^[A-Za-z0-9_-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid x format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid x format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('y')
    def pattern_y(cls, v):
        pattern=re.compile(r"^[A-Za-z0-9_-]+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.search(element):
                    err_msg = f"Invalid y format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.search(v):
            err_msg = f"Invalid y format: {v}"
            raise ValueError(err_msg)
        return v


class GateKeySet(ConfiguredBaseModel):
    """
    The gate keys a repository trusts for proposer receipts, pinned in the repository as .rede/gate-keys.json. Rotating a key is a reviewed commit to this file; a receipt verifies against the set on its own base commit.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://rede.dev/contracts/proposal', 'tree_root': True})

    keys: list[GateKey] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['GateKeySet']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Proposal.model_rebuild()
HostEvent.model_rebuild()
VerifiedPrincipal.model_rebuild()
GateSignature.model_rebuild()
ProposerReceipt.model_rebuild()
GateKey.model_rebuild()
GateKeySet.model_rebuild()
