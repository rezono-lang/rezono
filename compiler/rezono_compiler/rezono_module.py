"""Modules written in Rezono: the key `rezono` of pack.yaml, and the lowering of a module's declarations to the
schema model (docs/rezono/publication.md §2, §3, §5.1, §5.2).

The compiler does not parse Rezono. It reads the JSON form that `rezono/` writes of a module
(contracts/rezono-module.yaml) and lowers its kinds, slots and enums to the LinkML schema that says the same, so
that every check after this one is the check a schema file gets. A module is a schema module of its pack, named
by its path under `rezono/` without `.rezono`; pack.yaml names it with its form and the layer of its kinds.

A name a module uses resolves against the kinds and enums of its pack, declared by a module or by `schema/`: one
name space. A name declared twice in a pack is refused, as is everything this slice does not lower, at its line
in the module's file. The lowering is a pure function of the form: the same form gives the same schema.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Set
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml
from .schemaview import SchemaView
from linkml_runtime.linkml_model import SchemaDefinition
from linkml_runtime.loaders.yaml_loader import YAMLLoader

FORMAT = "rezono.module/1"
IDENTIFIER_FORMAT = "rezono.module/2"
DIR = "rezono"
KEY = "rezono"  # the key of pack.yaml (contract RezonoModule in contracts/pack.yaml)
PAGE = "docs/rezono/publication.md"
PATH = re.compile(r"^rezono/[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*\.(rezono|json)$")
# The built-in slot types (§5.1) and their LinkML ranges.
TYPES = {"Bool": "boolean", "Date": "date", "Text": "string"}
# Declarations this slice does not lower, by the member that names them: what, and where the page says so.
REFUSED = {
    "unit": ("a unit is not lowered yet", "§6"),
    "rounding": ("a rounding is not lowered yet", "§6"),
    "param": ("a parameter is not lowered yet", "§6"),
    "reason": ("a reason declaration is not lowered (no ticket yet)", "§6"),
    "check": ("a check statement is not lowered yet", "§6"),
}
DERIVED = ("a derived value is not lowered yet", "§5.4")
EXTEND = {"extend", "derived"}
KIND = {"kind", "world", "applies", "sealed", "slots", "derived"}
SLOT = {"slot", "type", "card"}
ENUM = {"enum", "world", "values"}


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
    uses: list[str] = field(default_factory=list)  # module ids within the pack, sorted


def declared(meta: dict, pack_dir: Path, errors: list[str], *, reject_undeclared: bool = True) -> list[Declared]:
    """Check the declared paths and layers. Pack compilation also refuses files absent from the manifest."""
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
        if ok:
            out.append(Declared(module, form, layer))
    if reject_undeclared and (pack_dir / DIR).is_dir():
        for p in sorted((pack_dir / DIR).rglob("*")):
            rel = p.relative_to(pack_dir).as_posix()
            if p.is_file() and p.suffix in (".rezono", ".json") and rel not in named:
                errors.append(f"{pack_dir.name}/{rel}: pack.yaml names no module or form at this path ({KEY})")
    return out


def read_form(pack_dir: Path, d: Declared, errors: list[str]) -> dict | None:
    """The form of a module, if it is one: format, module and spans, and nothing else."""
    where = f"{pack_dir.name}/{d.form}"
    try:
        doc = json.loads((pack_dir / d.form).read_bytes())
    except (OSError, ValueError) as e:
        errors.append(f"{where}: not a JSON file ({e})")
        return None
    module = module_body(doc, FORMAT) or module_body(doc, IDENTIFIER_FORMAT)
    if module is None:
        errors.append(f"{where}: not the form of a module ({FORMAT} or {IDENTIFIER_FORMAT}, contracts/rezono-module.yaml)")
        return None
    if not valid_places(module, doc["spans"]):
        errors.append(f"{where}: spans must place each module node once, in order, with a positive line and "
                      "nonnegative start and end offsets in ascending order (contracts/rezono-module.yaml)")
        return None
    return doc


def place_pointers(value: object, at: str = "", member: str = "") -> Iterator[str]:
    """Canonical pointers in span order. The module, unless clauses and range bodies have no own place."""
    if isinstance(value, dict):
        if at and member not in ("unless", "between"):
            yield at
        for key in sorted(value, key=lambda s: s.encode("utf-16-be", "surrogatepass")):
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from place_pointers(value[key], f"{at}/{escaped}", key)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from place_pointers(item, f"{at}/{i}", member)


def valid_places(module: dict, spans: list) -> bool:
    expected = place_pointers(module)
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
    if (form["format"] != expected_format or not isinstance(form["spans"], list)
            or not isinstance(module, dict) or not isinstance(module.get("pack"), str)
            or not isinstance(module.get("use"), list) or not isinstance(module.get("decls"), list)
            or not module.keys() <= {"rezono", "pack", "use", "decls"}):
        return None
    return module


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


def marks(module: Path, form: Path) -> dict[tuple, tuple[int, int]]:
    """The (line, column) of every kind and slot of a module, by the path of keys its lowered schema holds it at
    (`classes`, the class, then `attributes` and the slot), as `spans.marks` gives them for a schema file (MOD2).
    The place is the name as written: the form gives its offset in code points, the text the line it is on."""
    text = module.read_text(encoding="utf-8")
    doc = json.loads(form.read_bytes())
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
            for j, s in enumerate(decl.get("slots") or []):
                if isinstance(s, dict) and isinstance(s.get("slot"), str):
                    place(f"/decls/{i}/slots/{j}", ("classes", decl["kind"], "attributes", s["slot"]))
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


def names(form: dict) -> dict[str, str]:
    """The kinds and enums a form declares: LinkML name -> the pointer of its first declaration."""
    out: dict[str, str] = {}
    for i, decl in enumerate(form["module"]["decls"]):
        name = decl.get("kind", decl.get("enum")) if isinstance(decl, dict) else None
        if isinstance(name, str):
            out.setdefault(name, f"/decls/{i}")
    return out


def builtin_range(name: str, declared: bool) -> str | None:
    # Bool became a built-in after modules could already declare it as a pack name.
    if name == "Bool" and declared:
        return None
    return TYPES.get(name)


def attributes(decl: dict, declared: Set[str]) -> dict[str, dict]:
    """Lower slots in written order. Only a non-embedded kind gets an implicit identifier (§5.1)."""
    slots = decl.get("slots") or []
    out: dict[str, dict] = {}
    if decl.get("embedded") is not True and not any(s.get("identifier") is True for s in slots):
        out["id"] = {"identifier": True}
    for s in slots:
        name = s["type"]
        slot: dict[str, object] = {"range": builtin_range(name, name in declared) or name}
        if s.get("identifier") is True:
            slot["identifier"] = True
        elif "card" not in s:
            slot["required"] = True
        out[s["slot"]] = slot
    return out


def lower_pack(pack_dir: Path, meta: dict, pack: str, declared_by: Mapping[str, Set[str]],
               errors: list[str], imported: bool = False) -> list[Lowered]:
    """Lower every module of one pack. `pack` is the pack's name, `declared_by` the LinkML names each schema
    module of the pack declares, by module id within the pack, `imported` whether another pack imports it. Every
    refusal names the module's file and line."""
    forms = {d: read_form(pack_dir, d, errors) for d in declared(meta, pack_dir, errors)}
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
    for i, decl in enumerate(module["decls"]):
        at = f"/decls/{i}"
        if not isinstance(decl, dict):
            refuse(at, "not a declaration of the form")
            continue
        name = decl.get("kind", decl.get("enum"))
        if isinstance(name, str):
            elsewhere = [o for o in owners.get(name, []) if o != d.id]
            if own[name] != at:
                refuse(at, f"{name} is declared twice in this module", "§3")
                continue
            if elsewhere:
                refuse(at, f"{name} is also declared by module {elsewhere[0]}; a name of the pack is declared once",
                       "§3")
                continue
        if "kind" in decl:
            if kind(decl, at, own, owners, uses, refuse, explicit_identifiers=form["format"] == IDENTIFIER_FORMAT):
                classes[decl["kind"]] = {"attributes": attributes(decl, declared_names)}
        elif "enum" in decl:
            if set(decl) - ENUM:
                refuse(at, f"an enum with {', '.join(sorted(set(decl) - ENUM))} is not lowered", "§5.2")
            elif decl.get("world") == "open":
                refuse(at, "an open enum (`world open`) is refused", "§5.2")
            elif twice := [k for k, v in enumerate(decl["values"]) if v in decl["values"][:k]]:
                for k in twice:
                    refuse(f"{at}/values/{k}", f"the value {decl['values'][k]} is written twice in enum {decl['enum']}",
                           "§5.2")
            else:
                enums[decl["enum"]] = {"permissible_values": {v: {} for v in decl["values"]}}
        elif "extend" in decl:
            extend(decl, at, imported, refuse)
        elif "fact" in decl:
            if "columns" in decl:
                refuse(at, "a fact table is not lowered yet", "§5.3")
            else:
                refuse(at, "a fact row is not lowered (no ticket yet)")
        else:
            refuse(at, *next((REFUSED[k] for k in REFUSED if k in decl), ("not a declaration this compiler reads",)))
    schema = {"id": f"https://rezono.org/rezono/{pack}/{d.id}", "name": d.id.replace("/", "_"),
              "imports": ["linkml:types"], "default_range": "string", "annotations": {"layer": d.layer},
              "enums": enums, "classes": classes}
    return Lowered(d, schema, sorted(uses))


