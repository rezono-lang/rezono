"""Modules written in Rezono: the key `rezono` of pack.yaml, and the lowering of a module's declarations to the
schema model (docs/rezono/publication.md §2, §3, §5.1, §5.2).

The compiler uses the language reader in `rezono/` to build a module's JSON form from its authored text
(contracts/rezono-module.yaml). It lowers the resulting kinds, slots and enums to the LinkML schema, so
that every check after this one is the check a schema file gets. A module is a schema module of its pack, named
by its path under `rezono/` without `.rezono`; pack.yaml names it with its form and the layer of its kinds.

A name a module uses resolves against the kinds and enums of its pack, declared by a module or by `schema/`: one
name space. A name declared twice in a pack is refused, as is everything this slice does not lower, at its line
in the module's file. The lowering is a pure function of the form: the same form gives the same schema.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Iterator, Mapping, Set
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import yaml
from . import rezono_alias, rezono_enum, rezono_extend, rezono_key, rezono_kind, rezono_metadata, rezono_slot
from .schemaview import SchemaView
from linkml_runtime.linkml_model import SchemaDefinition
from linkml_runtime.loaders.yaml_loader import YAMLLoader

FORMAT = "rezono.module/1"
IDENTIFIER_FORMAT = "rezono.module/2"
DIR = "rezono"
PACKAGED_READER = Path(__file__).with_name("module_reader") / "src" / "write-form.js"
CHECKOUT_READER = Path(__file__).resolve().parents[2] / DIR / "src" / "write-form.ts"
KEY = "rezono"  # the key of pack.yaml (contract RezonoModule in contracts/pack.yaml)
PAGE = "docs/rezono/publication.md"
DATASET_FORMAT = "rezono.module/2"
PATH = re.compile(r"^rezono/[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*\.(rezono|json)$")
# Declarations this slice does not lower, by the member that names them: what, and where the page says so.
REFUSED = {
    "unit": ("a unit is not lowered yet", "§6"),
    "rounding": ("a rounding is not lowered yet", "§6"),
    "param": ("a parameter is not lowered yet", "§6"),
    "reason": ("a reason declaration is not lowered (no ticket yet)", "§6"),
    "check": ("a check statement is not lowered yet", "§6"),
}


@dataclass(frozen=True)
class Declared:
    """One module as pack.yaml names it."""
    module: str  # rezono/<path>.rezono
    form: str  # rezono/<path>.json
    layer: str

    @property
    def id(self) -> str:
        """The module's name: its path under rezono/ without .rezono."""
        return self.module[len(DIR) + 1:-len(".rezono")]


@dataclass
class Lowered:
    """A module lowered: its LinkML schema, and the modules of its pack whose names it uses."""
    declared: Declared
    schema: dict
    form: dict
    uses: list[str] = field(default_factory=list)  # module ids within the pack, sorted


