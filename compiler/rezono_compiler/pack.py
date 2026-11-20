"""Read a pack into an olog model: kinds, arrows, attributes, enums, keys, path equations, labels, messages."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import TypedDict

import yaml
from rezono_admission.schema import INPUT_FORMATS

from .schemaview import SchemaView

from . import amounts, diagnostics, fold, icons as icon_files, modules, rezono_module, rules_dl, spans, strict_yaml, types, views
from .diagnostics import Diagnosed
from .names import NAME
from .regex import PatternError, portable
from . import rezono_reason

LAYERS = ("source", "facts", "conclusions", "plan", "output", "observation")
# Annotations the compiler reads now, or in a later milestone (then ignored without warning).
ANNOTATIONS = {"layer", "path_equations", "outcome", "explain", "invariants", "seal", "sealed_with", "world", "explore",
               "currency", "plane", "owner", "renamed_from", "input_format"}
CURRENCY = re.compile(r"^[A-Z]{3}$")  # ISO 4217
CLASS = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")  # a pack's class (pack.yaml, SO-5), as contracts/pack.yaml says
# What a missing row means: closed, not true; open, unknown.
WORLDS = ("closed", "open")
BIGINT = (-(2**63), 2**63 - 1)
# A sweep computes one epoch per grid value (docs/interaction.md, 1); v1 allows this many, and one sweep per pack.
MAX_GRID = 64
MAX_SWEEPS = 1
# Explanation questions (docs/gui.md, "Questions as data"): what a question starts from, the shape of its answer,
# what a trace step may say, and the messages std-explain gives every question.
QUESTION_STARTS = ("present", "absent", "delta", "sweep")
ANSWERS = ("route", "rings", "gap", "overlay", "series")
TRACE_KEYS = {"direction", "depth", "through", "keep", "stop", "fanout"}
EXPLAIN_MESSAGES = ("explain.outside", "explain.more", "explain.empty")
# The repository's contracts/, for a caller that runs in a checkout (the publisher fingerprints and archives it).
# The compiler itself reads its contracts through contract_dir().
CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
# Messages the compiler refers to; every pack's default-language catalog must define them.
MESSAGES = ("arrow.total", "arrow.partial", "attribute.total", "attribute.partial",
            "is_a", "unique_key", "path_equation")
# Messages a pack needs only when it has a multivalued slot of that sort.
MANY = ("arrow.many.total", "arrow.many.partial", "attribute.many.total", "attribute.many.partial")
# Slot facets a LinkML rule condition may use; anything else is an error.
CONDITIONS = {"required", "value_presence", "equals_string", "equals_number", "minimum_value", "maximum_value",
              "pattern"}
# The slot_uri that makes a slot the name of its kind's elements (docs/compiler.md, Element names).
NAME_URI = "http://www.w3.org/2000/01/rdf-schema#label"
# Slot roles already supported by the compiler (S26). Timestamp ranges remain unsupported by the engine.
SLOT_ROLE_URIS = {NAME_URI: "name", "http://schema.org/description": "description", "http://schema.org/image": "image",
                  "http://schema.org/position": "order", "http://schema.org/validFrom": "valid_from",
                  "http://schema.org/validThrough": "valid_until",
                  "http://www.w3.org/ns/prov#generatedAtTime": "known_from"}
SLOT_ROLE_TYPES = {"name": types.STRING, "description": types.STRING, "image": types.STRING, "order": types.INTEGER,
                   "valid_from": types.DATE, "valid_until": types.DATE, "known_from": types.DATE}
# Until every pack carries the order role, a kind's own whole-number attribute of this name orders its elements.
LEGACY_ORDER = "lane_order"
# LinkML slot facets outside the supported subset (docs/compiler.md); each is an error, never ignored.
UNSUPPORTED = ("equals_expression", "equals_string_in", "any_of", "exactly_one_of", "all_of", "none_of", "array",
               "ifabsent")
# LinkML's open value: a slot with a class of this class_uri as range takes any value, which Rezono cannot type.
ANY_URI = "https://w3id.org/linkml/Any"
ENTRY = rezono_reason.ENTRY
VARIABLE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


class CompileError(Diagnosed):
    """A pack that does not compile, with its diagnostics (D15, diagnostics.py): an error whose site gives its own
    (view typing) keeps them, any other is one `compile_error` per line of its message."""


def contract_dir() -> Path:
    """The contracts the compiler reads (view.yaml with its imports, source.yaml). An installed compiler carries them
    as package data, `rezono_compiler/contracts/`, which compiler/setup.py copies from contracts/ into the wheel; in a
    checkout they are contracts/ itself. Neither is an error that names both, never a guess."""
    shipped = Path(str(resources.files(__package__) / "contracts"))
    for d in (shipped, CONTRACTS):
        if (d / "view.yaml").is_file():
            return d
    raise CompileError(f"the compiler's contracts are missing: neither {shipped} (an installed compiler) "
                       f"nor {CONTRACTS} (a checkout) has view.yaml")


@dataclass
class Slot:
    name: str
    kind: str  # the kind that declares it (owns its table)
    required: bool
    arrow: bool
    range: str  # kind name for an arrow, type or enum name otherwise
    sql_type: str
    inlined: bool = False
    enum: str | None = None
    minimum: int | None = None
    maximum: int | None = None
    multivalued: bool = False
    minimum_cardinality: int | None = None
    maximum_cardinality: int | None = None
    patterns: list[str] = field(default_factory=list)  # portable regular expressions (regex.portable)
    input_format: str | None = None
    constant: object = None  # equals_string or equals_number
    world: str = "closed"  # open if the slot or its kind is open
    explore: tuple[int, int, int] | None = None  # (min, max, step) of a sweep on this slot
    names: bool = False  # slot_uri rdfs:label: its value names an element of the kind (NAME_URI)
    currency: str | None = None  # ISO 4217: an amount in whole minor units of this currency
    unit: str | None = None  # P10.3: the type that declares its unit (Pack.units); with a currency, it stays money
    role: str | None = None  # S26: the recognised role of slot_uri, independent of the slot's name
    span: tuple | None = None  # MOD2: where it is declared (spans.py)
    renamed_from: str | None = None  # MOD2: annotation `renamed_from`, its first name, which its stable id keeps

    @property
    def table(self) -> str:
        return f"{self.kind}__{self.name}"

    @property
    def element(self) -> str:
        return f"{self.kind}.{self.name}"

    @property
    def type(self) -> types.Type:
        """The semantic type of the slot's value (S3a): a scalar, money, a date, an enum value or a reference.
        Cardinality and world stay on the slot."""
        return types.of_slot(self)


@dataclass
class Kind:
    name: str
    cls: str
    layer: str
    parent: str | None
    abstract: bool
    identifier: str | None
    id_type: str = "VARCHAR"
    slots: dict[str, Slot] = field(default_factory=dict)  # declared here, by name
    unique_keys: list[tuple[str, list[str]]] = field(default_factory=list)
    path_equations: list[tuple[str, list[str], list[str]]] = field(default_factory=list)
    module: str = ""
    id_patterns: list[str] = field(default_factory=list)  # on the identifier of a root kind
    rules: list[ClassRule] = field(default_factory=list)
    world: str = "closed"  # open if the class or an ancestor says world: open
    seal: object = None  # the annotation `seal` as written: the name of the period slot
    sealed_with: object = None  # the annotation `sealed_with` as written: the arrow to the element it is part of
    relationship: bool = False  # LinkML represents_relationship (S27), inherited unless explicitly overridden
    plane: str | None = None  # DV1: "control" for a kind of decided values; a data-plane kind has none
    owner: str | None = None  # DV1: who reviews a change to a control kind
    fold: bool = False  # annotation `explain: fold`: a helper kind, folded in an explanation (display only; fold.py)
    span: tuple | None = None  # MOD2: where its class is declared (spans.py)
    renamed_from: str | None = None  # MOD2: annotation `renamed_from`, its first name, which its stable id keeps
    spans: dict = field(default_factory=dict)  # MOD2: where its unique keys (`key:<name>`) and path equations (`eq:<name>`) are


ACCESS = ("may_read", "may_propose", "may_review", "may_publish")  # std-access; their `kind` column names kinds
CLOSE = "period_close"  # the kind of the closing fact of a seal, with these slots
CLOSED_UNTIL, COVERS, ELEMENT, SHA256 = "closed_until", "covers", "element", "sha256"


@dataclass
class Part:
    """A kind whose elements are parts of a sealed element (`sealed_with: <arrow>`, docs/compiler.md#parts): its
    rows belong to the row a close holds, and a part counts only when the element it is part of is accepted
    (`<kind>__accepted(id)`, made by the compiler). `owner` is the kind the arrow points to: the sealed kind or
    another part."""
    kind: str
    arrow: Slot
    owner: str
    tables: list[str] = field(default_factory=list)  # the part's own tables, of the kind and its subkinds

    @property
    def accepted(self) -> str:
        return f"{self.kind}__accepted"


@dataclass
class Seal:
    """The sealed kind (docs/compiler.md#design-m3-the-seal): its period, a required date, and
    the kind of a cover in PeriodClose.covers (an arrow `element` to the sealed kind and its `sha256`). The
    compiler makes `<kind>__refused(id, period_close)` and `<kind>__accepted(id)`; the loader fills
    `<kind>__row_sha256(id, v)` with the canonical hash of each element's row, over `tables` and the rows of its
    `parts`, ordered so that a part's owner comes before it."""
    kind: str
    period: Slot
    cover: str = ""
    tables: list[str] = field(default_factory=list)  # the attribute and arrow tables of the kind and its subkinds, and the subkinds
    parts: list[Part] = field(default_factory=list)

    @property
    def refused(self) -> str:
        return f"{self.kind}__refused"

    @property
    def accepted(self) -> str:
        return f"{self.kind}__accepted"

    @property
    def row_sha256(self) -> str:
        return f"{self.kind}__row_sha256"


@dataclass
class Condition:
    """A LinkML slot condition: facets that one slot of the element must meet."""
    slot: str
    facets: dict  # facet -> value, a subset of CONDITIONS


@dataclass
class ClassRule:
    """A LinkML class rule: where every precondition holds, every postcondition must hold; else the
    elseconditions. A violation is an element for which that fails."""
    name: str  # rule_<n>, in the order of the class
    pre: list[Condition]
    post: list[Condition]
    otherwise: list[Condition]


class AcceptanceQuestion(TypedDict):
    id: str
    question: str
    tests: list[str]


@dataclass
class Pack:
    meta: dict
    schemas: list[dict]
    kinds: dict[str, Kind]
    enums: dict[str, list[str]]
    channels: dict = field(default_factory=dict)
    labels: list[dict] = field(default_factory=list)
    messages: dict[str, str] = field(default_factory=dict)  # language -> MF2 resource text
    warnings: list[str] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)  # {name, version, sha256} of every imported pack
    rules: dict | None = None  # the rule IR document (contracts/rules.yaml), if the pack has rules/
    # The calculation rules as written (contracts/calc.yaml), if the pack or a pack it imports has calc/.
    calc: dict | None = None
    sweeps: list[dict] = field(default_factory=list)  # from sweeps.yaml: one fact cell each, with its grid
    questions: list[dict] = field(default_factory=list)  # explanation questions: imports first, then own
    reader_questions: list[dict] = field(default_factory=list)  # reader questions: imports first, then own
    seals: list[Seal] = field(default_factory=list)  # the sealed kind, if any
    iri: dict = field(default_factory=dict)  # pack.yaml `iri:` resolved (`iris`): base, kind -> IRI, reason IRIs
    folds: dict[str, str] = field(default_factory=dict)  # derived relations marked `@explain fold` -> their .decl
    # Per rule id, the kind of each body literal in source order (MOD14): the rule IR keeps atoms, aggregates,
    # assignments and comparisons in lists of their own, and the bundle publishes the body as it was written.
    rule_bodies: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Per rule id, where the rule is written (MOD2, spans.py): its head in a rule file, or the view that made it.
    rule_spans: dict[str, tuple | None] = field(default_factory=dict)
    # P10.3: the units the pack and the packs it imports declare, by the name of their LinkML type (`units`).
    units: dict[str, types.Unit] = field(default_factory=dict)
    acceptance_questions: list[AcceptanceQuestion] = field(default_factory=list)  # own source inventory

    def ancestors(self, kind: str) -> list[str]:
        """The kind itself, then its parent, up to the root."""
        out = []
        while kind:
            out.append(kind)
            kind = self.kinds[kind].parent
        return out

    def root(self, kind: str) -> str:
        return self.ancestors(kind)[-1]

    def slot(self, kind: str, name: str) -> Slot | None:
        """A slot of a kind, declared there or inherited."""
        for k in self.ancestors(kind):
            if name in self.kinds[k].slots:
                return self.kinds[k].slots[name]
        return None

    def all_slots(self, kind: str) -> list[Slot]:
        return sorted((s for k in self.ancestors(kind) for s in self.kinds[k].slots.values()),
                      key=lambda s: s.name)

    def name(self, kind: str) -> Slot | None:
        """The attribute that names an element of a kind: its slot with slot_uri rdfs:label, own or inherited."""
        return next((s for s in self.all_slots(kind) if s.names), None)

    def slot_roles(self, kind: str) -> dict[str, Slot]:
        """One slot per recognised role, declared on this kind or inherited; checked by `check`."""
        return dict(sorted((s.role or "name", s) for s in self.all_slots(kind) if s.role or s.names))

    def ends(self, kind: str) -> list[Slot]:
        """The arrows of the first unique key of a kind (or a supertype) that holds only single-valued arrows, in
        the key's order. A declared relationship needs at least two distinct ends (S27). Empty: no such key."""
        for k in self.ancestors(kind):
            for _, names in self.kinds[k].unique_keys:
                if self.kinds[kind].relationship and (len(names) < 2 or len(set(names)) != len(names)):
                    continue
                slots = [self.slot(kind, n) for n in names]
                if all(s and s.arrow and not s.multivalued for s in slots):
                    return slots
        return []

    def name_arrows(self, kind: str) -> list[Slot]:
        """For a kind without a name: its ends (a link kind), if one of them has a name, so their names name its
        elements; empty, their ids do."""
        if self.name(kind):
            return []
        slots = self.ends(kind)
        return slots if any(self.name(s.range) for s in slots) else []

    def elements(self) -> list[str]:
        """Every language-neutral element id that can carry a label."""
        out = []
        for k, kind in self.kinds.items():
            out += [k] + [s.element for s in kind.slots.values()]
            out += [f"{k}.{n}" for n, _ in kind.unique_keys] + [f"{k}.{n}" for n, _, _ in kind.path_equations]
        for e, values in self.enums.items():
            out += [e] + [f"{e}.{v}" for v in values]
        if self.rules:
            out += [r["name"] for r in self.rules["relations"] if r["role"] == "derived"]
        return sorted(out)


def valid_name(name: str) -> bool:
    """A name that becomes part of an engine name: lower snake case, without the separator '__'."""
    return bool(NAME.match(name)) and "__" not in name


def snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def tags(element) -> dict:
    """Annotations by tag; LinkML gives a dict or a JsonObj depending on the element."""
    a = element.annotations or {}
    return {k: v for k, v in (a.items() if isinstance(a, dict) else vars(a).items()) if not k.startswith("_")}


def ann(element, tag, default=None):
    a = tags(element).get(tag)
    return default if a is None else a.value


def renamed_from(element, where: str, errors: list[str]) -> str | None:
    """MOD2: the annotation `renamed_from`, the first name of a renamed class or slot. Its stable id keeps that
    name, so a rename changes no id; the bundle records the name."""
    if "renamed_from" not in tags(element):
        return None
    name = plain(ann(element, "renamed_from"))
    if not isinstance(name, str) or not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", name):
        errors.append(f"{where}: renamed_from is the first name it had, not {name!r}")
        return None
    return name


def reason_messages(doc) -> list[str]:
    """The message `reason.<reason>` of every reason a named outcome gives; known has none."""
    outcomes = {r["name"] for r in (doc or {}).get("relations", []) if r.get("outcome")}
    return sorted({f"reason.{r['head']['terms'][2]}" for r in (doc or {}).get("rules", [])
                   if r["head"]["relation"] in outcomes and r["head"]["terms"][2]})


def world(element, where: str, errors: list[str]) -> str:
    w = ann(element, "world", "closed")
    if w not in WORLDS:
        errors.append(f"{where}: world must be one of {WORLDS}, not {w!r}")
        return "closed"
    return w


def read_meta(pack_dir: str | Path) -> dict:
    """Read metadata and refuse unsupported views, without loading schemas or pack code."""
    path = Path(pack_dir) / "pack.yaml"
    try:
        meta = strict_yaml.read(path)
    except (OSError, yaml.YAMLError) as error:
        raise CompileError(f"{path}: cannot read pack metadata ({error})") from error
    if not isinstance(meta, dict) or not all(meta.get(k) for k in ("name", "version", "default_language")):
        raise CompileError(f"{path}: needs name, version and default_language")
    value = meta.get("theory", False)
    if type(value) is not bool:
        raise CompileError(f"{path}: theory must be a boolean")
    # What the data is (SO-5): a name the pack's owner gives; a profile says which classes it carries.
    if "class" in meta and not (isinstance(meta["class"], str) and CLASS.fullmatch(meta["class"])):
        raise CompileError(f"{path}: class is a lower-case name with hyphens (contracts/pack.yaml), not {meta['class']!r}")
    try:
        views.admit(pack_dir)  # a views.yaml outside the profile that executes is refused here
    except views.ViewError as error:
        raise CompileError(str(error)) from error
    return meta | {"theory": value}


def theory_meta(meta: dict, pack_dir: Path, errors: list[str]) -> bool:
    """A theory is a definition without its own facts, also when imported by another pack."""
    value = meta.get("theory", False)
    if type(value) is not bool:
        errors.append(f"{pack_dir}/pack.yaml: theory must be a boolean")
        return False
    if value:
        facts = pack_dir / "facts"
        if facts.is_file() or any(p.is_file() for p in facts.rglob("*")):
            errors.append(f"{pack_dir}/facts: a theory pack cannot contain fact files")
    return value


NAMESPACE = re.compile(r"https://[^\s\"#<>?\\^`{|}]+/")  # a whole IRI that ends in `/` (pack.yaml `iri:`)


def namespace(value, where: str, errors: list[str]) -> str | None:
    """A namespace or `base` of pack.yaml `iri:`: a whole https IRI ending in `/`, used as written (ruling 2)."""
    if not isinstance(value, str) or not value.startswith("https://"):
        errors.append(f"{where}: an IRI here is https, not {value!r}")
    elif not value.endswith("/"):
        errors.append(f"{where}: a namespace ends in '/', not {value!r}")
    elif not NAMESPACE.fullmatch(value):
        errors.append(f"{where}: {value!r} is not a whole IRI (no space, '#', '?' or quote)")
    else:
        return value
    return None


def module_path(m: modules.Module) -> str:
    """A module's name in its pack's `modules:`: its path under schema/ without .yaml, or, for a module written in
    Rezono, its path under rezono/ without .rezono (the path a schema file of it would have)."""
    return m.id.split(":", 1)[-1]


def iri_block(name: str, meta: dict, classes: set[str], modules_of: set[str], codes: set[str],
              errors: list[str]) -> dict | None:
    """One pack's `iri:` block and its modules' namespaces, checked: {base, kinds: {class: ns}, modules: {path:
    ns}, reasons: {code: ns}}. None for a pack without the block. `classes` are the LinkML classes the pack
    declares, `modules_of` its module paths, `codes` the reason codes of the compile."""
    where = f"{name}/pack.yaml: iri"
    block = meta.get("iri")
    if block is None:
        if any(isinstance(e, dict) and "namespace" in e for e in meta.get("modules") or []):
            errors.append(f"{name}/pack.yaml: modules: a module namespace needs the block 'iri' with a 'base'")
        return None
    if not isinstance(block, dict) or "base" not in block or set(block) - {"base", "namespaces"}:
        errors.append(f"{where}: needs 'base' and may have 'namespaces'")
        return None
    out = {"base": namespace(block["base"], f"{where}.base", errors), "kinds": {}, "modules": {}, "reasons": {}}
    entries = block.get("namespaces") or []
    if not isinstance(entries, list):
        errors.append(f"{where}.namespaces: a list of {{iri, kinds, reasons}}")
        entries = []
    for i, entry in enumerate(entries):
        at = f"{where}.namespaces[{i}]"
        if not isinstance(entry, dict) or "iri" not in entry or set(entry) - {"iri", "kinds", "reasons"} \
                or not all(isinstance(entry.get(k, []), list) for k in ("kinds", "reasons")):
            errors.append(f"{at}: needs 'iri' and may have a list 'kinds' and a list 'reasons'")
            continue
        ns = namespace(entry["iri"], f"{at}.iri", errors)
        for member, known, what in (("kinds", classes, "a kind the pack declares"),
                                    ("reasons", codes, "a reason code of the pack")):
            for n in map(str, entry.get(member, [])):
                if n in out[member]:
                    errors.append(f"{at}: '{n}' is named in two namespaces")
                elif n not in known:
                    errors.append(f"{at}: '{n}' is not {what}")
                elif ns:
                    out[member][n] = ns
    for entry in meta.get("modules") or []:
        if isinstance(entry, dict) and "namespace" in entry:
            rel = str(entry.get("module"))
            if rel not in modules_of:
                errors.append(f"{name}/pack.yaml: modules: '{rel}' is not a module "
                              "(a path under schema/ without .yaml)")
            elif ns := namespace(entry["namespace"], f"{name}/pack.yaml: modules: '{rel}'.namespace", errors):
                out["modules"][rel] = ns
    return out


def iris(pack: Pack, meta: dict, packs: dict, owner: dict, errors: list[str]) -> dict:
    """The IRIs pack.yaml `iri:` declares (docs/ring2/iris.md §4), resolved per kind
    and reason code: {} when neither the pack nor any pack it imports declares the block, so nothing changes.

    A kind takes the namespace that the pack declaring it gives it: an entry of `namespaces` that names the kind,
    else its module's `namespace`, else that pack's `base`. A kind of an imported pack without the block takes the
    compiled pack's `base`, as it did before. Its IRI is the namespace and its class name, nothing else joined. A
    reason code takes the compiled pack's namespace for it, else its `base`: `<ns>reason/<code>`. Two packs of one
    compile never share a `base`."""
    root = meta["name"]
    metas = {root: meta} | {n: p.meta for n, p in sorted(packs.items())}
    codes = {m.removeprefix("reason.") for m in reason_messages(pack.rules)}
    blocks = {}
    for name, own in metas.items():
        mine = {k: m for k, m in owner.items() if m.pack == name}
        paths = {module_path(m) for m in mine.values()}
        block = iri_block(name, own, {pack.kinds[k].cls for k in mine}, paths, codes, errors)
        if block is not None:
            blocks[name] = block
    bases: dict[str, str] = {}
    for name, block in blocks.items():
        if block["base"] in bases:
            errors.append(f"{name}/pack.yaml: iri.base {block['base']} is also the base of {bases[block['base']]}; "
                          "two packs never share a base")
        bases.setdefault(block["base"], name)
    if not blocks or errors:
        return {}
    out: dict = {"kinds": {}}
    for k, kind in pack.kinds.items():
        m = owner[k]
        path = module_path(m)
        if m.pack in blocks:
            b = blocks[m.pack]
            ns = b["kinds"].get(kind.cls) or b["modules"].get(path) or b["base"]
        elif root in blocks:
            ns = blocks[root]["base"]
        else:
            continue
        out["kinds"][k] = f"{ns}{kind.cls}"
    if root in blocks:
        b = blocks[root]
        out["base"] = b["base"]
        out["reasons"] = [{"code": c, "iri": f"{b['reasons'].get(c, b['base'])}reason/{c}"} for c in sorted(codes)]
    return out


def read(pack_dir: str | Path) -> Pack:
    pack_dir = Path(pack_dir)
    errors: list[str] = []
    typed: dict[str, tuple[diagnostics.Diagnostic, ...]] = {}  # D15: the diagnostics of an error that has its own
    warnings: list[str] = []
    meta = read_meta(pack_dir)
    if not list((pack_dir / "schema").rglob("*.yaml")) and not meta.get("rezono"):
        raise CompileError(f"{pack_dir}/schema: no schema files, and pack.yaml names no module written in Rezono")
    is_theory = theory_meta(meta, pack_dir, errors)
    if errors:
        raise CompileError("\n".join(errors))
    mods, packs = modules.load(pack_dir, meta, errors)
    if errors:
        raise CompileError("\n".join(errors))
    names = modules.Names(mods, snake, errors, warnings=warnings)
    found: dict = {}

    def placed(m, *paths):
        """The span of the first of `paths` in module `m`'s file (MOD2); a module written in Rezono is placed by its
        form, since its text is not YAML."""
        if m.file not in found:
            found[m.file] = rezono_module.marks(m.file, m.form) if m.form else spans.marks(m.file)
        return spans.first(found[m.file], spans.where(m.pack, meta["name"], m.rel), *paths)
    for p in packs.values():
        theory_meta(p.meta, p.dir, errors)
        try:
            views.refuse(p.dir)
        except views.ViewError as error:
            errors.append(str(error))

    kinds: dict[str, Kind] = {}
    enums: dict[str, list[str]] = {}
    owner: dict[str, modules.Module] = {}
    for m in mods:
        sv = m.sv
        default_layer = ann(sv.schema, "layer")
        warnings += [f"{m.rel}: unknown annotation '{t}'" for t in tags(sv.schema) if t not in ANNOTATIONS]
        if "world" in tags(sv.schema):
            errors.append(f"{m.rel}: world goes on a class or a slot, not on a schema")
        for cname in sorted(sv.all_classes(imports=False)):
            c = sv.get_class(cname)
            k = names.name(m.id, cname)
            if not NAME.match(k) or "__" in k:
                errors.append(f"class {cname}: name '{k}' is not a valid kind name")
            if k in kinds:
                errors.append(f"class {cname}: kind '{k}' defined twice")
            if c.mixins or c.slot_usage:
                errors.append(f"class {cname}: mixins and slot_usage are not supported")
            if c.extra_slots is not None and c.extra_slots.allowed is not False:
                errors.append(f"class {cname}: extra_slots (an open structure) is not supported yet")
            warnings += [f"class {cname}: unknown annotation '{t}'" for t in tags(c) if t not in ANNOTATIONS]
            layer = ann(c, "layer", default_layer)
            if layer not in LAYERS:
                errors.append(f"class {cname}: layer must be one of {LAYERS}, not {layer!r}")
            parent = names.resolve(m.id, c.is_a) if c.is_a else None
            if c.is_a and parent is None:  # LinkML cannot induce its slots either: nothing more to check
                errors.append(f"class {cname}: parent {c.is_a} is not in the import closure of {m.id}")
                continue
            ancestors = {cname}
            ancestor = c
            while ancestor.is_a:
                if ancestor.is_a in ancestors:
                    errors.append(f"class {cname}: inheritance forms a cycle through {ancestor.is_a}")
                    break
                parent_class = sv.get_class(ancestor.is_a)
                if parent_class is None:
                    errors.append(f"class {cname}: parent {ancestor.is_a} is not a kind")
                    break
                ancestors.add(ancestor.is_a)
                ancestor = parent_class
            if ancestor.is_a:
                continue
            induced = sv.class_induced_slots(cname)
            if any(s.key for s in induced):
                errors.append(f"class {cname}: use 'identifier', not 'key'")
            ident = [s.name for s in induced if s.identifier]
            if len(ident) > 1:
                errors.append(f"class {cname}: more than one identifier ({', '.join(sorted(ident))})")
            relationship = False
            for ancestor in sv.class_ancestors(cname, mixins=False):
                marker = sv.get_class(ancestor).represents_relationship
                if marker is not None:
                    relationship = bool(marker)
                    break
            if ann(c, "explain", "fold") != "fold":
                errors.append(f"class {cname}: explain is fold, not {ann(c, 'explain')!r}")
            kinds[k] = Kind(k, cname, layer, parent, bool(c.abstract), ident[0] if ident else None, module=m.id,
                            world=world(c, cname, errors), relationship=relationship, fold="explain" in tags(c))
            owner[k] = m
            kinds[k].span = placed(m, ("classes", cname))
            kinds[k].renamed_from = renamed_from(c, f"class {cname}", errors)
        for ename in sorted(sv.all_enums(imports=False)):
            e = names.name(m.id, ename)
            if not valid_name(e):
                errors.append(f"enum {ename}: name '{e}' is not a valid name")
            if e in enums:
                errors.append(f"enum {ename}: defined twice")
            enums[e] = list(sv.get_enum(ename).permissible_values or {})
    declared = units(mods, placed, errors)

    for k, kind in kinds.items():  # the root kind has the world; a subkind shares its tables, so its world too
        if kind.parent and "world" in tags(owner[k].sv.get_class(kind.cls)):
            errors.append(f"class {kind.cls}: world goes on the root kind; a subkind has the world of {kind.parent}")
        root, seen = kind, {k}
        while root.parent in kinds and root.parent not in seen:
            seen.add(root.parent)
            root = kinds[root.parent]
        kind.world = root.world
    for k, kind in sorted(kinds.items()):
        m, cname = owner[k], kind.cls
        sv = m.sv
        if kind.parent and kind.parent not in kinds:
            errors.append(f"class {cname}: parent {kind.parent} is not a kind of this pack")
            continue
        c = sv.get_class(cname)
        inherited = {s.name for s in sv.class_induced_slots(c.is_a)} if kind.parent else set()
        for s in sv.class_induced_slots(cname):
            rng = s.range or sv.schema.default_range
            where = f"{cname}.{s.name}"
            if s.name in inherited and s.name in set(c.attributes or {}) | set(c.slots or []):
                errors.append(f"{where}: redefines an inherited slot, which is not supported")
            if s.identifier and kind.parent and s.name not in inherited:
                errors.append(f"{where}: a subkind inherits the identifier of {kind.parent}; it cannot declare its own")
            if s.identifier and "world" in tags(s):
                errors.append(f"{where}: world goes on the class, not on its identifier")
            if s.identifier and "input_format" in tags(s):
                errors.append(f"{where}: input_format goes on a text attribute, not on an identifier")
            if s.identifier and "explore" in tags(s):
                errors.append(f"{where}: explore goes on a slot of whole numbers, not on an identifier")
            if s.name not in inherited:  # an inherited slot is checked where it is declared
                errors += [f"{where}: '{f}' is not supported yet" for f in UNSUPPORTED if getattr(s, f, None)]
            if s.name in inherited:
                continue
            if not NAME.match(s.name) or "__" in s.name or s.name == "is_a":
                errors.append(f"{where}: '{s.name}' is not a valid slot name")
            warnings += [f"{where}: unknown annotation '{t}'" for t in tags(s) if t not in ANNOTATIONS]
            if s.identifier:
                if not kind.parent:  # a subkind that declares one is refused above
                    kind.id_type = identifier_type(sv, s, rng, where, errors)
                    if kind.id_type == "VARCHAR":
                        kind.id_patterns = patterns(sv, s, rng, where, errors)
                continue
            slot = Slot(s.name, k, bool(s.required), False, rng, "VARCHAR", multivalued=bool(s.multivalued))
            own = world(s, where, errors)
            if kind.world == "open" and "world" in tags(s) and own != "open":
                errors.append(f"{where}: a slot of an open kind is open")
            slot.world = "open" if kind.world == "open" else own
            if rng in sv.all_classes():
                slot.arrow, slot.range, slot.inlined = True, names.resolve(m.id, rng), bool(s.inlined or s.inlined_as_list)
                if open_value(sv, rng):
                    errors.append(f"{where}: range {rng} is linkml:Any, an open value; Rezono types every value")
                if s.pattern:
                    errors.append(f"{where}: a pattern applies to text and enums, not to an arrow")
                if "explore" in tags(s):
                    errors.append(f"{where}: explore goes on a slot of whole numbers, not on an arrow")
            elif rng in sv.all_enums():
                slot.enum = slot.range = names.resolve(m.id, rng)
                slot.patterns = patterns(sv, s, rng, where, errors)  # enum values are text
                if "explore" in tags(s):
                    errors.append(f"{where}: explore goes on a slot of whole numbers, not on an enum")
            else:
                slot.sql_type = sql_type(sv, rng, where, errors)
                slot.minimum, slot.maximum = limits(sv, s, rng)
                bounds(slot, where, errors)
                if "explore" in tags(s):
                    slot.explore = explore(slot, plain(ann(s, "explore")), where, errors)
                slot.patterns = patterns(sv, s, rng, where, errors)
                if slot.patterns and slot.sql_type != "VARCHAR":
                    errors.append(f"{where}: a pattern applies to text only")
                slot.currency = currency(sv, s, rng, where, errors)
                if slot.currency and slot.sql_type != "BIGINT":
                    errors.append(f"{where}: a currency goes on whole numbers (minor units), not on {rng}")
                slot.unit = slot_unit(sv, rng, declared) if isinstance(rng, str) else None
            if "input_format" in tags(s):
                form = ann(s, "input_format")
                if not isinstance(form, str) or form not in INPUT_FORMATS:
                    errors.append(f"{where}: unknown input_format {form!r}")
                elif slot.type.bundle != "text" or slot.arrow:
                    errors.append(f"{where}: input_format goes on a text attribute")
                else:
                    slot.input_format = form
            cardinality(slot, s, where, errors)
            constant(slot, s, where, errors)
            slot.role = slot_role(sv, s)
            slot.span = placed(m, ("classes", cname, "attributes", s.name), ("classes", cname, "slots", ("=", s.name)),
                               ("classes", cname))
            slot.renamed_from = renamed_from(s, where, errors)
            slot.names = slot.role == "name"
            if slot.names and (slot.arrow or slot.enum or slot.multivalued or slot.sql_type != "VARCHAR"):
                errors.append(f"{where}: a name (slot_uri rdfs:label) is one text value, not an arrow, enum or list")
            elif slot.role and (slot.arrow or slot.enum or slot.multivalued
                                or slot.type.base != SLOT_ROLE_TYPES[slot.role]):
                want = {types.STRING: "text", types.INTEGER: "whole-number", types.DATE: "date"}[SLOT_ROLE_TYPES[slot.role]]
                errors.append(f"{where}: role {slot.role} is one {want} value, not an arrow, enum or list")
            kind.slots[s.name] = slot
        kind.slots = dict(sorted(kind.slots.items()))
        for kname, uk in sorted((c.unique_keys or {}).items()):
            if not valid_name(kname):
                errors.append(f"{cname}: unique key '{kname}' is not a valid name")
            kind.unique_keys.append((kname, list(uk.unique_key_slots)))
            kind.spans[f"key:{kname}"] = placed(m, ("classes", cname, "unique_keys", kname), ("classes", cname))
        for i, eq in enumerate(ann(c, "path_equations", []) or []):
            notes = ("classes", cname, "annotations", "path_equations")
            kind.spans[f"eq:{eq.get('name', '')}"] = placed(m, notes + (i,), notes + ("value", i), ("classes", cname))
            if not valid_name(str(eq.get("name", ""))):
                errors.append(f"{cname}: path equation '{eq.get('name')}' is not a valid name")
            kind.path_equations.append((str(eq.get("name", "")), eq["left"].split("."), eq["right"].split(".")))
        kind.path_equations.sort()
        kind.rules = class_rules(c, errors)
        if "seal" in tags(c):
            kind.seal = plain(ann(c, "seal"))
        if "sealed_with" in tags(c):
            kind.sealed_with = plain(ann(c, "sealed_with"))
        if "plane" in tags(c):
            kind.plane = plain(ann(c, "plane"))
        if "owner" in tags(c):
            kind.owner = plain(ann(c, "owner"))

    pack = Pack({"name": meta["name"], "version": str(meta["version"]), "default_language": meta["default_language"],
                 "theory": is_theory},
                [{"name": m.sv.schema.name, "id": m.sv.schema.id, "file": m.rel, "module": m.id, "pack": m.pack}
                 for m in mods
                 if m.form is None or "schema" in m.form["module"]
                 or m.sv.schema.classes or m.sv.schema.enums or m.sv.schema.types],
                dict(sorted(kinds.items())), dict(sorted(enums.items())), warnings=warnings, units=declared,
                imports=[{"name": p.name, "version": p.version, "sha256": p.sha256} for p in packs.values()])
    if not errors:
        check(pack, errors)
    if not errors:
        planes(pack, errors)
    if not errors:
        pack.sweeps = sweeps(pack, pack_dir, errors)
    calc_inputs, calc_parts, ordered, renames = {}, {}, {}, {}
    calc_bare_leaves: list[tuple[str, str, str, str]] = []
    if not errors:
        from . import calc  # calc reads the IR of this module, so it is imported here
        ordered = {n: packs[n] for n in modules.dependency_order(packs, modules.direct(meta))}
        renames = {p.name: rename(mods, p, names) for p in packs.values()}
        try:
            pack.calc, calc_parts = calc.read_closure(pack, pack_dir, ordered, renames, mods=mods,
                                                      bare_leaves=calc_bare_leaves)
            if pack.calc is not None:
                calc_inputs = calc.rule_input_columns(pack, pack.calc)
        except CompileError as e:
            errors.append(str(e))
            typed[str(e)] = e.diagnostics
    generated = []
    if not errors:
        from . import rezono_relational, rezono_table  # table lowering reads the pack's model
        forms = {m.rel: m.form for m in mods if m.pack_dir == pack_dir and m.form is not None}
        generated = rezono_table.lower_pack(pack, meta, pack_dir, errors, forms=forms)
    if not errors:
        from . import native_rule_lowering

        try:
            native = native_rule_lowering.lower_modules(meta, mods, packs, names)
            pack.rules, rule_warnings = rules_dl.read(pack, pack_dir, ordered, renames, calc_inputs=calc_inputs,
                                                      calc_parts=calc_parts, folds=pack.folds,
                                                      bodies=pack.rule_bodies, spans=pack.rule_spans,
                                                      generated=generated, embedded=rezono_relational.sources(mods),
                                                      native=native)
            pack.warnings += rule_warnings
            if pack.rules:   # a variable or a column that joins two currencies is an error
                amounts.columns(pack.rules, amounts.tables(pack))
        except (rules_dl.RuleError, CompileError) as e:
            errors.append(str(e))
            if isinstance(e, Diagnosed):
                typed[str(e)] = e.diagnostics
    if not errors and (view_file := views.admit(pack_dir)) is not None:
        # A view that executes: typed against the theory as its own pack, then lowered to ordinary
        # rules, and every rule that read a mapped theory table is bound to the view's relation.
        from . import view_rules, view_typing
        try:
            missing = sorted(v.theory for v in view_file.views if v.theory not in packs)
            if missing:
                raise views.ViewError(f"{pack_dir / 'views.yaml'}: views[{missing[0]}].theory: expected a pinned import")
            theories = {v.theory: read(packs[v.theory].dir) for v in view_file.views}
            found = spans.marks(pack_dir / "views.yaml")
            written = (strict_yaml.read(pack_dir / "views.yaml") or {}).get("views") or []
            for view in view_typing.resolve(view_file, pack, theories, source=pack_dir / "views.yaml").views:
                before = {r["id"] for r in (pack.rules or {}).get("rules", [])}
                pack.rules = view_rules.bind(pack.rules, view, pack, theories[view.theory], renames[view.theory],
                                             source=view_rules.SOURCE)
                # MOD2: a rule the view generates is written where the view is
                at = [("views", i) for i, v in enumerate(written) if isinstance(v, dict) and v.get("theory") == view.theory]
                span = spans.first(found, view_rules.SOURCE, *at, ("views",))
                for r in (pack.rules or {}).get("rules", []):
                    if r["id"] not in before:
                        pack.rule_spans[r["id"]] = span
        except (views.ViewError, view_rules.ViewRuleError, CompileError) as e:
            errors.append(str(e))
            if isinstance(e, Diagnosed):
                typed[str(e)] = e.diagnostics
    if not errors and pack.seals and pack.rules:
        from . import seal
        seal.check_rules(pack, pack.rules, errors)
    if not errors and pack.calc is not None:
        from . import calc, calc_sql, rezono_calc, rules as rule_ir
        try:
            if calc_bare_leaves and pack.rules:
                rezono_calc.check_relation_ambiguity(pack, calc_bare_leaves)
            # every check now, so `check` reports it in seconds, a unit error at its place in a calc file (P10.3)
            calculation = calc.build(pack, pack.calc, files=calc.files_of(pack_dir, meta["name"], ordered))
            calc.check_imports(pack, calculation, calc_parts, ordered, renames)
            used = {r["name"] for r in (pack.rules or {}).get("relations", []) if r["role"] == "calc"}
            if used:
                numeric = {name for rule, name in calculation.engine.items() if calculation.types[rule] == calc.NUMBER}
                if invalid := used - numeric:
                    raise CompileError(f"rules: a calculation input needs a numeric selection: {', '.join(sorted(invalid))}")
                program = rule_ir.load(pack.rules)
                _, after = program.partition_at_calc(used, calc_sql.derived_reads(calculation))
                if "may_read" in after:
                    raise CompileError("rules: may_read cannot depend on a calculation selection")
        except (CompileError, rule_ir.IRError) as e:
            errors.append(str(e))
            if isinstance(e, CompileError):
                typed[str(e)] = e.diagnostics
        subject = (pack.calc or {}).get("subject")
        inputs = ((pack.calc or {}).get("inputs") or {}).get("kind")
        # A part counts only when its sealed element does (docs/compiler.md#parts): the same refusal holds for it.
        sealed = {k for s in pack.seals for k in (s.kind, *(p.kind for p in s.parts))}
        what = "a sealed kind or a part of one"
        if subject in pack.kinds and pack.root(subject) in sealed:
            errors.append(f"calc.program: subject '{subject}' is {what}; a calculation reads it through "
                          "a rule that reads its accepted rows")
        if inputs in pack.kinds and pack.root(inputs) in sealed:  # the calculation would read refused input too
            errors.append(f"calc.binding: inputs.kind '{inputs}' is {what}; a calculation reads it through "
                          "a rule that reads its accepted rows")
        parameters = ((pack.calc or {}).get("parameters") or "").partition(".")[0]
        if parameters in pack.kinds and pack.root(parameters) in sealed:  # a refused row would set a parameter
            errors.append(f"calc.binding: parameters: kind '{parameters}' is {what}; a calculation reads it "
                          "through a rule that reads its accepted rows")
    if not errors:
        pack.channels = channels(pack, pack_dir, ordered, renames, errors)
        pack.questions = questions(pack, pack_dir, ordered, errors)
        pack_reasons: dict[str, list[tuple[str, str]]] = {}
        for m in mods:
            if m.reasons:
                pack_reasons.setdefault(m.pack, []).extend(m.reasons)
        language(pack, pack_dir, ordered, renames, errors, reasons=pack_reasons)
        pack.iri = iris(pack, meta, packs, owner, errors)
    if not errors:
        fold.check(pack, errors)
    if errors:
        raise CompileError("\n".join(errors), [d for e in errors for d in typed.get(e) or diagnostics.of_text(e)])
    for w in pack.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return pack


def slot_role(sv: SchemaView, s) -> str | None:
    """Recognise the S26 role from the module's CURIE prefixes or a full IRI, never from a slot name."""
    uri = s.slot_uri
    if not uri:
        return None
    if uri == "rdfs:label":
        return "name"  # S15 compatibility: the standard name CURIE was already recognised directly
    try:
        uri = sv.expand_curie(uri)
    except Exception:  # an undeclared prefix has no recognised role
        return None
    if uri.startswith("https://schema.org/"):
        uri = "http://schema.org/" + uri[len("https://schema.org/"):]
    return SLOT_ROLE_URIS.get(uri)


def rename(mods: list[modules.Module], imported: modules.Imported, names: modules.Names) -> dict[str, str]:
    """For an imported pack: the name of each class and enum it can see (its own and those of the packs it
    imports) on its own, and in this pack. Its labels and channels use its own names; a clash in this pack
    qualifies them."""
    by_pack = {}
    for m in mods:
        by_pack.setdefault(m.pack, []).append(m)
    packs = {imported.name}
    todo = [imported.name]
    while todo:
        for m in by_pack.get(todo.pop(), []):
            for i in m.imports:
                p = i.partition(":")[0]
                if p not in packs:
                    packs.add(p)
                    todo.append(p)
    alone = modules.Names([m for m in mods if m.pack in packs], snake, [], root=imported.name)
    return {alone.name(m.id, n): names.name(m.id, n) for m in mods if m.pack in packs for n in names.declared[m.id]}


def renamed(element: str, renames: dict[str, str]) -> str:
    head, sep, tail = element.partition(".")
    return renames.get(head, head) + sep + tail


def patterns(sv: SchemaView, s, rng: str, where: str, errors: list[str]) -> list[str]:
    """The patterns of a slot and of its type and the types it derives from, in portable form."""
    found = [s.pattern] if s.pattern else []
    t = sv.get_type(rng)
    while t is not None:
        if t.pattern:
            found.append(t.pattern)
        t = sv.get_type(t.typeof) if t.typeof else None
    out = []
    for p in found:
        try:
            q = portable(p)
        except PatternError as e:
            errors.append(f"{where}: pattern {p!r}: {e}")
            continue
        if q not in out:
            out.append(q)
    return out


def currency(sv: SchemaView, s, rng: str, where: str, errors: list[str]) -> str | None:
    """The annotation `currency` of a slot, else of its type or a type it derives from: an ISO 4217 code.
    The values are then whole minor units of that currency (cents for EUR), never a fraction."""
    found = ann(s, "currency")
    t = sv.get_type(rng)
    while found is None and t is not None:
        found = ann(t, "currency")
        t = sv.get_type(t.typeof) if t.typeof else None
    if found is None:
        return None
    if not isinstance(found, str) or not CURRENCY.match(found):
        errors.append(f"{where}: currency {found!r} is not an ISO 4217 code (three capitals, such as EUR)")
        return None
    return found


UNIT_TAGS = ("dimension", "unit", "currency")  # the annotations that make a LinkML type a unit (P10.3)


def located(span) -> str:
    """A span (spans.py) as the start of a message: `file:line:column: `, or nothing when it is not known."""
    return f"{span[0]}:{span[1]}:{span[2]}: " if span else ""


def units(mods, placed, errors: list[str]) -> dict[str, types.Unit]:
    """The units of measure the modules declare (P10.3), by the name of their LinkML type, as Rezono's `unit`
    (docs/rezono/v0.md §5) says it in the current syntax:
    - `dimension: data` makes the type the base unit of the dimension `data` (`unit B = integer`);
    - `unit: 2^30 B` makes it an exact multiple of a declared unit (`unit GiB = 2^30 B`), also `per` a unit;
    - `currency: EUR` makes it the minor unit of a currency (`unit Cents = money minor EUR`), dimension `money EUR`.
    A unit is a type of whole numbers. The units are the pack's data: the compiler knows none of its own."""
    found: dict[str, tuple] = {}  # name -> (tag, value, where)
    for m in mods:
        for tname in sorted(m.sv.all_types(imports=False)):
            t = m.sv.get_type(tname)
            given = [tag for tag in UNIT_TAGS if tag in tags(t)]
            if not given:
                continue
            where = f"{located(placed(m, ('types', tname, 'annotations', given[0]), ('types', tname)))}type {tname}"
            value = plain(ann(t, given[0]))
            if tname in found and found[tname][:2] != (given[0], value):
                errors.append(f"{where}: unit {tname} is declared twice, differently")
                continue
            if len(given) > 1:
                errors.append(f"{where}: a unit is declared by one of {', '.join(UNIT_TAGS)}, not by {' and '.join(given)}")
                continue
            if given[0] != "currency" and sql_type(m.sv, tname, where, []) != "BIGINT":
                errors.append(f"{where}: a unit is a type of whole numbers (typeof integer)")
                continue
            found[tname] = (given[0], value, where)
    out: dict[str, types.Unit] = {}
    bases: dict[str, str] = {}
    for name, (tag, value, where) in sorted(found.items()):
        if tag == "currency":
            if isinstance(value, str) and CURRENCY.match(value):  # else every slot of the type says why (`currency`)
                out[name] = types.money_unit(value, name)
        elif tag == "dimension":
            if not isinstance(value, str) or not types.DIMENSION.match(value):
                errors.append(f"{where}: dimension {value!r} is no name of a dimension (lower case, such as data)")
            elif value in bases:
                errors.append(f"{where}: dimension {value} has two base units, {bases[value]} and {name}; "
                              f"define one by the other (unit: <factor> {bases[value]})")
            else:
                bases[value] = name
                out[name] = types.base_unit(name, value)
    waiting = {n: (str(v), w) for n, (tag, v, w) in found.items() if tag == "unit"}
    while waiting:  # a definition may name a unit defined after it; one that never resolves is an error below
        ready = {n for n, (v, _) in waiting.items()
                 if all(u in out for u in re.findall(r"[A-Za-z][A-Za-z0-9_]*", v) if u != "per")}
        if not ready:
            break
        for n in sorted(ready):
            value, where = waiting.pop(n)
            try:
                out[n] = types.defined(n, value, out)
            except ValueError as e:
                errors.append(f"{where}: unit {e}")
    for n, (value, where) in sorted(waiting.items()):
        try:
            types.defined(n, value, {**out, **{w: types.PLAIN for w in waiting}})
        except ValueError as e:
            errors.append(f"{where}: unit {e}")
            continue
        errors.append(f"{where}: unit {value!r} names a unit that is not declared, or the definitions form a cycle")
    return dict(sorted(out.items()))


def slot_unit(sv: SchemaView, rng: str, declared: dict[str, types.Unit]) -> str | None:
    """The unit of a slot's values: the first type in its range's typeof chain that declares one. A currency type
    is named too; its slot stays money (`currency`), and the name is how a message names its unit."""
    t = sv.get_type(rng)
    while t is not None:
        if any(tag in tags(t) for tag in UNIT_TAGS):
            return t.name if t.name in declared else None
        t = sv.get_type(t.typeof) if t.typeof else None
    return None


def open_value(sv: SchemaView, cname: str) -> bool:
    """Whether a class is LinkML's open value (class_uri linkml:Any)."""
    uri = sv.get_class(cname).class_uri
    if uri in ("linkml:Any", ANY_URI):  # also when the schema declares no linkml prefix
        return True
    try:
        return bool(uri) and sv.expand_curie(uri) == ANY_URI
    except Exception:  # an undeclared prefix: not linkml:Any
        return False


def limits(sv: SchemaView, s, rng: str) -> tuple:
    """minimum_value and maximum_value of a slot and of its type and the types it derives from: every limit
    holds, so the highest minimum and the lowest maximum."""
    los, his = [s.minimum_value], [s.maximum_value]
    t = sv.get_type(rng)
    while t is not None:
        los.append(t.minimum_value)
        his.append(t.maximum_value)
        t = sv.get_type(t.typeof) if t.typeof else None
    los, his = [x for x in los if x is not None], [x for x in his if x is not None]
    try:
        return (max(los) if los else None), (min(his) if his else None)
    except TypeError:  # limits of different sorts: bounds() reports the one that is not a whole number
        return (los[0] if los else None), (his[0] if his else None)


def cardinality(slot: Slot, s, where: str, errors: list[str]) -> None:
    """minimum_cardinality, maximum_cardinality and exact_cardinality of a multivalued slot. Every one given
    holds, so an exact count beside a minimum above it or a maximum below it is an error, never an override."""
    lo, hi, exact = s.minimum_cardinality, s.maximum_cardinality, s.exact_cardinality
    given = [b for b in (lo, hi, exact) if b is not None]
    if not given:
        return
    if not slot.multivalued:
        errors.append(f"{where}: a cardinality applies to multivalued slots only")
    elif any(isinstance(b, bool) or not isinstance(b, int) or not 0 <= b <= BIGINT[1] for b in given):
        errors.append(f"{where}: a cardinality is a whole number, at least 0")
    elif lo is not None and hi is not None and lo > hi:
        errors.append(f"{where}: minimum_cardinality {lo} is above maximum_cardinality {hi}")
    elif exact is not None and lo is not None and lo > exact:
        errors.append(f"{where}: exact_cardinality {exact} is below minimum_cardinality {lo}")
    elif exact is not None and hi is not None and hi < exact:
        errors.append(f"{where}: exact_cardinality {exact} is above maximum_cardinality {hi}")
    elif exact is not None:
        slot.minimum_cardinality = slot.maximum_cardinality = exact
    else:
        slot.minimum_cardinality, slot.maximum_cardinality = lo, hi


def constant(slot: Slot, s, where: str, errors: list[str]) -> None:
    """equals_string on text or an enum, equals_number on an integer: the one allowed value."""
    if s.equals_string is not None and s.equals_number is not None:
        errors.append(f"{where}: equals_string and equals_number together")
    elif s.equals_string is not None:
        if slot.arrow or slot.sql_type != "VARCHAR":
            errors.append(f"{where}: equals_string applies to text and enums only")
        slot.constant = str(s.equals_string)
    elif s.equals_number is not None:
        n = s.equals_number
        if slot.sql_type != "BIGINT" or slot.arrow:
            errors.append(f"{where}: equals_number applies to integers only")
        elif isinstance(n, bool) or not isinstance(n, int) or not BIGINT[0] <= n <= BIGINT[1]:
            errors.append(f"{where}: equals_number must be a whole number within BIGINT")
        slot.constant = n


def facets(sd) -> dict:
    """The facets set on a LinkML slot definition (not its name)."""
    out = {}
    for f, v in vars(sd).items():
        if f.startswith("_") or f == "name" or v is None or (isinstance(v, (list, dict)) and not v):
            continue
        out[f] = str(v) if f == "value_presence" else v
    return out


def class_rules(c, errors: list[str]) -> list[ClassRule]:
    """The LinkML `rules` of a class: slot conditions only (docs/compiler.md)."""
    out = []
    for i, r in enumerate(c.rules or [], 1):
        where = f"class {c.name} rule {i}"
        if r.deactivated:
            continue
        if r.bidirectional or r.open_world:
            errors.append(f"{where}: bidirectional and open_world are not supported")
        parts = []
        for label, expr in (("preconditions", r.preconditions), ("postconditions", r.postconditions),
                            ("elseconditions", r.elseconditions)):
            conds = []
            if expr is not None:
                other = sorted(f for f, v in facets(expr).items() if f != "slot_conditions")
                if other:
                    errors.append(f"{where}: {label} with {', '.join(other)}; only slot_conditions are supported")
                for slot, sd in sorted((expr.slot_conditions or {}).items()):
                    fs = facets(sd)
                    bad = sorted(set(fs) - CONDITIONS)
                    if bad:
                        errors.append(f"{where}: condition on {slot} uses {', '.join(bad)}; "
                                      f"supported are {', '.join(sorted(CONDITIONS))}")
                    if fs.get("pattern"):
                        try:
                            fs["pattern"] = portable(fs["pattern"])
                        except PatternError as e:
                            errors.append(f"{where}: pattern {fs['pattern']!r}: {e}")
                    if fs.get("value_presence") not in (None, "PRESENT", "ABSENT"):
                        errors.append(f"{where}: value_presence must be PRESENT or ABSENT")
                    conds.append(Condition(str(slot), fs))
            parts.append(conds)
        if not parts[1] and not parts[2]:
            errors.append(f"{where}: has no postconditions or elseconditions")
        out.append(ClassRule(f"rule_{i}", *parts))
    return out


def bounds(slot: Slot, where: str, errors: list[str]) -> None:
    given = [b for b in (slot.minimum, slot.maximum) if b is not None]
    if given and slot.sql_type != "BIGINT":
        errors.append(f"{where}: minimum/maximum only on integer types")
    elif any(isinstance(b, bool) or not isinstance(b, int) or not BIGINT[0] <= b <= BIGINT[1] for b in given):
        errors.append(f"{where}: minimum/maximum must be whole numbers within BIGINT")
    elif len(given) == 2 and slot.minimum > slot.maximum:
        errors.append(f"{where}: minimum {slot.minimum} is above maximum {slot.maximum}")


def planes(pack: Pack, errors: list[str]) -> None:
    """A kind of decided values (DV1; O13; publication L0 §3.7): `plane: control` on a class, with `owner`, the role
    or team that reviews a change to it. Its rows are values a reviewed proposal set, so each names its decision:
    the kind has a required, single-valued slot `decision`, text or an arrow (to the kind that records decisions).
    A data-plane kind says nothing: `plane: data` is not written, so every pack without a control kind keeps its
    bytes. A subkind of a control kind is one too."""
    for k, kind in pack.kinds.items():
        where = f"class {kind.cls}"
        if kind.plane is None:
            if kind.owner is not None:
                errors.append(f"{where}: owner is said of a control kind only (plane: control)")
            continue
        if kind.plane != "control":
            errors.append(f"{where}: plane is only ever control; a data-plane kind leaves it out, not {kind.plane!r}")
            continue
        if kind.parent is not None and not any(pack.kinds[a].plane == "control" for a in pack.ancestors(kind.parent)):
            # It would share its parent's slot tables, where a record of the parent adds rows without review.
            errors.append(f"{where}: a control kind is a root kind or below a control kind, not below a data-plane kind")
        if not (isinstance(kind.owner, str) and kind.owner.strip()):
            errors.append(f"{where}: a control kind names its owner, who reviews a change to it")
        decision = pack.slot(k, "decision")
        if decision is None or not decision.required or decision.multivalued or decision.inlined or not (
                decision.arrow or (decision.sql_type == "VARCHAR" and decision.enum is None)):
            errors.append(f"{where}: a control kind has a required, single-valued slot decision, text or an arrow")


def seals(pack: Pack, errors: list[str]) -> list[Seal]:
    """The sealed kind: `seal: <slot>` on a root kind names its period, a required single date.
    A pack with a seal has PeriodClose with the required date closed_until and covers, an inlined list of a
    kind without identifier that has exactly the required arrow `element` to the sealed kind and the
    required text `sha256`. One sealed kind per pack for now; its parts are kinds with `sealed_with` (`parts`)."""
    def single(slot: Slot | None, sql_type: str) -> bool:
        return (slot is not None and slot.required and not slot.multivalued and not slot.enum
                and not slot.arrow and slot.sql_type == sql_type)

    out = []
    for k, kind in pack.kinds.items():
        if kind.seal is None:
            continue
        where = f"class {kind.cls}: seal"
        period = pack.slot(k, kind.seal) if isinstance(kind.seal, str) else None
        if kind.parent:
            errors.append(f"{where} goes on the root kind, not on a subkind of {pack.root(k)}")
        elif kind.identifier is None:
            errors.append(f"{where} needs an identifier, so that a refused row has a name")
        elif k == CLOSE:
            errors.append(f"{where}: the closing fact itself cannot be sealed")
        elif not single(period, "DATE"):
            errors.append(f"{where} names the period: one required, single date slot of {kind.cls}, not {kind.seal!r}")
        else:
            out.append(Seal(k, period))
    if len(out) > 1:
        errors.append(f"seal: one sealed kind per pack for now, not {', '.join(s.kind for s in out)}")
        return []
    if not out:
        for kind in pack.kinds.values():
            if kind.sealed_with is not None:
                errors.append(f"class {kind.cls}: sealed_with, but the pack seals no kind")
        return out
    s = out[0]
    close = pack.kinds.get(CLOSE)
    covers = pack.slot(CLOSE, COVERS) if close else None
    if close is None or close.parent or close.identifier is None or not single(pack.slot(CLOSE, CLOSED_UNTIL), "DATE"):
        errors.append(f"a seal needs the kind PeriodClose ({CLOSE}) with an identifier and the required date {CLOSED_UNTIL}")
    elif covers is None or not (covers.arrow and covers.inlined and covers.multivalued):
        errors.append(f"PeriodClose.{COVERS} must be an inlined list of covers (the rows a close closes)")
    else:
        c = pack.kinds[covers.range]
        element = pack.slot(c.name, ELEMENT)
        if (c.identifier is not None or c.parent or {x.name for x in pack.all_slots(c.name)} != {ELEMENT, SHA256}
                or element is None or not (element.arrow and element.required and not element.multivalued)
                or element.inlined or element.range != s.kind or not single(pack.slot(c.name, SHA256), "VARCHAR")):
            errors.append(f"class {c.cls}: a cover has exactly the required arrow {ELEMENT} to "
                          f"{pack.kinds[s.kind].cls} and the required text {SHA256}, and no identifier")
        s.cover = c.name
    # The row: every attribute and arrow table of the kind and its subkinds, and the subkinds' own tables, so
    # that membership of a subkind is part of the row a close holds.
    s.tables = family_tables(pack, s.kind)
    s.parts = parts(pack, s, errors)
    return out


def family_tables(pack: Pack, root: str) -> list[str]:
    family = [k for k in pack.kinds if pack.root(k) == root]
    return sorted([t.table for k in family for t in pack.kinds[k].slots.values()] + [k for k in family if k != root])


def parts(pack: Pack, s: Seal, errors: list[str]) -> list[Part]:
    """The parts of the sealed kind: `sealed_with: <slot>` on a root kind names a required, single arrow to the
    sealed kind or to another part, so every part reaches one sealed element. Ordered so that an owner comes
    before its parts; a cycle, or an arrow to a kind outside the seal, is refused."""
    found = {}
    for k, kind in pack.kinds.items():
        if kind.sealed_with is None:
            continue
        where = f"class {kind.cls}: sealed_with"
        arrow = pack.slot(k, kind.sealed_with) if isinstance(kind.sealed_with, str) else None
        if kind.parent:
            errors.append(f"{where} goes on the root kind, not on a subkind of {pack.root(k)}")
        elif kind.identifier is None:
            errors.append(f"{where} needs an identifier, so that a part has a name in the row")
        elif k in (CLOSE, s.kind) or kind.seal is not None:
            errors.append(f"{where}: the sealed kind and the closing fact are not parts")
        elif (arrow is None or not arrow.arrow or not arrow.required or arrow.multivalued or arrow.inlined
              or arrow.range not in pack.kinds):
            errors.append(f"{where} names the element it is part of: one required, single arrow of {kind.cls}, "
                          f"not {kind.sealed_with!r}")
        else:
            found[k] = Part(k, arrow, pack.root(arrow.range), family_tables(pack, k))
    out, placed = [], {s.kind}
    while found:
        ready = sorted(k for k, part in found.items() if part.owner in placed)
        if not ready:
            for k, part in sorted(found.items()):
                errors.append(f"class {pack.kinds[k].cls}: sealed_with points to {part.owner}, which is neither the "
                              f"sealed kind {s.kind} nor a part of it: a cycle, or an arrow outside the seal")
            return []
        for k in ready:
            out.append(found.pop(k))
            placed.add(k)
    return out


def plain(value):
    """An annotation value as plain data: LinkML may give a nested mapping as a JsonObj."""
    if hasattr(value, "_as_dict"):
        value = value._as_dict
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and BIGINT[0] <= v <= BIGINT[1]


def explore(slot: Slot, given, where: str, errors: list[str]) -> tuple[int, int, int] | None:
    """The grid of a sweep on this slot: `explore: {step}`, within the slot's minimum and maximum. `min` and
    `max` may narrow that range, never widen it. Whole numbers only: money in minor units, a count."""
    if slot.sql_type != "BIGINT" or slot.multivalued:
        errors.append(f"{where}: explore goes on a single slot of whole numbers")
        return None
    if not isinstance(given, dict) or set(given) - {"min", "max", "step"} or "step" not in given:
        errors.append(f"{where}: explore must be a mapping with step, and optionally min and max")
        return None
    step, lo, hi = given["step"], given.get("min", slot.minimum), given.get("max", slot.maximum)
    if not whole(step) or step <= 0:
        errors.append(f"{where}: explore step must be a whole number above 0, not {step!r}")
        return None
    if lo is None or hi is None:
        errors.append(f"{where}: explore needs a range: minimum_value and maximum_value on the slot, or min and max")
        return None
    if not whole(lo) or not whole(hi):
        errors.append(f"{where}: explore min and max must be whole numbers within BIGINT")
        return None
    if slot.minimum is not None and lo < slot.minimum or slot.maximum is not None and hi > slot.maximum:
        errors.append(f"{where}: explore range {lo}..{hi} is wider than the slot's {slot.minimum}..{slot.maximum}")
        return None
    if lo > hi:
        errors.append(f"{where}: explore min {lo} is above max {hi}")
        return None
    if (hi - lo) // step + 1 > MAX_GRID:
        errors.append(f"{where}: explore gives {(hi - lo) // step + 1} values, more than {MAX_GRID}; "
                      f"the smallest step that fits is {(hi - lo) // MAX_GRID + 1}")
        return None
    return lo, hi, step


def sweeps(pack: Pack, pack_dir: Path, errors: list[str]) -> list[dict]:
    """The sweeps of `sweeps.yaml`: each names one fact cell (kind, key, slot), as a delta `set` does. The
    range comes from the slot's `explore`, so every sweep on a slot has the same grid."""
    path = pack_dir / "sweeps.yaml"
    if not path.exists():
        return []
    doc = strict_yaml.read(path)
    if not isinstance(doc, dict) or set(doc) != {"sweeps"} or not isinstance(doc["sweeps"], list):
        errors.append("sweeps.yaml: must be a mapping with one key, sweeps, a list")
        return []
    if len(doc["sweeps"]) > MAX_SWEEPS:
        errors.append(f"sweeps.yaml: {len(doc['sweeps'])} sweeps; a pack has at most {MAX_SWEEPS}")
    out, names = [], set()
    for n, sw in enumerate(doc["sweeps"]):
        where = f"sweeps.yaml: sweep {n}"
        if not isinstance(sw, dict) or set(sw) != {"name", "kind", "key", "slot"}:
            errors.append(f"{where}: needs exactly name, kind, key and slot")
            continue
        name, kind, key, slot_name = sw["name"], sw["kind"], sw["key"], sw["slot"]
        if not isinstance(name, str) or not NAME.match(name) or "__" in name or "-" in name:
            errors.append(f"{where}: name {name!r} must be lower snake case")
            continue
        if name in names:
            errors.append(f"{where}: name {name!r} is used twice")
        names.add(name)
        where = f"sweeps.yaml: sweep {name}"
        if kind not in pack.kinds or pack.kinds[kind].abstract:
            errors.append(f"{where}: {kind!r} is not a kind of this pack that has facts")
            continue
        slot = pack.slot(kind, slot_name) if isinstance(slot_name, str) else None
        if slot is None:
            errors.append(f"{where}: kind {kind} has no slot {slot_name!r} (the identifier cannot be swept)")
            continue
        if slot.explore is None:
            errors.append(f"{where}: slot {slot.element} has no `explore: {{step}}` with a range")
            continue
        if whole(key):
            key = str(key)
        if not isinstance(key, str):
            errors.append(f"{where}: key must be text or a whole number, not {key!r}")
            continue
        files = fact_files(pack, pack_dir, kind, key)
        if len(files) != 1:
            errors.append(f"{where}: {kind} {key!r} is {'in no fact file' if not files else 'in ' + ', '.join(files)}; "
                          "a sweep needs it in exactly one")
            continue
        lo, hi, step = slot.explore
        out.append({"name": name, "kind": kind, "key": key, "slot": slot.name,
                    "min": lo, "max": hi, "step": step, "count": (hi - lo) // step + 1})
    return out


def fact_files(pack: Pack, pack_dir: Path, kind: str, key: str) -> list[str]:
    """The fact files with a record of this kind (its section) whose identifier, as text, is `key`."""
    ident = pack.kinds[pack.root(kind)].identifier
    found = []
    from .facts import files
    for f in files(pack_dir):
        data = strict_yaml.read(f) or {}
        records = data.get(kind) if isinstance(data, dict) else None
        if any(isinstance(r, dict) and ident in r and not isinstance(r[ident], bool) and str(r[ident]) == key
               for r in records or []):
            found.append(f"facts/{f.name}")
    return found


def identifier_type(sv: SchemaView, s, rng: str, where: str, errors: list[str]) -> str:
    """An identifier is one whole number or one text; a text identifier may carry a pattern. Limits, also those of
    its type, are an error: an identifier has none."""
    if s.multivalued or limits(sv, s, rng) != (None, None):
        errors.append(f"{where}: an identifier cannot be multivalued or carry minimum or maximum (also not from its type)")
    # What a slot may say and an identifier cannot hold is an error, never dropped (nothing ignored).
    given = [f for f in ("minimum_cardinality", "maximum_cardinality", "exact_cardinality", "equals_string",
                         "equals_number") if getattr(s, f, None) is not None]
    given += ["annotation currency"] if "currency" in tags(s) else []
    given += [f"role {role}"] if (role := slot_role(sv, s)) else []
    errors += [f"{where}: an identifier names its element; it cannot carry {f}" for f in given]
    if rng in sv.all_classes() or rng in sv.all_enums():
        errors.append(f"{where}: an identifier must be text or a whole number")
        return "VARCHAR"
    t = sql_type(sv, rng, where, errors)
    if t not in ("VARCHAR", "BIGINT"):
        errors.append(f"{where}: an identifier must be text or a whole number")
    return t


def sql_type(sv: SchemaView, name: str, where: str, errors: list[str]) -> str:
    t = sv.get_type(name)
    while t is not None and t.typeof:
        t = sv.get_type(t.typeof)
    root = t.name if t is not None else name
    base = types.linkml(root)
    if root in types.FLOATING:
        errors.append(f"{where}: floating point type '{root}' is not allowed; use integer cents")
    elif base is None:
        errors.append(f"{where}: type '{root}' is not supported")
    return types.scalar(base).sql if base else "VARCHAR"


def check(pack: Pack, errors: list[str]) -> None:
    """Cross-kind checks: arrows, identifiers, keys, path equations and element ids."""
    targets = set()
    for kind in pack.kinds.values():
        for s in kind.slots.values():
            if not s.arrow:
                continue
            if s.inlined:
                targets.add(s.range)
            elif pack.kinds[pack.root(s.range)].identifier is None:
                errors.append(f"{kind.cls}.{s.name}: range {s.range} has no identifier, so it must be inlined")
            s.sql_type = pack.kinds[pack.root(s.range)].id_type
        for name, slots in kind.unique_keys:
            for sn in slots:
                if pack.slot(kind.name, sn) is None:
                    errors.append(f"{kind.cls} unique key {name}: unknown slot {sn}")
        for name, left, right in kind.path_equations:
            ends = [path_end(pack, kind.name, p, f"{kind.cls} path equation {name}", errors) for p in (left, right)]
            if None not in ends and pack.root(ends[0]) != pack.root(ends[1]):
                errors.append(f"{kind.cls} path equation {name}: paths end in unrelated kinds {ends}")
        for r in kind.rules:
            for c in r.pre + r.post + r.otherwise:
                condition(pack, kind, r, c, errors)
    pack.seals = seals(pack, errors)
    for kind in pack.kinds.values():
        named = [s.element for s in pack.all_slots(kind.name) if s.names]
        if len(named) > 1:
            errors.append(f"{kind.cls}: more than one name (slot_uri rdfs:label): {', '.join(named)}")
        for role in SLOT_ROLE_TYPES:
            slots = [s.element for s in pack.all_slots(kind.name) if s.role == role]
            if role != "name" and len(slots) > 1:
                errors.append(f"{kind.cls}: more than one {role} slot: {', '.join(slots)}")
        if kind.relationship:
            if named:
                errors.append(f"{kind.cls}: represents_relationship forbids a name attribute; its ends name it")
            if not pack.ends(kind.name):
                errors.append(f"{kind.cls}: represents_relationship needs a unique key of at least two distinct "
                              "single-valued arrows")
        if kind.parent is None and kind.identifier is None and kind.name not in targets:
            errors.append(f"{kind.cls}: no identifier and never inlined, so it can have no elements")
    for e in pack.enums:
        if e in pack.kinds:
            errors.append(f"enum {e}: name is also a kind")
    ids = pack.elements()
    errors += [f"element id '{e}' is used twice" for e in sorted({e for e in ids if ids.count(e) > 1})]


def condition(pack: Pack, kind: Kind, rule: ClassRule, c: Condition, errors: list[str]) -> None:
    """A rule condition names a slot of the kind (or an ancestor) and facets that fit its type."""
    where = f"class {kind.cls} {rule.name}: condition on {c.slot}"
    s = pack.slot(kind.name, c.slot)
    if s is None:
        errors.append(f"{where}: not a slot of {kind.name} (the identifier cannot be a condition)")
        return
    f = c.facets
    if ("equals_string" in f or "pattern" in f) and (s.arrow or s.sql_type != "VARCHAR"):
        errors.append(f"{where}: equals_string and pattern apply to text and enums only")
    numbers = [f[x] for x in ("equals_number", "minimum_value", "maximum_value") if x in f]
    if numbers and (s.arrow or s.sql_type != "BIGINT"):
        errors.append(f"{where}: equals_number, minimum_value and maximum_value apply to integers only")
    elif any(isinstance(n, bool) or not isinstance(n, int) or not BIGINT[0] <= n <= BIGINT[1] for n in numbers):
        errors.append(f"{where}: numbers must be whole and within BIGINT")


def path_end(pack: Pack, kind: str, path: list[str], where: str, errors: list[str]) -> str | None:
    for step in path:
        s = pack.slot(kind, step)
        if s is None or not s.arrow:
            errors.append(f"{where}: '{step}' is not an arrow of {kind}")
            return None
        if s.multivalued:  # one end per path is what the view compares; sets of ends are not supported yet
            errors.append(f"{where}: '{step}' is a multivalued arrow, which a path equation cannot follow yet")
            return None
        kind = s.range
    return kind


def channels(pack: Pack, pack_dir: Path, packs: dict, renames: dict, errors: list[str]) -> dict:
    """The pack's part of the key: a shape per kind, with an icon if it names one, and a dash per arrow, as in
    contracts/view.yaml. An icon is a file of the pack that names it, checked and carried as a tree (icons.py).
    Imported packs' signs come first, a dependency before the pack that imports it, under this pack's names;
    the pack's own signs win. A pack binds at most one relief, from its own table or one import's: a second is
    refused, never silently replaced. `sources` says where each binding is written (MOD2): its id is
    `<section>/<kind, arrow or sheet>`, or the section of the one relief, home or house style."""
    path = pack_dir / "channels.yaml"
    if not path.exists():
        errors.append(f"{path}: missing channel table")
        return {}
    view = SchemaView(str(contract_dir() / "view.yaml"))
    shapes = set(view.get_enum("Shape").permissible_values)
    arrows = {s.element for kind in pack.kinds.values() for s in kind.slots.values() if s.arrow}
    # A derived relation that a Flow draws as lines has a dash like an arrow (docs/gui.md, Edge source).
    arrows |= {r["name"] for r in derived_relations(pack)}
    kinds, signs, relief, relief_from, flows, matrices, reports, icons, images = {}, {}, None, None, {}, {}, {}, {}, {}
    home, home_from, timelines, nests = None, None, {}, {}
    house_style, house_style_from = None, None
    sources = [(p.dir / "channels.yaml", renames[name], name) for name, p in packs.items()]
    sources += [(path, {}, pack.meta["name"])]
    placed = {}  # binding id -> its span; a later table's binding wins, as its sign does
    for source, names, owner in sources:
        if not source.exists():
            continue
        data = strict_yaml.read(source) or {}
        where = "channels.yaml" if source == path else f"{source.parent.name}/channels.yaml"
        found, file = spans.marks(source), spans.where(owner, pack.meta["name"], "channels.yaml")
        for section in ("relief", "home", "house_style"):
            if section in data:
                placed.setdefault(section, spans.first(found, file, (section,)))  # one per pack: the first
        for section, key in (("kinds", "kind"), ("arrows", "arrow"), ("flows", "id"), ("matrices", "id"),
                             ("timelines", "id"), ("nests", "id"), ("reports", "id"), ("images", "kind")):
            for i, raw in enumerate(data.get(section) or []):
                if isinstance(raw, dict) and key in raw:
                    target = renamed(str(raw[key]), names) if key != "id" else str(raw[key])
                    placed[f"{section}/{target}"] = spans.first(found, file, (section, i))
        for section in sorted(set(data) - {"kinds", "arrows", "relief", "flows", "matrices", "timelines", "nests", "reports", "images", "home",
                                           "house_style"}):
            errors.append(f"{where}: unknown section '{section}' (colour roles and statuses belong to std-view; "
                          "a pack gives its own colour values only in house_style)")
        # One house style per pack, from its own table or one import's, as a home: a second is refused.
        if "house_style" in data and house_style_from:
            errors.append(f"{where}: a second house style; {house_style_from} declares one already (a pack has one house style)")
        elif "house_style" in data:
            house_style, house_style_from = house_style_binding(data["house_style"], view, where, errors), where
        if "relief" in data and relief_from:
            errors.append(f"{where}: a second relief binding; {relief_from} binds one already (a pack binds one relief)")
        elif "relief" in data:
            relief, relief_from = relief_binding(pack, data["relief"], names, where, errors), where
        # One home per pack, from its own table or one import's, as a relief: a second is refused.
        if "home" in data and home_from:
            errors.append(f"{where}: a second home; {home_from} declares one already (a pack has one home)")
        elif "home" in data:
            home, home_from = (data["home"], names), where
        for raw in data.get("flows") or []:
            flow = flow_binding(pack, raw, names, where, errors)
            if flow and flow["id"] in flows:
                errors.append(f"{where}: a second flow '{flow['id']}' (a flow's id names its sheet)")
            elif flow:
                flows[flow["id"]] = flow
        for raw in data.get("matrices") or []:
            matrix = matrix_binding(pack, raw, names, where, errors)
            if matrix and matrix["id"] in matrices:
                errors.append(f"{where}: a second matrix '{matrix['id']}' (a matrix's id names its sheet)")
            elif matrix:
                matrices[matrix["id"]] = matrix
        for section, form, check, found in (("timelines", "timeline", timeline_binding, timelines), ("nests", "nest", nest_binding, nests)):
            for raw in data.get(section) or []:
                sheet = check(pack, raw, names, where, errors)
                if sheet and sheet["id"] in found:
                    errors.append(f"{where}: a second {form} '{sheet['id']}' (a {form}'s id names its sheet)")
                elif sheet:
                    found[sheet["id"]] = sheet
        for raw in data.get("reports") or []:
            report = report_binding(pack, raw, names, where, errors)
            if report and report["id"] in reports:
                errors.append(f"{where}: a second report '{report['id']}' (a report's id names its sheet)")
            elif report:
                reports[report["id"]] = report
        for name, items, key in (("kind", data.get("kinds") or [], "kind"), ("arrow", data.get("arrows") or [], "arrow")):
            seen = [str(e.get(key)) for e in items]
            errors += [f"{where}: {name} '{x}' has two signs" for x in sorted({x for x in seen if seen.count(x) > 1})]
        for binding in image_bindings(pack, data.get("images") or [], names, where, errors):
            if binding["kind"] in images:
                errors.append(f"{where}: kind '{binding['kind']}' has a second image binding (one per kind)")
            images[binding["kind"]] = binding
        listed = icon_files.sources(source.parent, where, errors) if any("icon" in e for e in data.get("kinds") or []) else {}
        for e in data.get("kinds") or []:
            e = dict(e, kind=renamed(str(e.get("kind")), names)) if "kind" in e else e
            if set(e) - {"icon"} != {"kind", "shape"} or e["kind"] not in pack.kinds or e["shape"] not in shapes:
                errors.append(f"{where}: kind sign {e} needs a known kind and a shape from {sorted(shapes)}, and may name an icon")
            if "icon" in e:
                # The bundle names an icon by its hash: two packs may each have an icons/server.svg.
                found = icon_files.icon(source.parent, str(e["icon"]), listed, where, errors)
                e = dict(e, icon=found["sha256"]) if found else {k: v for k, v in e.items() if k != "icon"}
                if found:
                    icons[found["sha256"]] = found
            kinds[str(e.get("kind"))] = e
        for e in data.get("arrows") or []:
            e = dict(e, arrow=renamed(str(e.get("arrow")), names)) if "arrow" in e else e
            if set(e) != {"arrow", "dash"} or e["arrow"] not in arrows or not isinstance(e["dash"], str):
                errors.append(f"{where}: arrow sign {e} needs a known arrow and a dash")
            signs[str(e.get("arrow"))] = e
    # Report references resolve after all source/import channel tables have been collected.
    for report in reports.values():
        for part in report["parts"]:
            if "matrix" in part and part["matrix"]["sheet"] not in matrices:
                errors.append(f"channels.yaml: report {report['id']}: '{part['matrix']['sheet']}' is not a Matrix binding")
    # The home names sheets and relations, so it resolves after every table is read.
    home = home_binding(pack, home[0], flows, home[1], home_from, errors) if home is not None else None
    pack.warnings += [f"channels.yaml: no shape for kind '{k}'" for k in pack.kinds if k not in kinds]
    return {"kinds": [kinds[k] for k in sorted(kinds)], "arrows": [signs[a] for a in sorted(signs)]} | (
        {"relief": relief} if relief else {}) | ({"flows": [flows[f] for f in sorted(flows)]} if flows else {}) | (
        {"matrices": [matrices[m] for m in sorted(matrices)]} if matrices else {}) | (
        {"timelines": [timelines[t] for t in sorted(timelines)]} if timelines else {}) | (
        {"nests": [nests[n] for n in sorted(nests)]} if nests else {}) | (
        {"reports": [reports[r] for r in sorted(reports)]} if reports else {}) | (
        {"icons": [icons[i] for i in sorted(icons)]} if icons else {}) | (
        {"images": [images[k] for k in sorted(images)]} if images else {}) | ({"home": home} if home else {}) | (
        {"house_style": house_style} if house_style else {}) | (
        {"sources": [{"id": b, "span": spans.doc(placed[b])} for b in sorted(placed)]} if placed else {})


def house_style_binding(raw, view: SchemaView, where: str, errors: list[str]) -> dict | None:
    """The pack's house style (`HouseStyle` in contracts/view.yaml): its own values for colour roles of std-view,
    per display theme. Which themes and roles a house style may set, and what a value is, stand in the contract
    and are read there: nothing visual is decided here, and the compiler reads no std-view. It gives values
    only, so the legend is the same in every house style. Refused: a theme or a role twice, and a role with the
    value of the paper of its theme (what is drawn on the paper in the paper's colour cannot be seen; that is
    not taste). In the bundle the palettes stand in the contract's order of themes, the roles sorted by name."""
    where = f"{where}: house_style"
    themes = list(view.get_enum("HouseStyleTheme").permissible_values)
    token = view.get_class("HouseStyleColor").attributes
    role_of, value_of = re.compile(token["role"].pattern), re.compile(token["value"].pattern)
    palettes = raw.get("palettes") if isinstance(raw, dict) and set(raw) == {"palettes"} else None
    if not isinstance(palettes, list) or not palettes:
        errors.append(f"{where}: a house style is a list of palettes, one per display theme")
        return None
    found, before = {}, len(errors)
    for palette in palettes:
        theme = palette.get("theme") if isinstance(palette, dict) and set(palette) == {"theme", "tokens"} else None
        if not isinstance(theme, str) or theme not in themes or theme in found:
            errors.append(f"{where}: a palette is {{theme, tokens}}, its theme one of {', '.join(themes)}, each theme once")
            continue
        tokens, values = palette["tokens"], {}
        for t in tokens if isinstance(tokens, list) and tokens else [None]:
            role, value = (t.get("role"), t.get("value")) if isinstance(t, dict) and set(t) == {"role", "value"} else (None, None)
            if not isinstance(role, str) or not role_of.fullmatch(role) or role in values:
                errors.append(f"{where}: {theme}: a token is {{role, value}}, its role one the contract lets a house style set "
                              f"({token['role'].pattern}), each role once")
            elif not isinstance(value, str) or not value_of.fullmatch(value):
                errors.append(f"{where}: {theme}: the value of '{role}' is not a hex colour (#rrggbb)")
            else:
                values[role] = value
        paper = values.get("paper", "").lower()
        errors += [f"{where}: {theme}: '{r}' has the value of the paper, so it cannot be seen on it"
                   for r, v in sorted(values.items()) if r != "paper" and v.lower() == paper]
        found[theme] = [{"role": r, "value": values[r]} for r in sorted(values)]
    if len(errors) > before:
        return None
    return {"palettes": [{"theme": t, "tokens": found[t]} for t in themes if t in found]}


def home_binding(pack: Pack, raw, flows: dict, names: dict, where: str, errors: list[str]) -> dict | None:
    """The pack home's binding (`HomeSheet` in contracts/view.yaml): a hero, a claim, or both. `hero` names exactly
    one sheet of the pack by its form and id; today the form is a Flow. `claim` lists derived relations, each once
    and each with exactly one rule: a row of such a relation reads as one sentence, the message of its rule
    (`claim_messages`)."""
    where = f"{where}: home"
    if not isinstance(raw, dict) or not raw or set(raw) - {"hero", "claim"}:
        errors.append(f"{where}: a home declares a hero, a claim or both")
        return None
    out = {}
    if "hero" in raw:
        hero = raw["hero"]
        if not isinstance(hero, dict) or set(hero) != {"flow"} or not isinstance(hero["flow"], str) or hero["flow"] not in flows:
            errors.append(f"{where}: hero is one Flow of the pack by its id ({{flow: <id>}})")
            return None
        out["hero"] = {"flow": hero["flow"]}
    if "claim" in raw:
        claim = raw["claim"]
        if not isinstance(claim, list) or not claim or len({str(c) for c in claim}) != len(claim):
            errors.append(f"{where}: claim is a list of derived relations, each once")
            return None
        claim = [renamed(str(c), names) for c in claim]
        derived = {r["name"] for r in derived_relations(pack)}
        heads = [r["head"]["relation"] for r in (pack.rules or {}).get("rules", [])]
        wrong = [c for c in claim if c not in derived or heads.count(c) != 1]
        if wrong:
            errors += [f"{where}: claim '{c}' is not a derived relation with exactly one rule" for c in wrong]
            return None
        out["claim"] = claim
    return out


def claim_messages(pack: Pack) -> list[str]:
    """The messages a home's claim needs, in every language the pack carries: the sentence of the one rule of each
    claim relation."""
    claim = ((pack.channels or {}).get("home") or {}).get("claim") or []
    return [f"rule.{r['id']}" for c in claim for r in (pack.rules or {}).get("rules", []) if r["head"]["relation"] == c]


def image_bindings(pack: Pack, raw, names: dict, where: str, errors: list[str]) -> list[dict]:
    """Image bindings (`ImageBinding` in contracts/view.yaml): per kind one single-valued text slot
    that the kind has, own or inherited, by element id. The binding makes the slot an image; what it means is
    the pack's. Whether each cell names a listed file is checked at publication (`rezono:assets`), as it is data."""
    out = []
    for b in raw if isinstance(raw, list) else [raw]:
        if not isinstance(b, dict) or set(b) != {"kind", "slot"}:
            errors.append(f"{where}: image binding {b} needs exactly kind and slot")
            continue
        kind = renamed(str(b["kind"]), names)
        head, _, name = renamed(str(b["slot"]), names).partition(".")
        s = pack.kinds[head].slots.get(name) if head in pack.kinds else None
        if kind not in pack.kinds or s is None or pack.slot(kind, name) is not s:
            errors.append(f"{where}: image binding {b}: '{b['slot']}' is not a slot of kind '{b['kind']}'")
        elif s.arrow or s.enum or s.multivalued or s.sql_type != "VARCHAR":
            errors.append(f"{where}: image binding {b}: '{b['slot']}' is not a single-valued text attribute")
        else:
            out.append({"kind": kind, "slot": s.element})
    return out


def derived_relations(pack: Pack) -> list[dict]:
    """The derived relations of the pack's rules, each with its columns (`key`: name and type)."""
    return [r for r in (pack.rules or {}).get("relations", []) if r.get("role") == "derived"]


def binding_slot(pack: Pack, element, kind: str, what: str, names: dict, where: str, errors: list[str]):
    """A slot of `kind` (declared there or on a supertype), by its element id under this pack's names."""
    head, _, name = renamed(str(element), names).partition(".")
    s = pack.kinds[head].slots.get(name) if head in pack.kinds else None
    if s is None or pack.slot(kind, name) is not s:
        errors.append(f"{where}: {what} '{element}' is not a slot of {kind}")
        return None
    return s


def edge_source(pack: Pack, e, what: str, names: dict, where: str, errors: list[str], start, end) -> dict | None:
    """One edge source (`EdgeSource` in contracts/view.yaml) from a kind that `start` accepts to one that `end` accepts:
    an arrow, a link kind with an arrow to each end, or a derived relation with two text columns and the kinds of
    each. With `quantity`, an integer column of its relation or attribute of its link kind."""
    relations = {r["name"]: r for r in derived_relations(pack)}
    slot = lambda element, kind, what: binding_slot(pack, element, kind, what, names, where, errors)
    shape = set(e) - {"quantity"} if isinstance(e, dict) else set()
    out_e = None
    if shape == {"arrow"}:
        a = next((s for k in pack.kinds.values() for s in k.slots.values() if s.arrow and s.element == renamed(str(e["arrow"]), names)), None)
        if a is None or not start(a.kind) or not end(a.range):
            errors.append(f"{where}: {what} arrow '{e['arrow']}' is not an arrow between node kinds")
        else:
            out_e = {"arrow": a.element}
    elif shape == {"via", "from", "to"}:
        via = renamed(str(e["via"]), names)
        ends = [slot(e[x], via, x) if via in pack.kinds else None for x in ("from", "to")]
        key = pack.ends(via) if via in pack.kinds else []
        if not all(ends) or not all(s in key for s in ends) or not start(ends[0].range) or not end(ends[1].range) or ends[0] is ends[1]:
            errors.append(f"{where}: {what} via '{via}' needs a link kind whose key holds from and to, each an arrow to a node kind")
        else:
            out_e = {"via": via, "from": ends[0].element, "to": ends[1].element}
    elif shape == {"relation", "from", "to", "from_kinds", "to_kinds"}:
        r = relations.get(str(e["relation"]))
        columns = {c["name"]: c["type"] for c in (r or {}).get("key", [])}
        ends = [[renamed(str(k), names) for k in (e[x] if isinstance(e[x], list) else [])] for x in ("from_kinds", "to_kinds")]
        if r is None:
            errors.append(f"{where}: {what} relation '{e['relation']}' is not a derived relation of the rules")
        elif any(columns.get(e[x]) != "string" for x in ("from", "to")):
            errors.append(f"{where}: {what} relation '{e['relation']}' has no text columns '{e['from']}' and '{e['to']}'")
        elif not all(ends) or not all(start(k) for k in ends[0]) or not all(end(k) for k in ends[1]):
            errors.append(f"{where}: {what} relation '{e['relation']}' needs from_kinds and to_kinds that are node kinds or their subkinds")
        else:
            out_e = {"relation": r["name"], "from": e["from"], "to": e["to"], "from_kinds": ends[0], "to_kinds": ends[1]}
    else:
        errors.append(f"{where}: {what} is an arrow, a via with from and to, or a relation with from, to, from_kinds and to_kinds")
    if out_e is None or "quantity" not in e:
        return out_e
    q = e["quantity"]
    keys = {"channel", "slot", "level", "meaning_message", "scale"}
    scale = q.get("scale") if isinstance(q, dict) else None
    whole = isinstance(scale, dict) and all(type(scale.get(k)) is int for k in ("zero", "exponent_numerator", "exponent_denominator"))
    if not isinstance(q, dict) or set(q) != keys or q["channel"] != "size" or q["level"] != "quantitative" or not whole \
            or scale["exponent_numerator"] < 1 or scale["exponent_denominator"] < 1 or not scale.get("unit_message") \
            or set(scale) != {"zero", "exponent_numerator", "exponent_denominator", "unit_message"}:
        errors.append(f"{where}: {what} quantity is a size binding at level quantitative with {sorted(keys)} and a whole scale")
        return None
    if "relation" in out_e:
        columns = {c["name"]: c["type"] for c in relations[out_e["relation"]].get("key", [])}
        if columns.get(q["slot"]) != "integer":
            errors.append(f"{where}: {what} quantity '{q['slot']}' is not an integer column of {out_e['relation']}")
            return None
        return dict(out_e, quantity=dict(q))
    if "via" in out_e:
        attr = slot(q["slot"], out_e["via"], "quantity")
        if attr and (attr.arrow or attr.multivalued or attr.sql_type != "BIGINT"):
            errors.append(f"{where}: {what} quantity '{q['slot']}' is not an integer attribute of {out_e['via']}")
            return None
        return dict(out_e, quantity=dict(q, slot=attr.element)) if attr else None
    errors.append(f"{where}: {what} quantity needs a relation or a link kind: an arrow row has no quantity")
    return None


def order_slot(pack: Pack, kind: str) -> Slot | None:
    """The slot that orders the elements of a kind: the one with the order role (`slot_uri: schema:position`, S26),
    declared or inherited. Until every pack carries the role, the kind's own whole-number attribute `lane_order`
    stands for it, as the viewer reads it (viewer/src/lib/layout/nodes.ts, `orderSlot`)."""
    role = pack.slot_roles(kind).get("order")
    if role:
        return role
    s = pack.kinds[kind].slots.get(LEGACY_ORDER)
    return s if s and not (s.arrow or s.enum or s.multivalued) and s.sql_type == "BIGINT" else None


def ordered_lane(pack: Pack, s: Slot, what: str, where: str, errors: list[str]) -> None:
    """Enum lanes follow the declared value order. An arrow takes its order from the target kind."""
    if not s.enum and order_slot(pack, s.range) is None:
        errors.append(f"{where}: {what} is bound as ordered, but {s.range} has no order: give it a whole-number slot "
                      "with slot_uri schema:position, or bind the lane at level nominal")


def flow_binding(pack: Pack, raw, names: dict, where: str, errors: list[str]) -> dict | None:
    """A Flow binding (`FlowSheet` in contracts/view.yaml), checked against the schema and the rules. Node kinds are
    kinds, each once; a node's `label` is a text attribute of it and its `lane` a lane binding on a single-valued enum
    attribute or arrow of it, which at level `ordered` needs a declared order (`ordered_lane`). Every edge source
    names its lines once: an arrow between node kinds, a link kind with an arrow to each end, or a derived relation
    with two text columns and the node kinds of each. A line's end is a node kind or a subkind of one, so it has a
    lane. A link kind's ends are those of its key (`Pack.ends`). A node's `group` is a single-valued arrow of it to a
    kind that is no node kind: the target is the box the node stands in. An edge's `quantity` is a size binding on an
    integer column of its relation or attribute of its link kind; `routes` is a relation edge source listed by its
    start (its first column)."""
    keys = {"id", "title_message", "nodes", "edges", "direction", "routes"}
    if not isinstance(raw, dict) or not {"id", "title_message", "nodes", "edges"} <= set(raw) or set(raw) - keys:
        errors.append(f"{where}: a flow needs id, title_message, nodes and edges, and may have direction and routes")
        return None
    where = f"{where}: flow {raw['id']}"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", str(raw["id"])) or raw.get("direction", "right") not in ("down", "right"):
        errors.append(f"{where}: an id is lower case (a-z, 0-9, _) and a direction is down or right")
        return None
    if not isinstance(raw["nodes"], list) or not raw["nodes"] or not isinstance(raw["edges"], list) or not raw["edges"]:
        errors.append(f"{where}: nodes and edges are non-empty lists")
        return None
    out, nodes = dict(raw, nodes=[], edges=[]), []

    slot = lambda element, kind, what: binding_slot(pack, element, kind, what, names, where, errors)

    for n in raw["nodes"]:
        if not isinstance(n, dict) or "kind" not in n or set(n) - {"kind", "label", "lane", "group"}:
            errors.append(f"{where}: a node is a kind, with an optional label, lane and group")
            continue
        kind = renamed(str(n["kind"]), names)
        if kind not in pack.kinds or kind in nodes:
            errors.append(f"{where}: node '{kind}' is not a kind, or is there twice")
            continue
        nodes.append(kind)
        node = dict(n, kind=kind)
        if "label" in n:
            label = slot(n["label"], kind, "label")
            if label and (label.arrow or label.enum or label.multivalued or label.sql_type != "VARCHAR"):
                errors.append(f"{where}: label '{n['label']}' is not a text attribute of {kind}")
            if label:
                node["label"] = label.element
        if "group" in n:
            g = slot(n["group"], kind, "group")
            if g and (not g.arrow or g.multivalued):
                errors.append(f"{where}: group '{n['group']}' is not a single-valued arrow of {kind}")
            elif g:
                node["group"] = g.element
        if "lane" in n:
            lane = n["lane"]
            if not isinstance(lane, dict) or set(lane) != {"channel", "slot", "level", "meaning_message"} or lane["channel"] != "lane" \
                    or lane["level"] not in ("nominal", "ordered"):
                errors.append(f"{where}: lane of {kind} is a lane binding (channel, slot, level nominal or ordered, meaning_message)")
                continue
            s = slot(lane["slot"], kind, "lane")
            if s and (s.multivalued or not (s.arrow or s.enum)):
                errors.append(f"{where}: lane '{lane['slot']}' is not a single-valued enum attribute or arrow of {kind}")
            elif s and lane["level"] == "ordered":
                ordered_lane(pack, s, f"lane '{lane['slot']}' of {kind}", where, errors)
            if s:
                node["lane"] = dict(lane, slot=s.element)
        out["nodes"].append(node)

    def drawn(kind: str) -> bool:
        """A node kind, or a subkind of one."""
        while kind:
            if kind in nodes:
                return True
            kind = pack.kinds[kind].parent if kind in pack.kinds else None
        return False

    # A group is a box, never a node: its kind is no node kind, nor a subkind or supertype of one.
    for node in out["nodes"]:
        if "group" in node:
            target = next(s.range for k in pack.kinds.values() for s in k.slots.values() if s.element == node["group"])
            if any(drawn(k) for k in pack.kinds if target in pack.ancestors(k)) or drawn(target):
                errors.append(f"{where}: group '{node['group']}' of {node['kind']} points to a node kind")

    relations = {r["name"]: r for r in derived_relations(pack)}
    source = lambda e, what: edge_source(pack, e, what, names, where, errors, drawn, drawn)

    for e in raw["edges"]:
        made = source(e, "edge")
        if made:
            out["edges"].append(made)
    # Routes: rows of a derived relation between nodes, listed by their start, so `from` is its first column.
    if "routes" in raw:
        r = raw["routes"]
        made = source(r, "routes") if isinstance(r, dict) and "quantity" not in r else None
        first = (relations.get(made["relation"], {}).get("key") or [{}])[0].get("name") if made and "relation" in made else None
        if made is None or first != made["from"]:
            errors.append(f"{where}: routes is a relation whose first column is its from, with from_kinds and to_kinds")
            return None
        out["routes"] = made
    return out if len(out["nodes"]) == len(raw["nodes"]) and len(out["edges"]) == len(raw["edges"]) else None


def matrix_binding(pack: Pack, raw, names: dict, where: str, errors: list[str]) -> dict | None:
    """A Matrix binding (`MatrixSheet` in contracts/view.yaml), checked against the schema and the rules: `rows` and
    `columns` each a kind (the same kind is allowed), and `cells` one edge source from the row kind (or a subkind) to
    the column kind (or a subkind), in that direction. `columns` may have a `lane`: a lane binding on a single-valued
    enum attribute of its kind, which makes the Matrix a Board with one column per value (docs/gui.md, Board)."""
    if not isinstance(raw, dict) or set(raw) != {"id", "title_message", "rows", "columns", "cells"}:
        errors.append(f"{where}: a matrix needs id, title_message, rows, columns and cells")
        return None
    where = f"{where}: matrix {raw['id']}"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", str(raw["id"])):
        errors.append(f"{where}: an id is lower case (a-z, 0-9, _)")
        return None
    axes, lane = {}, None
    for axis in ("rows", "columns"):
        a = raw[axis]
        kind = renamed(str(a.get("kind")), names) if isinstance(a, dict) else None
        if not isinstance(a, dict) or set(a) - {"kind", "lane"} or kind not in pack.kinds or (axis == "rows" and "lane" in a):
            errors.append(f"{where}: {axis} is a kind" + (", with an optional lane" if axis == "columns" else ""))
            return None
        axes[axis] = kind
        if "lane" in a:
            lane = a["lane"]
            if not isinstance(lane, dict) or set(lane) != {"channel", "slot", "level", "meaning_message"} or lane["channel"] != "lane"                     or lane["level"] not in ("nominal", "ordered"):
                errors.append(f"{where}: lane of {axis} is a lane binding (channel, slot, level nominal or ordered, meaning_message)")
                return None
            s = binding_slot(pack, lane["slot"], kind, "lane", names, where, errors)
            if s is None:
                return None
            if s.multivalued or not s.enum:
                errors.append(f"{where}: lane '{lane['slot']}' is not a single-valued enum attribute of {kind}")
                return None
            lane = dict(lane, slot=s.element)

    def under(kind: str):
        return lambda k: k in pack.kinds and kind in pack.ancestors(k)

    if isinstance(raw["cells"], dict) and "quantity" in raw["cells"]:
        errors.append(f"{where}: cells have no quantity")
        return None
    cells = edge_source(pack, raw["cells"], "cells", names, where, errors, under(axes["rows"]), under(axes["columns"]))
    if cells is None:
        return None
    return {"id": raw["id"], "title_message": raw["title_message"], "rows": {"kind": axes["rows"]},
            "columns": {"kind": axes["columns"]} | ({"lane": lane} if lane else {}), "cells": cells}


ID = r"[a-z][a-z0-9_]*"  # the id of a sheet binding: it names the sheet in its address


def tone_binding(raw, what: str, where: str, errors: list[str]) -> bool:
    """True if `raw` is a tone binding at level ordered (`ChannelBinding`): what a pack's rules conclude, as a
    tone. What its slot names is the caller's to check."""
    ok = isinstance(raw, dict) and set(raw) == {"channel", "slot", "level", "meaning_message"} and raw["channel"] == "tone" \
        and raw["level"] == "ordered" and isinstance(raw["meaning_message"], str)
    if not ok:
        errors.append(f"{where}: {what} is a tone binding (channel tone, slot, level ordered, meaning_message)")
    return ok


def timeline_binding(pack: Pack, raw, names: dict, where: str, errors: list[str]) -> dict | None:
    """A Timeline binding (`TimelineSheet` in contracts/view.yaml), checked against the schema: `rows` is a kind;
    `start`, `end`, `extension` and every mark are single-valued date attributes of it, each named once; `label` is
    a text attribute of it; an extension has its message and only an extension has one; `judgement` is a tone
    binding at level ordered on a single-valued attribute of it. Slots are element ids (`<kind>.<slot>`, the kind
    that declares it), as in every binding. That its messages exist in every language of the pack is checked with
    the languages (`sheet_messages`)."""
    need = {"id", "title_message", "rows", "start", "end", "main_message"}
    if not isinstance(raw, dict) or not need <= set(raw) or set(raw) - need - {"label", "extension", "extension_message", "judgement", "marks"}:
        errors.append(f"{where}: a timeline needs id, title_message, rows, start, end and main_message, and may have "
                      "label, extension with extension_message, judgement and marks")
        return None
    where = f"{where}: timeline {raw['id']}"
    if not re.fullmatch(ID, str(raw["id"])):
        errors.append(f"{where}: an id is lower case (a-z, 0-9, _)")
        return None
    kind, before = renamed(str(raw["rows"]), names), len(errors)
    if kind not in pack.kinds:
        errors.append(f"{where}: rows '{raw['rows']}' is not a kind")
        return None
    messages = [m for m in ("title_message", "main_message", "extension_message") if m in raw]
    if not all(isinstance(raw[m], str) and raw[m] for m in messages) or ("extension" in raw) != ("extension_message" in raw):
        errors.append(f"{where}: a message is a message id, and an extension has an extension_message (only an extension has one)")
    marks = raw.get("marks", [])
    if not isinstance(marks, list) or not all(isinstance(m, dict) and set(m) == {"slot"} for m in marks):
        errors.append(f"{where}: marks is a list, each a slot")
        return None
    out, dates = {"id": raw["id"], "title_message": raw["title_message"], "rows": kind}, []

    def date(element, what: str) -> str | None:
        s = binding_slot(pack, element, kind, what, names, where, errors)
        if s and (s.arrow or s.enum or s.multivalued or s.sql_type != "DATE"):
            errors.append(f"{where}: {what} '{element}' is not a single-valued date attribute of {kind}")
        elif s and s.element in dates:
            errors.append(f"{where}: {what} '{element}' is bound twice: start, end, extension and each mark are different dates")
        dates.append(s.element if s else None)
        return dates[-1]

    if "label" in raw:
        label = binding_slot(pack, raw["label"], kind, "label", names, where, errors)
        if label and (label.arrow or label.enum or label.multivalued or label.sql_type != "VARCHAR"):
            errors.append(f"{where}: label '{raw['label']}' is not a text attribute of {kind}")
        out["label"] = label.element if label else None
    out |= {x: date(raw[x], x) for x in ("start", "end", "extension") if x in raw}
    out |= {m: raw[m] for m in ("main_message", "extension_message") if m in raw}
    if "judgement" in raw and tone_binding(raw["judgement"], "judgement", where, errors):
        s = binding_slot(pack, raw["judgement"]["slot"], kind, "judgement", names, where, errors)
        if s and (s.arrow or s.multivalued):
            errors.append(f"{where}: judgement '{raw['judgement']['slot']}' is not a single-valued attribute of {kind}")
        out["judgement"] = dict(raw["judgement"], slot=s.element if s else None)
    if marks:
        out["marks"] = [{"slot": date(m["slot"], "mark")} for m in marks]
    return out if len(errors) == before else None


def nest_binding(pack: Pack, raw, names: dict, where: str, errors: list[str]) -> dict | None:
    """A Nest binding (`NestSheet` in contracts/view.yaml), checked against the schema and the rules. Its levels run
    from the outside in, two at least, each a kind and each kind once. Every level but the first has `part_of`, a
    single-valued arrow of its kind to the kind of the level before it, so the parts form a tree; the first has
    none. Every level but the last has a `flow` (row or column), how it lays out its parts; the last has no parts
    and so no flow. A level's `label` is a text attribute of its kind. A perspective has an id, once, and a name;
    over a `relation` (a derived relation of the rules) it names the text column of the `part`, a `state` that
    binds a tone at level ordered to another column of it, and may name the text column of the `origin`; without
    a relation it has none of these. Slots are element ids (`<kind>.<slot>`); that the messages exist in every
    language is checked with the languages (`sheet_messages`)."""
    need = {"id", "title_message", "part_message", "levels"}
    if not isinstance(raw, dict) or not need <= set(raw) or set(raw) - need - {"perspectives"}:
        errors.append(f"{where}: a nest needs id, title_message, part_message and levels, and may have perspectives")
        return None
    where = f"{where}: nest {raw['id']}"
    if not re.fullmatch(ID, str(raw["id"])):
        errors.append(f"{where}: an id is lower case (a-z, 0-9, _)")
        return None
    levels, views, before = raw["levels"], raw.get("perspectives", []), len(errors)
    if not all(isinstance(raw[m], str) and raw[m] for m in ("title_message", "part_message")):
        errors.append(f"{where}: title_message and part_message are message ids")
    if not isinstance(levels, list) or len(levels) < 2 or not isinstance(views, list):
        errors.append(f"{where}: levels is a list of two levels at least, from the outside in, and perspectives a list")
        return None
    out, kinds = {"id": raw["id"], "title_message": raw["title_message"], "part_message": raw["part_message"], "levels": []}, []
    for i, level in enumerate(levels):
        if not isinstance(level, dict) or "kind" not in level or set(level) - {"kind", "part_of", "label", "flow", "order_message"}:
            errors.append(f"{where}: a level is a kind, with part_of, flow and an optional label and order_message")
            return None
        kind = renamed(str(level["kind"]), names)
        if kind not in pack.kinds or kind in kinds:
            errors.append(f"{where}: level '{level['kind']}' is not a kind, or is there twice")
            return None
        made = dict(level, kind=kind)
        if ("part_of" in level) != (i > 0):
            errors.append(f"{where}: level {kind}: every level but the first has part_of, and the first has none")
        elif i > 0:
            arrow = binding_slot(pack, level["part_of"], kind, "part_of", names, where, errors)
            if arrow and (not arrow.arrow or arrow.multivalued or arrow.range != kinds[-1]):
                errors.append(f"{where}: part_of '{level['part_of']}' is not a single-valued arrow of {kind} to {kinds[-1]}, "
                              "the kind of the level before it")
            made["part_of"] = arrow.element if arrow else None
        if ("flow" in level) != (i < len(levels) - 1) or level.get("flow", "row") not in ("row", "column"):
            errors.append(f"{where}: level {kind}: every level but the last has a flow, row or column, and the last has none")
        if "label" in level:
            label = binding_slot(pack, level["label"], kind, "label", names, where, errors)
            if label and (label.arrow or label.enum or label.multivalued or label.sql_type != "VARCHAR"):
                errors.append(f"{where}: label '{level['label']}' is not a text attribute of {kind}")
            made["label"] = label.element if label else None
        if not isinstance(level.get("order_message", ""), str):
            errors.append(f"{where}: level {kind}: order_message is a message id")
        kinds.append(kind)
        out["levels"].append(made)
    relations, seen = {r["name"]: r for r in derived_relations(pack)}, []
    for p in views:
        over = {"relation", "part", "state"}
        if not isinstance(p, dict) or not {"id", "label_message"} <= set(p) or set(p) - {"id", "label_message", "origin"} - over \
                or not re.fullmatch(ID, str(p["id"])) or p["id"] in seen or not isinstance(p["label_message"], str) \
                or ("relation" not in p and set(p) & (over | {"origin"})) or ("relation" in p and not over <= set(p)):
            errors.append(f"{where}: a perspective has an id (lower case, once) and a label_message; over a relation it "
                          "names part and state and may name origin, and without one it has none of them")
            continue
        seen.append(p["id"])
        if "relation" in p and tone_binding(p["state"], f"state of perspective {p['id']}", where, errors):
            columns = {c["name"]: c["type"] for c in relations.get(str(p["relation"]), {}).get("key", [])}
            ends = [p[x] for x in ("part", "origin") if x in p]
            if str(p["relation"]) not in relations:
                errors.append(f"{where}: perspective {p['id']}: '{p['relation']}' is not a derived relation of the rules")
            elif any(columns.get(c) != "string" for c in ends) or len(set(ends)) != len(ends):
                errors.append(f"{where}: perspective {p['id']}: part and origin are different text columns of {p['relation']}")
            elif p["state"]["slot"] not in columns or p["state"]["slot"] in ends:
                errors.append(f"{where}: perspective {p['id']}: state '{p['state']['slot']}' is not another column of {p['relation']}")
        out.setdefault("perspectives", []).append(dict(p))
    return out if len(errors) == before else None


def sheet_messages(pack: Pack) -> dict[str, str]:
    """The messages a Timeline or a Nest shows, each with the binding that names it first. A sheet is read in every
    language the pack carries, so each is needed in every one of them."""
    out: dict[str, str] = {}
    table = pack.channels or {}
    for t in table.get("timelines") or []:
        for m in (t["title_message"], t["main_message"], t.get("extension_message"), (t.get("judgement") or {}).get("meaning_message")):
            out.setdefault(m, f"timeline '{t['id']}'")
    for n in table.get("nests") or []:
        asked = [n["title_message"], n["part_message"]] + [level.get("order_message") for level in n["levels"]]
        asked += [m for p in n.get("perspectives") or [] for m in (p["label_message"], (p.get("state") or {}).get("meaning_message"))]
        for m in asked:
            out.setdefault(m, f"nest '{n['id']}'")
    out.pop(None, None)
    return out


def report_binding(pack: Pack, raw, names: dict, where: str, errors: list[str]) -> dict | None:
    """A Report binding (`ReportSheet` in contracts/view.yaml): an id, a title and an ordered list of
    parts: cards of page-template fields, a paged series of existing Waterfalls for an amount slot, a Matrix, or a
    comparison of a derived relation in three classes (`comparison_part`).
    Slots use element ids; their declaring kind uses the same role-filtered page as Cards, never bound instance ids."""
    if not isinstance(raw, dict) or set(raw) != {"id", "title_message", "parts"}:
        errors.append(f"{where}: a report needs id, title_message and parts")
        return None
    where = f"{where}: report {raw['id']}"
    if not re.fullmatch(r"[a-z][a-z0-9_]*", str(raw["id"])):
        errors.append(f"{where}: an id is lower case (a-z, 0-9, _)")
        return None
    if not isinstance(raw["parts"], list) or not raw["parts"]:
        errors.append(f"{where}: parts is a list of one or more parts")
        return None
    parts = []
    for n, part in enumerate(raw["parts"], 1):
        if isinstance(part, dict) and set(part) == {"matrix"}:
            m = part["matrix"]
            if (not isinstance(m, dict) or set(m) != {"sheet"} or not isinstance(m["sheet"], str)
                    or not re.fullmatch(r"[a-z][a-z0-9_]*", m["sheet"])):
                errors.append(f"{where}: part {n}: a matrix needs only a sheet binding id")
                return None
            parts.append({"matrix": {"sheet": m["sheet"]}})
            continue
        if isinstance(part, dict) and set(part) == {"waterfall"}:
            w = part["waterfall"]
            if not isinstance(w, dict) or set(w) != {"slot"}:
                errors.append(f"{where}: part {n}: a waterfall needs only an amount slot, no instance ids or selector")
                return None
            slot = renamed(str(w["slot"]), names)
            attribute = next((s for k in pack.kinds.values() for s in k.slots.values() if s.element == slot), None)
            if attribute is None or not attribute.currency:
                errors.append(f"{where}: part {n}: '{slot}' is not an amount attribute")
                return None
            parts.append({"waterfall": {"slot": slot}})
            continue
        if isinstance(part, dict) and set(part) == {"comparison"}:
            c = comparison_part(pack, part["comparison"], f"{where}: part {n}", errors)
            if c is None:
                return None
            parts.append({"comparison": c})
            continue
        cards = part.get("cards") if isinstance(part, dict) and set(part) == {"cards"} else None
        if not isinstance(cards, dict) or set(cards) != {"kind", "fields"}:
            errors.append(f"{where}: part {n} is cards with a kind and fields, a waterfall with an amount slot, a matrix"
                          " or a comparison")
            return None
        kind = renamed(str(cards["kind"]), names)
        if kind not in pack.kinds:
            errors.append(f"{where}: part {n}: '{kind}' is not a kind")
            return None
        fields = [renamed(str(f), names) for f in cards["fields"]] if isinstance(cards["fields"], list) else []
        template = {s.element for s in pack.all_slots(kind)}
        wrong = [f for f in fields if f not in template]
        if not fields or wrong or len(set(fields)) != len(fields):
            errors.append(f"{where}: part {n}: fields are one or more slots of {kind}'s page, none twice"
                          + (f" ({', '.join(wrong)} is not)" if wrong else ""))
            return None
        parts.append({"cards": {"kind": kind, "fields": fields}})
    return {"id": raw["id"], "title_message": raw["title_message"], "parts": parts}


COMPARISON_CLASSES = ("equal", "different", "not_compared")


def comparison_part(pack: Pack, raw, where: str, errors: list[str]) -> dict | None:
    """A Report part `comparison` (`ComparisonPart` in contracts/view.yaml): a derived relation, the column that
    holds its verdict, and the verdicts per class. Every verdict a rule of the relation can give must stand in exactly
    one class: a rule whose head writes a verdict no class names, or a variable there, stops the pack (unknown is
    explicit; the viewer never guesses a class)."""
    if not isinstance(raw, dict) or not {"relation", "verdict"} <= set(raw) or set(raw) - {"relation", "verdict", *COMPARISON_CLASSES}:
        errors.append(f"{where}: a comparison needs relation and verdict, and may have {', '.join(COMPARISON_CLASSES)}")
        return None
    relation = next((r for r in derived_relations(pack) if r["name"] == raw["relation"]), None)
    if relation is None:
        errors.append(f"{where}: '{raw['relation']}' is not a derived relation")
        return None
    columns = [c["name"] for c in relation["key"]]
    if raw["verdict"] not in columns:
        errors.append(f"{where}: '{raw['verdict']}' is not a column of {raw['relation']} ({', '.join(columns)})")
        return None
    classes = {c: raw.get(c) or [] for c in COMPARISON_CLASSES}
    if any(not isinstance(v, list) or not all(isinstance(x, str) for x in v) for v in classes.values()):
        errors.append(f"{where}: a class is a list of verdicts")
        return None
    classed = [v for c in COMPARISON_CLASSES for v in classes[c]]
    twice = sorted({v for v in classed if classed.count(v) > 1})
    if not classed or twice:
        errors.append(f"{where}: a verdict stands in exactly one class" + (f" ({', '.join(twice)} does not)" if twice else ""))
        return None
    at = columns.index(raw["verdict"])
    for rule in (pack.rules or {}).get("rules", []):
        if rule["head"]["relation"] != raw["relation"]:
            continue
        term = str(rule["head"]["terms"][at])
        if term.startswith("?"):
            errors.append(f"{where}: rule {rule['id']} gives its verdict from a variable, so no class can be checked")
        elif term not in classed:
            errors.append(f"{where}: rule {rule['id']} gives the verdict '{term}', which no class names")
    return {"relation": raw["relation"], "verdict": raw["verdict"], **{c: list(v) for c, v in classes.items() if v}}


def relief_binding(pack: Pack, raw, names: dict, where: str, errors: list[str]) -> dict | None:
    """A relief binding (`ReliefSheet` in contracts/view.yaml), checked against the schema: `region` a kind,
    `member` an arrow to it, `label` a text attribute of it, `height` (optional) an elevation binding on
    one of its integer attributes with an exact scale. Slots are element ids (`<kind>.<slot>`, the kind
    that declares it), as in the arrow signs. Which levels a channel can carry is std-view's; the viewer
    checks that against the key on load."""
    where = f"{where}: relief"
    if not isinstance(raw, dict) or not {"region", "member"} <= set(raw) or set(raw) - {"region", "member", "label", "height"}:
        errors.append(f"{where} needs region and member, and may have label and height")
        return None
    region = renamed(str(raw["region"]), names)
    out = dict(raw, region=region)
    if region not in pack.kinds:
        errors.append(f"{where}: region '{region}' is not a kind")
        return None

    def slot(element: str, kind: str | None, what: str):
        """The slot an element id names, declared by its kind; with `kind`, one that kind has (own or inherited)."""
        head, _, name = renamed(element, names).partition(".")
        s = pack.kinds[head].slots.get(name) if head in pack.kinds else None
        if s is None or (kind is not None and pack.slot(kind, name) is not s):
            errors.append(f"{where}: {what} '{element}' is not a slot of {kind or 'a kind'}")
            return None
        return s

    member = slot(str(out["member"]), None, "member")
    if member and not (member.arrow and not member.multivalued and member.range == region):
        errors.append(f"{where}: member '{out['member']}' is not a single-valued arrow to {region}")
    if member:
        out["member"] = member.element
    if "label" in out:
        label = slot(str(out["label"]), region, "label")
        if label and (label.arrow or label.enum or label.multivalued or label.sql_type != "VARCHAR"):
            errors.append(f"{where}: label '{out['label']}' is not a text attribute of {region}")
        if label:
            out["label"] = label.element
    if "height" in out:
        h = out["height"]
        keys = {"channel", "slot", "level", "meaning_message", "scale"}
        scale = h.get("scale") if isinstance(h, dict) else None
        if not isinstance(h, dict) or set(h) != keys or h["channel"] != "elevation" or h["level"] != "quantitative":
            errors.append(f"{where}: height is an elevation binding at level quantitative with {sorted(keys)}")
            return None
        whole = isinstance(scale, dict) and all(type(scale.get(k)) is int for k in ("zero", "exponent_numerator", "exponent_denominator"))
        if not whole or scale["exponent_numerator"] < 1 or scale["exponent_denominator"] < 1 or not scale.get("unit_message") \
                or set(scale) != {"zero", "exponent_numerator", "exponent_denominator", "unit_message"}:
            errors.append(f"{where}: a height's scale is whole numbers (exponents from 1) with a unit_message")
        attr = slot(str(h["slot"]), region, "height")
        if attr and (attr.arrow or attr.multivalued or attr.sql_type != "BIGINT"):
            errors.append(f"{where}: height '{h['slot']}' is not an integer attribute of {region}")
        if attr:
            out["height"] = dict(h, slot=attr.element)
    return out


def entries(body: str) -> list[tuple[str, str]]:
    """The entries of an MF2 resource body, each with its text up to the next entry or comment at the start of
    a line (continuation lines are indented): [(id, text)]."""
    out, cur = [], None
    for line in body.splitlines(keepends=True):
        m = ENTRY.match(line)
        if m or (line[:1] not in (" ", "\t", "\n", "") and cur is not None):
            if cur:
                out.append(cur)
            cur = [m.group(1), line] if m else None
        elif cur is not None:
            cur[1] += line
    if cur:
        out.append(cur)
    return [(mid, text if text.endswith("\n") else text + "\n") for mid, text in out]


def variables(block: str) -> set[str]:
    """The variables an MF2 entry names. A companion `<x>_gender` is left out: the viewer fills it for every
    variable `x`, and only a language with genders reads it."""
    return {v for v in VARIABLE.findall(block) if not v.endswith("_gender")}


def questions(pack: Pack, pack_dir: Path, packs: dict, errors: list[str]) -> list[dict]:
    """The explanation questions (docs/gui.md "Questions as data"): those of the imported packs
    first, a dependency before the pack that imports it, then the pack's own `questions.yaml`, each in file
    order. Every name a question uses must exist in this pack; a term is used once in the whole closure."""
    sources = [(p.dir / "questions.yaml", f"{name}/questions.yaml") for name, p in packs.items()]
    own = pack_dir / "questions.yaml"
    sources.append((own, "questions.yaml"))
    kinds = set(pack.kinds)
    derived = {r["name"] for r in (pack.rules or {}).get("relations", []) if r["role"] == "derived"}
    relations = set(rules_dl.base_tables(pack)) | derived
    rules = {r["id"] for r in (pack.rules or {}).get("rules", [])}
    names = {"kinds": kinds, "relations": relations, "rules": rules, "layers": set(LAYERS)}
    sweeps_ = {s["name"] for s in pack.sweeps}
    out, terms, readers = [], set(), []
    sections = ("questions", "reader", "acceptance")
    for path, where in sources:
        if not path.exists():
            continue
        doc = strict_yaml.read(path)
        if not isinstance(doc, dict) or doc.get("format") != "rezono.questions/1" \
                or not {"format"} < set(doc) <= {"format", *sections} \
                or not all(isinstance(doc.get(k, []), list) for k in sections):
            errors.append(f"{where}: must be a mapping with format rezono.questions/1 and questions or reader "
                          "or acceptance, each a list")
            continue
        acceptance = acceptance_questions(doc.get("acceptance", []), where, errors)
        if path == own:
            pack.acceptance_questions = acceptance
        readers += [(r, f"{where}: reader question {n}") for n, r in enumerate(doc.get("reader", []))]
        for n, q in enumerate(doc.get("questions", [])):
            q = question(q, f"{where}: question {n}", names, sweeps_, errors)
            if q is None:
                continue
            if q["term"] in terms:
                errors.append(f"{where}: term {q['term']} is used twice in the import closure")
                continue
            terms.add(q["term"])
            out.append(q)
    if pack.rules and not out:
        pack.warnings.append("rules without explanation questions: import std-explain (docs/gui.md)")
    ids: set[str] = set()
    for raw, where in readers:
        r = reader_question(pack, raw, where, out, errors)
        if r is None:
            continue
        if r["id"] in ids:
            errors.append(f"{where}: id {r['id']} is used twice in the import closure")
            continue
        ids.add(r["id"])
        pack.reader_questions.append(r)
    return out


READER_ID = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")  # kebab case: the reader question's address
TEST_POINTER = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*/)*[A-Za-z0-9_][A-Za-z0-9_.-]*\.py::test_[A-Za-z0-9_]+")
MESSAGE_ID = re.compile(r"^[a-z][a-z0-9_.]*$")  # a message id, as messages/<lang>.mf2 writes one (ENTRY)
READINGS = ("days", "yyyymmdd")  # a whole number read as a day (contracts/pack.yaml, ViewColumn.reading)


def acceptance_questions(entries: list, where: str, errors: list[str]) -> list[AcceptanceQuestion]:
    """Validate the pack's source-only test inventory without opening the test paths."""
    result: list[AcceptanceQuestion] = []
    ids: set[str] = set()
    for index, raw in enumerate(entries):
        at = f"{where}: acceptance question {index}"
        if not isinstance(raw, dict) or set(raw) != {"id", "question", "tests"}:
            errors.append(f"{at}: needs exactly id, question and tests")
            continue
        id_, question, tests = raw["id"], raw["question"], raw["tests"]
        if not isinstance(id_, str) or not READER_ID.fullmatch(id_):
            errors.append(f"{at}: id must be kebab case")
            continue
        at = f"{where}: acceptance question {id_}"
        before = len(errors)
        if id_ in ids:
            errors.append(f"{at}: id {id_} is used twice in this pack")
        ids.add(id_)
        if not isinstance(question, str) or not question.strip():
            errors.append(f"{at}: question must be nonblank text")
        if not isinstance(tests, list) or not tests:
            errors.append(f"{at}: tests needs at least one test pointer")
        elif any(not isinstance(test, str) or not TEST_POINTER.fullmatch(test) for test in tests):
            errors.append(f"{at}: tests must use a relative Python test pointer path.py::test_name")
        if len(errors) == before:
            result.append({"id": id_, "question": question, "tests": tests})
    return result


def reader_question(pack: Pack, raw, where: str, asked: list[dict], errors: list[str]) -> dict | None:
    """One reader question (docs/gui.md "Reader questions"), checked: a derived relation of the pack and
    columns of it, each with a message; `element` a kind, on a text column only; `reading` (days or yyyymmdd) on a
    whole-number column only; a context as a kind with fields of its page, as a Cards part; and the proof a
    question with a present start that the relation's rows offer, by default the first in bundle order. The
    question as the bundle carries it, with its proof resolved, or None."""
    keys = {"id", "title_message", "about_message", "relation", "columns", "context", "proof"}
    if not isinstance(raw, dict) or not keys - {"context", "proof"} <= set(raw) <= keys:
        errors.append(f"{where}: needs id, title_message, about_message, relation and columns, and at most context"
                      " and proof")
        return None
    if not isinstance(raw["id"], str) or not READER_ID.match(raw["id"]):
        errors.append(f"{where}: id {raw['id']!r} must be kebab case")
        return None
    where = f"{where.rsplit(': ', 1)[0]}: reader question {raw['id']}"
    bad = len(errors)
    for k in ("title_message", "about_message"):
        if not isinstance(raw[k], str) or not MESSAGE_ID.match(raw[k]):
            errors.append(f"{where}: {k} is a message id")
    derived = {r["name"]: r for r in (pack.rules or {}).get("relations", []) if r["role"] == "derived"}
    relation = raw["relation"]
    if relation not in derived:
        errors.append(f"{where}: '{relation}' is not a derived relation of this pack")
        return None
    types_ = {c["name"]: c["type"] for c in derived[relation]["key"]}
    # The currency of each column, as the bundle gives it (emit.rule_bundle): an amount is read as money, not a day.
    money = {c["name"]: amount for c, amount in zip(derived[relation]["key"],
                                                      amounts.columns(pack.rules or {}, amounts.tables(pack))[relation])}
    columns = []
    if not isinstance(raw["columns"], list) or not raw["columns"]:
        errors.append(f"{where}: columns is a list of at least one column")
    for i, c in enumerate(raw["columns"] if isinstance(raw["columns"], list) else []):
        at = f"{where}: column {i}"
        if not isinstance(c, dict) or not {"column", "message"} <= set(c) <= {"column", "message", "element", "reading"}:
            errors.append(f"{at}: needs column and message, and at most element or reading")
            continue
        if c["column"] not in types_:
            errors.append(f"{at}: '{c['column']}' is not a column of {relation}")
            continue
        if not isinstance(c["message"], str) or not MESSAGE_ID.match(c["message"]):
            errors.append(f"{at}: message is a message id")
        if "element" in c and "reading" in c:
            errors.append(f"{at}: a column is an element or a day, not both")
        if "element" in c and (c["element"] not in pack.kinds or types_[c["column"]] != "string"):
            errors.append(f"{at}: element names a kind, on a text column")
        if "reading" in c and (c["reading"] not in READINGS or types_[c["column"]] != "integer"):
            errors.append(f"{at}: reading is {' or '.join(READINGS)}, on a whole-number column")
        elif "reading" in c and money.get(c["column"]):
            errors.append(f"{at}: column {c['column']} is an amount in {money[c['column']]}; a reading goes on a whole "
                          "number that is no amount")
        columns.append({k: c[k] for k in ("column", "message", "element", "reading") if k in c})
    if len({c["column"] for c in columns}) != len(columns):
        errors.append(f"{where}: a column is shown once")
    context = []
    for i, c in enumerate(raw.get("context") or []):
        at = f"{where}: context {i}"
        if not isinstance(c, dict) or not {"kind", "fields"} <= set(c) <= {"kind", "fields", "readings"} \
                or c["kind"] not in pack.kinds or not isinstance(c["fields"], list) or not c["fields"]:
            errors.append(f"{at}: is a kind with fields, and at most readings")
            continue
        slots = {s.element: s for s in pack.all_slots(c["kind"])}
        wrong = [f for f in c["fields"] if f not in slots]
        if wrong or len(set(c["fields"])) != len(c["fields"]):
            errors.append(f"{at}: fields are slots of {c['kind']}'s page, none twice"
                          + (f" ({', '.join(map(str, wrong))} is not)" if wrong else ""))
            continue
        readings = c.get("readings") or {}
        if not isinstance(readings, dict) or any(f not in c["fields"] or v not in READINGS
                                                 or slots[f].sql_type != "BIGINT" for f, v in readings.items()):
            errors.append(f"{at}: readings map a whole-number field to {' or '.join(READINGS)}")
            continue
        context.append({"kind": c["kind"], "fields": [{"field": f} | ({"reading": readings[f]} if f in readings else {})
                                                      for f in c["fields"]]})
    if raw.get("context") is not None and not isinstance(raw["context"], list):
        errors.append(f"{where}: context is a list")
    # The questions a row of a derived relation offers: a present start, applying to a conclusion of it
    # (viewer/src/lib/answer.ts, questionsFor).
    offered = [q["term"] for q in asked if q["start"] == "present" and applies_to_conclusion(q, relation)]
    proof = raw.get("proof", offered[0] if offered else None)
    if proof is None or proof not in offered:
        errors.append(f"{where}: " + (f"proof '{proof}' is not a question its rows offer" if "proof" in raw
                                      else f"no question offers a proof of a row of {relation}"))
    if len(errors) != bad:
        return None
    return {"id": raw["id"], "title_message": raw["title_message"], "about_message": raw["about_message"],
            "relation": relation, "proof": proof, "columns": columns} | ({"context": context} if context else {})


def applies_to_conclusion(q: dict, relation: str) -> bool:
    """Whether a question applies to a row of a derived relation: as `applies` in viewer/src/lib/answer.ts."""
    a = q.get("applies_to") or {}
    if a.get("derivation", "conclusion") != "conclusion":
        return False
    if a.get("relations") and relation not in a["relations"]:
        return False
    return not a.get("kinds") or any(relation == k or relation.startswith(f"{k}__") for k in a["kinds"])


def question(q, where: str, names: dict, sweeps_: set, errors: list[str]) -> dict | None:
    """One question, checked: only names that exist, a depth as a whole number or `all`, `through: rules`
    only back and from an absent start, and the steps composed as the start and answer allow (suppose). The
    question as the bundle carries it, or None."""
    keys = {"term", "start", "applies_to", "steps", "answer", "limit"}
    if not isinstance(q, dict) or not {"term", "start", "steps", "answer", "limit"} <= set(q) <= keys:
        errors.append(f"{where}: needs term, start, steps, answer and limit, and at most applies_to")
        return None
    term = q["term"]
    if not isinstance(term, str) or not NAME.match(term):
        errors.append(f"{where}: term {term!r} must be lower snake case")
        return None
    where = f"{where.rsplit(': ', 1)[0]}: {term}"
    bad = len(errors)
    if q["start"] not in QUESTION_STARTS:
        errors.append(f"{where}: start is one of {', '.join(QUESTION_STARTS)}")
    if q["answer"] not in ANSWERS:
        errors.append(f"{where}: answer is one of {', '.join(ANSWERS)}")
    if not whole(q["limit"]) or q["limit"] < 1:
        errors.append(f"{where}: limit is a whole number from 1")
    applies = q.get("applies_to", {})
    if not isinstance(applies, dict) or set(applies) - {"derivation", "kinds", "relations"} \
            or applies.get("derivation", "conclusion") not in ("fact", "conclusion"):
        errors.append(f"{where}: applies_to has derivation (fact or conclusion), kinds and relations")
        applies = {}
    for field_ in ("kinds", "relations"):
        named(applies.get(field_, []), names[field_], f"{where}: applies_to.{field_}", errors)
    steps = q["steps"] if isinstance(q["steps"], list) and q["steps"] else None
    if steps is None:
        errors.append(f"{where}: steps is a list of at least one step")
        steps = []
    for i, step in enumerate(steps):
        at = f"{where}: step {i}"
        if not isinstance(step, dict) or len(step) != 1 or next(iter(step)) not in ("trace", "suppose"):
            errors.append(f"{at}: is one trace or one suppose")
            continue
        if "suppose" in step:
            s = step["suppose"]
            if s not in ("given", "candidates", "without") and not (isinstance(s, dict) and set(s) == {"over"} and s["over"] in sweeps_):
                errors.append(f"{at}: suppose is given, candidates, without or over a sweep of this pack")
            continue
        t = step["trace"]
        if not isinstance(t, dict) or not {"direction", "depth"} <= set(t) <= TRACE_KEYS:
            errors.append(f"{at}: trace needs direction and depth, and at most {', '.join(sorted(TRACE_KEYS - {'direction', 'depth'}))}")
            continue
        if t["direction"] not in ("back", "forward"):
            errors.append(f"{at}: direction is back or forward")
        if t["depth"] != "all" and not (whole(t["depth"]) and t["depth"] >= 1):
            errors.append(f"{at}: depth is a whole number from 1, or all")
        if t.get("through", "proof") not in ("proof", "rules"):
            errors.append(f"{at}: through is proof or rules")
        if t.get("through") == "rules" and (t["direction"] != "back" or q["start"] != "absent" or i != 0):
            errors.append(f"{at}: through rules goes back from an absent start, as the first step")
        if "fanout" in t and (t.get("through") != "rules" or not whole(t["fanout"]) or t["fanout"] < 1):
            errors.append(f"{at}: fanout is a whole number from 1, with through rules")
        for f in ("keep", "stop"):
            given = t.get(f, {})
            if not isinstance(given, dict) or set(given) - set(names):
                errors.append(f"{at}: {f} filters on {', '.join(sorted(names))}")
                continue
            for field_, values in sorted(given.items()):
                named(values, names[field_], f"{at}: {f}.{field_}", errors)
    composed(q, steps, where, errors)
    return bundled(q) if len(errors) == bad else None


def composed(q: dict, steps: list, where: str, errors: list[str]) -> None:
    """How suppose composes with the start and the answer (docs/gui.md, "Questions as data"): `given` is the
    first step, once, exactly from a delta or a sweep; a sweep gives a series and nothing else; `overlay` is
    `given` alone from a delta; `candidates` follows a trace from an absent start; `series` comes from a sweep;
    `without` (the published variant whose only change withdraws the start fact) is the first step, once, from
    a present start."""
    sup = [s.get("suppose") if isinstance(s, dict) else None for s in steps]
    start, answer = q["start"], q["answer"]
    givens = [i for i, s in enumerate(sup) if s == "given"]
    if start in ("delta", "sweep") and givens != [0]:
        errors.append(f"{where}: a question from a {start} begins with suppose: given, once")
    if start not in ("delta", "sweep") and givens:
        errors.append(f"{where}: suppose: given only from a delta or a sweep start")
    if start == "sweep" and (len(steps) != 1 or answer != "series"):
        errors.append(f"{where}: a question from a sweep is suppose: given alone, with the answer series")
    if answer == "series" and start != "sweep" and not any(isinstance(s, dict) for s in sup):
        errors.append(f"{where}: the answer series comes from a sweep (start sweep, or suppose over one)")
    if answer == "overlay" and (start != "delta" or len(steps) != 1):
        errors.append(f"{where}: the answer overlay is suppose: given alone, from a delta")
    if any(s == "candidates" and (i == 0 or start != "absent") for i, s in enumerate(sup)):
        errors.append(f"{where}: suppose: candidates follows a trace from an absent start")
    if "without" in sup and (start != "present" or [i for i, s in enumerate(sup) if s == "without"] != [0]):
        errors.append(f"{where}: suppose: without is the first step, once, from a present start")


def bundled(q: dict) -> dict:
    """A checked question as the bundle carries it (contracts/explain.yaml, Question): a depth as text (a
    whole number or `all`), `suppose` as an object; names sorted."""
    def step(s):
        if "suppose" in s:
            given = s["suppose"]
            return {"suppose": dict(given) if isinstance(given, dict) else {"delta": given}}
        t = dict(s["trace"])
        t["depth"] = str(t["depth"])
        for f in ("keep", "stop"):
            if f in t:
                t[f] = {k: sorted(v) for k, v in sorted(t[f].items())}
        return {"trace": t}

    out = {"term": q["term"], "start": q["start"], "steps": [step(s) for s in q["steps"]], "answer": q["answer"],
           "limit": q["limit"]}
    if q.get("applies_to"):
        out["applies_to"] = {k: sorted(v) if isinstance(v, list) else v for k, v in sorted(q["applies_to"].items())}
    return out


def named(values, known: set, where: str, errors: list[str]) -> None:
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        errors.append(f"{where}: a list of names")
        return
    errors += [f"{where}: '{v}' does not exist in this pack" for v in values if v not in known]


def language(pack: Pack, pack_dir: Path, packs: dict, renames: dict, errors: list[str], *,
             reasons: dict[str, list[tuple[str, str]]] | None = None) -> None:
    """Labels (facts per language) and message resources (MessageFormat 2, carried as text).
    Imported packs' labels come first, a dependency before the pack that imports it, under this pack's names;
    the pack's own labels win."""
    default = pack.meta["default_language"]
    elements = set(pack.elements())
    langs = sorted({p.stem for p in (pack_dir / "labels").glob("*.yaml")} |
                   {p.stem for p in (pack_dir / "messages").glob("*.mf2")})
    if default not in langs:
        errors.append(f"no labels or messages for the default language '{default}'")
    many = {f"{'arrow' if s.arrow else 'attribute'}.many.{'total' if s.required else 'partial'}"
            for kind in pack.kinds.values() for s in kind.slots.values() if s.multivalued}
    claimed = claim_messages(pack)
    sheets = sheet_messages(pack)
    needed = list(MESSAGES) + [m for m in MANY if m in many] + reason_messages(pack.rules) + claimed
    asked = [m for q in pack.questions for m in (f"explain.{q['term']}", f"explain.{q['term']}.question")]
    if asked:
        asked += list(EXPLAIN_MESSAGES)
    carried = {}
    for lang in langs:
        lp, mp = pack_dir / "labels" / f"{lang}.yaml", pack_dir / "messages" / f"{lang}.mf2"
        labels = {}
        sources = [(p.dir / "labels" / f"{lang}.yaml", renames[name]) for name, p in packs.items()] + [(lp, {})]
        for source, names in sources:
            if not source.exists():
                continue
            where = f"labels/{lang}.yaml" if source == lp else f"{source.parents[1].name}/labels/{lang}.yaml"
            for element, value in sorted((strict_yaml.read(source) or {}).items()):
                element = renamed(str(element), names)
                if element not in elements:
                    errors.append(f"{where}: unknown element '{element}'")
                    continue
                fact = {"element": element, "lang": lang, "text": value}
                if isinstance(value, dict):
                    fact.update(text=value.get("text"), gender=value.get("gender"))
                    if set(value) - {"text", "gender"} or not isinstance(fact["text"], str):
                        errors.append(f"{where}: '{element}' needs a text and at most a gender")
                labels[element] = fact
        pack.labels += [labels[e] for e in sorted(labels)]
        pack.warnings += [f"labels/{lang}.yaml: no label for '{e}'" for e in sorted(elements - set(labels))]
        text = mp.read_text("utf-8").replace("\r\n", "\n") if mp.exists() else ""
        head, sep, body = text.partition("\n---\n")
        if text and (not sep or f"@locale {lang}" not in head.splitlines()):
            errors.append(f"messages/{lang}.mf2: a resource starts with '@locale {lang}' and a '---' line")
        extra = reasons.get(pack.meta["name"], []) if reasons and lang == default else []
        if extra and (not text or sep):
            if not sep:
                head, sep = f"@locale {lang}", "\n---\n"
            body = rezono_reason.append_entries(body, extra)
            text = f"{head}{sep}{body}"
        # An imported pack's messages come first, a dependency before the pack that imports it; an entry of
        # the pack itself wins (S14). The pack's own resource stays as written, after them.
        own, imported = set(ENTRY.findall(body)), {}
        for name, p in packs.items():
            source = p.dir / "messages" / f"{lang}.mf2"
            ibody = ""
            if source.exists():
                ihead, isep, ibody = source.read_text("utf-8").replace("\r\n", "\n").partition("\n---\n")
                if not isep or f"@locale {lang}" not in ihead.splitlines():
                    errors.append(f"{name}/messages/{lang}.mf2: a resource starts with '@locale {lang}' and a '---' line")
                    continue
            if reasons and lang == p.meta.get("default_language") and name in reasons:
                ibody = rezono_reason.append_entries(ibody, reasons[name])
            if ibody:
                imported.update({mid: block for mid, block in entries(ibody) if mid not in own})
        ids = own | set(imported)
        for mid in needed:
            if mid not in ids:
                # A claim is shown in every language of the pack: its sentence is never a warning.
                (errors if lang == default or mid in claimed else pack.warnings).append(f"messages/{lang}.mf2: no message '{mid}'")
        errors += [f"messages/{lang}.mf2: no message '{mid}' for a question" for mid in asked if mid not in ids]
        # A reader question is read in every language of the pack: its texts are never a warning.
        errors += [f"messages/{lang}.mf2: no message '{mid}' for reader question {r['id']}"
                   for r in pack.reader_questions
                   for mid in (r["title_message"], r["about_message"], *(c["message"] for c in r["columns"]))
                   if mid not in ids]
        # A Timeline and a Nest are read in every language of the pack: a name of theirs is never a warning.
        errors += [f"messages/{lang}.mf2: no message '{mid}' for {sheet}" for mid, sheet in sorted(sheets.items()) if mid not in ids]
        if imported:
            text = (head if sep else f"@locale {lang}") + "\n---\n" + "".join(imported.values()) + (body if sep else "")
        if text:
            pack.messages[lang] = text
        carried[lang] = (set(labels), {mid: variables(block) for mid, block in [*imported.items(), *entries(body)]})
    # A pack carries a language whole: each language has the labels and the messages of the default
    # language and no others, the imported ones included, and a message names the same variables in each.
    for lang in langs:
        if lang == default or default not in carried:
            continue
        for a, b in ((default, lang), (lang, default)):
            errors += [f"labels/{b}.yaml: no label for '{e}', which language '{a}' has"
                       for e in sorted(carried[a][0] - carried[b][0])]
            errors += [f"messages/{b}.mf2: no message '{m}', which language '{a}' has"
                       for m in sorted(set(carried[a][1]) - set(carried[b][1]))]
        errors += [f"messages/{lang}.mf2: '{m}' names {', '.join(sorted(v)) or 'no variable'}; in language '{default}' "
                   f"it names {', '.join(sorted(carried[default][1][m])) or 'no variable'}"
                   for m, v in sorted(carried[lang][1].items()) if carried[default][1].get(m, v) != v]