def kind(decl: dict, at: str, own: dict, owners: dict[str, list[str]], uses: set[str], refuse,
         *, explicit_identifiers: bool = False) -> bool:
    """Check a kind against §5.1; True when it lowers. A slot's type resolves in the module, else in the pack."""
    ok = True
    members = KIND | {"embedded"} if explicit_identifiers else KIND
    if extra := set(decl) - members:
        refuse(at, f"a kind with {', '.join(sorted(extra))} is not lowered", "§5.1")
        ok = False
    embedded = decl.get("embedded") is True
    if explicit_identifiers and "embedded" in decl and not embedded:
        refuse(at, "an embedded kind must be marked true", "§5.1")
        ok = False
    if decl.get("world") != "closed":
        refuse(at, "an open kind is refused: a kind says `world closed`", "§5.1")
        ok = False
    if "applies" in decl:
        refuse(f"{at}/applies", "`applies` is not lowered yet")
        ok = False
    if "sealed" in decl:
        refuse(at, "`sealed at` is not lowered yet")
        ok = False
    for k, _ in enumerate(decl.get("derived") or []):
        refuse(f"{at}/derived/{k}", *DERIVED)
        ok = False
    seen: set[str] = set()
    identifier_seen = False
    allowed = SLOT | {"identifier"} if explicit_identifiers else SLOT
    for j, s in enumerate(decl.get("slots") or []):
        here = f"{at}/slots/{j}"
        extra = sorted(set(s) - allowed) if isinstance(s, dict) else []
        if not isinstance(s, dict) or extra:
            refuse(here, f"a slot with {', '.join(extra)} is not lowered" if extra else "not a slot of the form",
                   "§5.1")
            ok = False
            continue
        if s["slot"] in seen:
            refuse(here, f"the slot {s['slot']} is written twice in kind {decl['kind']}", "§5.1")
            ok = False
        seen.add(s["slot"])
        explicit = s.get("identifier") is True
        if "identifier" in s and not explicit:
            refuse(here, "an explicit identifier must be marked true", "§5.1")
            ok = False
        if explicit:
            if embedded:
                refuse(here, "an embedded kind cannot declare an identifier", "§5.1")
                ok = False
            elif identifier_seen:
                refuse(here, f"kind {decl['kind']} has more than one identifier", "§5.1")
                ok = False
            identifier_seen = True
        if s["slot"] == "id" and not explicit:
            refuse(here, "a slot named `id` is refused: `id` identifies the elements of a kind", "§5.1")
            ok = False
        if s.get("card", "?") != "?":
            refuse(here, f"a slot `{s['type']}{s['card']}` is not lowered (no ticket yet)")
            ok = False
        t, found = s["type"], owners.get(s["type"], [])
        if t in own or builtin_range(t, bool(found)) is not None:
            continue
        if len(found) == 1:
            uses.add(found[0])
            continue
        refuse(here, f"{t} is declared by modules {' and '.join(found)} of this pack" if found else
               f"{t} is not Date, Text, or an enum or a kind of this pack. Built-in Bool is also supported", "§5.1")
        ok = False
    return ok