def declared(meta: dict, pack_dir: Path, errors: list[str], *, reject_undeclared: bool = True,
             include_datasets: bool = False) -> list[Declared]:
    """Check declared paths and layers, then select modules for schema lowering or fact discovery."""
    from .pack import LAYERS  # pack imports modules, which imports this module

    where = f"{pack_dir.name}/pack.yaml: {KEY}"
    entries = meta.get(KEY)
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        errors.append(f"{where}: a list of {{module, form, layer}}")
        return []
    out: list[Declared] = []
    named: set[str] = set()
    for i, entry in enumerate(entries):
        at = f"{where}[{i}]"
        if not isinstance(entry, dict) or set(entry) != {"module", "form", "layer"}:
            errors.append(f"{at}: needs exactly module, form and layer")
            continue
        module, form, layer = (str(entry[k]) for k in ("module", "form", "layer"))
        ok = True
        for what, path, suffix in (("module", module, ".rezono"), ("form", form, ".json")):
            if path in named:
                errors.append(f"{at}: {path} is named twice")
                ok = False
            named.add(path)
            if not PATH.match(path) or not path.endswith(suffix):
                errors.append(f"{at}: {what} is a path under {DIR}/ in lower case that ends in {suffix}, not {path!r}")
                ok = False
            elif not (pack_dir / path).is_file():
                errors.append(f"{at}: {what} {path} is not a file")
                ok = False
        if layer not in LAYERS:
            errors.append(f"{at}: layer must be one of {LAYERS}, not {layer!r}")
            ok = False
        if not ok:
            continue
        if not include_datasets and is_dataset_form(pack_dir / form):
            if meta.get("theory") is True:
                errors.append(f"{pack_dir.name}/{form}: a theory pack cannot contain fact files")
            continue
        out.append(Declared(module, form, layer))
    if reject_undeclared and (pack_dir / DIR).is_dir():
        for p in sorted((pack_dir / DIR).rglob("*")):
            rel = p.relative_to(pack_dir).as_posix()
            if p.is_file() and p.suffix in (".rezono", ".json") and rel not in named:
                errors.append(f"{pack_dir.name}/{rel}: pack.yaml names no module or form at this path ({KEY})")
    return out


def read_form(pack_dir: Path, d: Declared, errors: list[str],
              *, authored_output: Path | None = None) -> dict | None:
    """The form of a module, if it is one: format, module and spans, and nothing else."""
    path = authored_output if authored_output is not None else pack_dir / d.form
    where = f"{pack_dir.name}/{d.module if authored_output is not None else d.form}"
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError) as e:
        errors.append(f"{where}: not a JSON file ({e})")
        return None
    module = module_body(doc, FORMAT) or module_body(doc, IDENTIFIER_FORMAT)
    if module is None:
        errors.append(f"{where}: not the form of a module ({FORMAT} or {IDENTIFIER_FORMAT}, contracts/rezono-module.yaml)")
        return None
    spans = doc["spans"]
    if not valid_places(module, spans) and not (
        "schema" in module and valid_places(module, spans, legacy_metadata=True)
        and authored_output is None and form_only_source(pack_dir / d.module, doc)
    ):
        errors.append(f"{where}: spans must place each module node once, in order, with a positive line and "
                      "nonnegative start and end offsets in ascending order (contracts/rezono-module.yaml)")
        return None
    return doc


def effective_form(pack_dir: Path, d: Declared, errors: list[str]) -> dict | None:
    """Validate the submitted form, then use the authored declarations and their locations."""
    submitted = read_form(pack_dir, d, errors)
    if submitted is None:
        return None
    return source_form(pack_dir, d, submitted, errors, lambda source: legacy_header(source, submitted))


def effective_dataset_form(pack_dir: Path, d: Declared, pack: str, submitted: dict,
                           errors: list[str]) -> dict | None:
    """Read authored dataset tables unless the exact historical form-only declaration is present."""
    module = submitted["module"]
    name = Path(d.module).stem
    matches_legacy = not submitted["spans"] and not any(header_errors(module, pack))
    header = f"rezono 0\npack {pack}\ndataset {name}"
    return source_form(pack_dir, d, submitted, errors,
                       lambda source: matches_legacy and source.replace("\r\n", "\n").removesuffix("\n") == header)


def source_form(pack_dir: Path, d: Declared, submitted: dict, errors: list[str],
                legacy: Callable[[str], bool]) -> dict | None:
    try:
        data = (pack_dir / d.module).read_bytes()
        source = data.decode("utf-8")
    except (OSError, UnicodeError):
        errors.append(f"{pack_dir.name}/{d.module}: cannot read the module as UTF-8")
        return None
    if legacy(source):
        return submitted
    return authored_form(pack_dir, d, data, errors)


def legacy_header(source: str, form: dict) -> bool:
    """Older form-only modules pair a matching source header with placeholder offsets."""
    if any(place["start"] != "0" or place["end"] != "1" for place in form["spans"]):
        return False
    module = form["module"]
    header = [f"rezono {module['rezono']}"] if "rezono" in module else []
    header.append(f"pack {module['pack']}")
    actual = [line for raw in source.splitlines() if (line := raw.partition("--")[0].strip())]
    return actual == header