def extend(decl: dict, at: str, imported: bool, refuse) -> None:
    """Check an `extend` against §9.1: each derived value is a decision table under `unique`. What needs the pack's
    model (the kind, the inputs, the values) rezono_table checks; here what the form alone refuses."""
    if set(decl) - EXTEND:
        refuse(at, f"an extend with {', '.join(sorted(set(decl) - EXTEND))} is not lowered", "§9.1")
        return
    if imported:
        refuse(at, "a decision table in a module of an imported pack is not lowered yet", "§9.1")
        return
    for k, dv in enumerate(decl.get("derived") or []):
        here = f"{at}/derived/{k}"
        t = dv.get("table") if isinstance(dv, dict) else None
        if not isinstance(t, dict):
            refuse(here, *DERIVED)
        elif t.get("table") != "unique":
            refuse(here, f"a table `{t.get('table')}` is not lowered yet", "§9.1")
        elif "totality" in dv:
            refuse(here, "`total` on a table is not lowered: its proof is the check of `rezono/` (tables.md §7, "
                         "point 3)", "§9.1")
        elif "card" in dv:
            refuse(here, f"a derived value `{dv['type']}{dv['card']}` is not lowered yet", "§9.1")


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
    form = read_form(pack_dir, d, []) or {"module": {"decls": []}}
    return {decl["kind"]: ([] if decl.get("embedded") is True else ["id"])
            + [s["slot"] for s in decl.get("slots") or []]
            for decl in form["module"]["decls"] if isinstance(decl, dict) and "kind" in decl}