def authored_form(pack_dir: Path, d: Declared, data: bytes, errors: list[str]) -> dict | None:
    where = f"{pack_dir.name}/{d.module}"
    reader = PACKAGED_READER if PACKAGED_READER.is_file() else CHECKOUT_READER
    if not reader.is_file():
        errors.append(f"{where}: the compiler installation does not include the module reader")
        return None
    hint = "use Node 24" if reader == PACKAGED_READER else "use Node 24 and run npm ci in rezono/"
    node = os.environ.get("REZONO_NODE", "node")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("NODE_")}
    try:
        with TemporaryDirectory(prefix="rezono-module-") as directory:
            source, target = Path(directory) / "source.rezono", Path(directory) / "form.json"
            source.write_bytes(data)
            result = subprocess.run(
                [node, str(reader), source.name, target.name], cwd=directory,
                capture_output=True, encoding="utf-8", env=env,
            )
            if result.returncode == 0:
                return read_form(pack_dir, d, errors, authored_output=target)
    except (OSError, UnicodeError):
        errors.append(f"{where}: cannot run the module reader; {hint}")
        return None
    diagnostics = [f"{where}:{line.split(':', 1)[1]}" for line in result.stderr.splitlines()
                   if line.startswith(f"{source.name}:")]
    errors.extend(diagnostics or [f"{where}: the module reader failed; {hint}"])
    return None


def form_only_source(path: Path, form: dict) -> bool:
    try:
        return legacy_header(path.read_text(encoding="utf-8"), form)
    except (OSError, UnicodeError):
        return False


def place_pointers(value: object, at: str = "", member: str = "", *, legacy_metadata: bool = False) -> Iterator[str]:
    """Canonical pointers in span order. Metadata containers have no place of their own."""
    if isinstance(value, dict):
        excluded = {"unless", "between"} if legacy_metadata else {"unless", "between", "memberMetadata"}
        if (at and member not in excluded) or (not at and "schema" in value and not legacy_metadata):
            yield at
        for key in sorted(value, key=lambda s: s.encode("utf-16-be", "surrogatepass")):
            escaped = key.replace("~", "~0").replace("/", "~1")
            child = value[key]
            pointer = f"{at}/{escaped}"
            if legacy_metadata:
                yield from place_pointers(child, pointer, key, legacy_metadata=True)
            elif member == "memberMetadata":
                if isinstance(child, dict):
                    yield pointer
            elif key not in ("annotations", "prefixes"):
                yield from place_pointers(child, pointer, key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from place_pointers(item, f"{at}/{i}", member, legacy_metadata=legacy_metadata)


def valid_places(module: dict, spans: list, *, legacy_metadata: bool = False) -> bool:
    expected = place_pointers(module, legacy_metadata=legacy_metadata)
    for place in spans:
        if not isinstance(place, dict) or place.keys() != {"at", "line", "start", "end"}:
            return False
        if not isinstance(place["at"], str) or place["at"] != next(expected, None):
            return False
        line, start, end = place["line"], place["start"], place["end"]
        if not all(isinstance(n, str) and re.fullmatch(r"0|[1-9][0-9]*", n) for n in (line, start, end)):
            return False
        if line == "0" or (len(start), start) > (len(end), end):
            return False
    return next(expected, None) is None


def module_body(form: object, expected_format: str) -> dict | None:
    """Check the envelope and header shape before interpreting a module's declarations."""
    if not isinstance(form, dict) or form.keys() != {"format", "module", "spans"}:
        return None
    module = form["module"]
    header = {"rezono", "pack", "use", "decls"}
    if expected_format == IDENTIFIER_FORMAT:
        header |= rezono_metadata.HEADER
    if (form["format"] != expected_format or not isinstance(form["spans"], list)
            or not isinstance(module, dict) or not isinstance(module.get("pack"), str)
            or not isinstance(module.get("use"), list) or not isinstance(module.get("decls"), list)
            or not module.keys() <= header or not rezono_metadata.valid_header(module)):
        return None
    return module


def named_dataset(module: dict) -> dict | None:
    """Recognize the single named declaration handled by the fact loader."""
    declarations = module["decls"]
    if len(declarations) != 1 or not isinstance(declarations[0], dict):
        return None
    dataset = declarations[0]
    if (dataset.keys() == {"dataset", "decls"} and isinstance(dataset["dataset"], str)
            and dataset["dataset"] and isinstance(dataset["decls"], list)):
        return dataset
    return None


def is_dataset_form(path: Path) -> bool:
    """Dispatch only recognized dataset forms; leave other documents to ordinary schema validation."""
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False
    module = module_body(doc, DATASET_FORMAT)
    return module is not None and named_dataset(module) is not None


def header_errors(module: dict, pack: str) -> Iterator[tuple[str, str, str]]:
    """Header refusals shared by schema lowering and dataset admission."""
    if module.get("rezono") != "0":
        yield "rezono", f"the `rezono` line says 0, not {module.get('rezono', 'nothing')}", "§3"
    if module["pack"] != pack:
        yield "pack", f"the `pack` line names {module['pack']}, not this pack, {pack}", "§3"
    for i in range(len(module["use"])):
        yield f"/use/{i}", "a `use` line is not lowered", "§6"



def lines(form: dict) -> dict[str, int]:
    """The line of every node that has a place, by its pointer into `module`."""
    out = {}
    for s in form["spans"]:
        try:
            out[str(s["at"])] = int(s["line"])
        except (TypeError, KeyError, ValueError):
            continue
    return out


def marks(module: Path, form: Path | dict) -> dict[tuple, tuple[int, int]]:
    """The (line, column) of each kind, slot and path equation, by its keys in the lowered schema (MOD2).
    The place is the name as written: the form gives its offset in code points, the text the line it is on."""
    if isinstance(form, Path):
        text = module.read_text(encoding="utf-8")
        doc = json.loads(form.read_bytes())
    else:
        text = module.read_bytes().decode("utf-8")
        doc = form
    start = {s["at"]: s["start"] for s in doc["spans"]}
    limit = str(len(text))
    out: dict[tuple, tuple[int, int]] = {}

    def place(at: str, path: tuple) -> None:
        offset = start.get(at)
        # A structurally valid form can describe a different text. Only map a position in this source.
        if offset is not None and (len(offset), offset) <= (len(limit), limit):
            n = int(offset)
            out[path] = (text.count("\n", 0, n) + 1, n - text.rfind("\n", 0, n))
    for i, decl in enumerate(doc["module"]["decls"]):
        if isinstance(decl, dict) and isinstance(decl.get("kind"), str):
            place(f"/decls/{i}", ("classes", decl["kind"]))
            if isinstance(equations := decl.get("equations"), list):
                for j, _ in enumerate(equations):
                    place(f"/decls/{i}/equations/{j}", ("classes", decl["kind"], "annotations", "path_equations", j))
            for j, s in enumerate(decl.get("slots") or []):
                if isinstance(s, dict) and isinstance(s.get("slot"), str):
                    place(f"/decls/{i}/slots/{j}", ("classes", decl["kind"], "attributes", s["slot"]))
            if isinstance(keys := decl.get("keys"), list):
                for j, key in enumerate(keys):
                    if isinstance(key, dict) and isinstance(key.get("unique"), str):
                        place(f"/decls/{i}/keys/{j}", ("classes", decl["kind"], "unique_keys", key["unique"]))
    return out


def header_line(pack_dir: Path, d: Declared, word: str) -> int:
    """The line of a header line (`rezono`, `pack`). The form gives the module itself no place, so this is the
    first line of the text that starts with that word; nothing more of the text is read."""
    try:
        text = (pack_dir / d.module).read_text(encoding="utf-8")
    except OSError:
        return 1
    for n, line in enumerate(text.splitlines(), 1):
        if line.split("--", 1)[0].split()[:1] == [word]:
            return n
    return 1


def declaration_name(decl: dict) -> str | None:
    name = decl.get("kind", decl.get("enum", decl.get("type") if "base" in decl else None))
    return name if isinstance(name, str) else None


def names(form: dict) -> dict[str, str]:
    """The schema names a form declares and the pointer of each first declaration."""
    out: dict[str, str] = {}
    for i, decl in enumerate(form["module"]["decls"]):
        name = declaration_name(decl) if isinstance(decl, dict) else None
        if name is not None:
            out.setdefault(name, f"/decls/{i}")
    return out


def lower_pack(pack_dir: Path, meta: dict, pack: str, declared_by: Mapping[str, Set[str]],
               errors: list[str], imported: bool = False) -> list[Lowered]:
    """Lower every module of one pack. `pack` is the pack's name, `declared_by` the LinkML names each schema
    module of the pack declares, by module id within the pack, `imported` whether another pack imports it. Every
    refusal names the module's file and line."""
    forms = {d: effective_form(pack_dir, d, errors) for d in declared(meta, pack_dir, errors)}
    owners: dict[str, list[str]] = {}
    for mid, ns in sorted(declared_by.items()):
        for n in ns:
            owners.setdefault(n, []).append(mid)
    for d, form in forms.items():
        if d.id in declared_by:
            errors.append(f"{pack_dir.name}/{d.module}: module '{d.id}' is also a schema module (schema/{d.id}.yaml)")
        for n in names(form) if form else {}:
            owners.setdefault(n, []).append(d.id)
    return [lower(pack_dir, d, form, pack, owners, errors, imported) for d, form in forms.items() if form is not None]


def lower(pack_dir: Path, d: Declared, form: dict, pack: str, owners: dict[str, list[str]],
          errors: list[str], imported: bool = False) -> Lowered:
    """One module's form as the LinkML schema that says the same (§5.1, §5.2), or a refusal at a line. An `extend`
    adds nothing to the schema: its tables are rules, which rezono_table writes once the pack's model is read
    (§9.1)."""
    where, line, module = f"{pack_dir.name}/{d.module}", lines(form), form["module"]
    extended = form["format"] == IDENTIFIER_FORMAT

    def refuse(at: str | int, what: str, section: str = "§6") -> None:
        n = at if isinstance(at, int) else line.get(at) or line.get("/".join(at.split("/")[:3])) or 1
        errors.append(f"{where}:{n}: {what} ({PAGE} {section})")

    for key, message, section in header_errors(module, pack):
        place = key if key.startswith("/") else header_line(pack_dir, d, key)
        refuse(place, message, section)
    own = names(form)
    declared_names = own.keys() | owners.keys()
    uses: set[str] = set()
    enums: dict[str, dict] = {}
    classes: dict[str, dict] = {}
    aliases: dict[str, dict[str, str]] = {}
    for i, decl in enumerate(module["decls"]):
        at = f"/decls/{i}"
        if not isinstance(decl, dict):
            refuse(at, "not a declaration of the form")
            continue
        name = declaration_name(decl)
        if name is not None:
            elsewhere = [o for o in owners.get(name, []) if o != d.id]
            if own[name] != at:
                refuse(at, f"{name} is declared twice in this module", "§3")
                continue
            if elsewhere:
                refuse(at, f"{name} is also declared by module {elsewhere[0]}; a name of the pack is declared once",
                       "§3")
                continue
        if "kind" in decl:
            kind_fields = {}
            if form["format"] == IDENTIFIER_FORMAT and "abstract" in decl:
                abstract = rezono_kind.lower_abstract(decl, at, refuse)
                if abstract is None:
                    continue
                decl, kind_fields = abstract
            keys = {}
            if form["format"] == IDENTIFIER_FORMAT and "keys" in decl:
                decl = decl.copy()
                if (keys := rezono_key.lower(decl.pop("keys"), f"{at}/keys", refuse)) is None:
                    continue
            lowered_kind = rezono_kind.lower(
                decl, at, own, owners, declared_names, uses, refuse,
                extended_format=extended,
            )
            if lowered_kind is not None:
                if keys:
                    lowered_kind["unique_keys"] = keys
                classes[decl["kind"]] = lowered_kind | kind_fields
        elif "enum" in decl:
            lowered_enum = rezono_enum.lower(decl, at, refuse, extended=extended)
            if lowered_enum is not None:
                enums[decl["enum"]] = lowered_enum
        elif "extend" in decl:
            rezono_extend.validate(decl, at, imported, refuse)
        elif "fact" in decl:
            if "columns" in decl:
                refuse(at, "a fact table is not lowered yet", "§5.3")
            else:
                refuse(at, "a fact row is not lowered (no ticket yet)")
        elif "type" in decl and "base" in decl:
            if form["format"] != IDENTIFIER_FORMAT:
                refuse(at, "a scalar alias requires rezono.module/2", "§5.1")
            elif alias := rezono_alias.lower(decl, at, refuse):
                aliases[decl["type"]] = alias
        else:
            refuse(at, *next((REFUSED[k] for k in REFUSED if k in decl), ("not a declaration this compiler reads",)))
    schema = {"id": f"https://rezono.org/rezono/{pack}/{d.id}", "name": d.id.replace("/", "_"),
              "imports": ["linkml:types"], "default_range": "string", "annotations": {"layer": d.layer},
              "enums": enums, "classes": classes}
    if aliases:
        schema["types"] = aliases
    if extended and "schema" in module:
        range_name = module.get("defaultRange", "Text")
        schema = rezono_metadata.header(
            module, schema, d.layer,
            rezono_slot.builtin_range(range_name, range_name in declared_names, extended_form=True), refuse,
        )
    return Lowered(d, schema, form, sorted(uses))


def view(schema: dict, importmap: dict) -> SchemaView:
    """The SchemaView of a lowered module, its imports resolved through `importmap`."""
    loaded = cast(SchemaDefinition, YAMLLoader().load(schema, target_class=SchemaDefinition))
    return SchemaView(loaded, importmap=importmap)


def schema_classes(pack_dir: Path, rel: str) -> dict:
    """The classes of a compilable pack's module, with ranges from the compiler's name resolution."""
    from . import modules  # The schema loader also calls this module's lowering functions.

    meta = yaml.safe_load((pack_dir / "pack.yaml").read_text(encoding="utf-8")) or {}
    loaded, _ = modules.load(pack_dir, meta, [])
    schema = next(m.sv.schema for m in loaded if m.pack_dir == pack_dir and m.rel == rel)
    classes = {}
    for name, cls in schema.classes.items():
        slots = {}
        for slot, attr in cls.attributes.items():
            if attr.identifier:
                slots[slot] = {"identifier": True}
            else:
                slots[slot] = {"range": attr.range}
                if attr.required:
                    slots[slot]["required"] = True
        classes[name] = {"attributes": slots}
    return classes


def class_slot_order(pack_dir: Path, rel: str) -> dict[str, list[str]]:
    """Read a compiled module's class and slot order from its form for the writer."""
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_text(encoding="utf-8")) or {}
    d = next(d for d in declared(meta, pack_dir, []) if d.module == rel)
    form = effective_form(pack_dir, d, []) or {"module": {"decls": []}}
    return {decl["kind"]: ([] if decl.get("embedded") is True else ["id"])
            + [s["slot"] for s in decl.get("slots") or []]
            for decl in form["module"]["decls"] if isinstance(decl, dict) and "kind" in decl}
