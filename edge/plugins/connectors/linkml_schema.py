"""A pack's schema as LinkML, and a LinkML schema as a pack's schema modules (lane M, M02; P10.7).

A pack's schema is already written in LinkML, but in Rezono's form: modules that import each other by Rezono's
names (`lab`, `../shared`, `std-decision:decision`), meaning in annotations only Rezono reads, and types that only
the compiler resolves. This connector maps that form onto plain LinkML and back. The compiler stays the one
reader of the subset ([pack](../../../docs/compiler/pack.md#schemas-the-supported-linkml)): the export starts
from a pack it read and checked, the import ends with the compiler reading what it wrote.

**Out** (`export`): one LinkML schema per module, laid out as `<pack>/<module>.yaml`, and a root schema
`<pack>.yaml` that imports them all. Every import is a path relative to the importing file, so LinkML's own
`SchemaView` reads the whole pack without Rezono: the modules of an imported pack are written beside it, under its
own name. Per module, as LinkML reads it:

- the module's header (id, name, description, language, prefixes, annotations) and its types and enums as
  declared, in their order (an enum's values keep theirs);
- per class, its own slots as `attributes`, induced the way LinkML induces them (a top-level slot or a class's
  `slots:` becomes an attribute) with an explicit `range`; what the class inherits stays with its parent;
- the annotation `layer` on every class, as the compiler resolves it (the class's own, else its module's), and
  `semantic` on every attribute: its type as the schema bundle says it (B10, `contracts/bundle.yaml`
  `SemanticType`), written by the same function.

A module written in Rezono is refused for now: its LinkML is the compiler's lowering, and the import could only
write it back as a LinkML module.

What a reader that knows only LinkML does not get is in `linkml.losses.yaml`: rules, value states, reasons,
proofs, sources, access, labels and the pack's other files are not schema; Rezono's annotations are extensions.

**In** (`import_schema`, `write`): a LinkML schema and the schemas it imports, by relative paths only, each
becoming a module of the pack. A file `<pack>/<path>.yaml` under the root's directory is module `<path>` of
that pack: of the pack being written, or of a pack it imports, which is not written (the pack takes it by its
pin). Any other file is a module of the pack at its own path. Each module is written in the form above, with
Rezono's import names, without `semantic` (the compiler derives it again). What has no meaning in Rezono is refused
with its place, never dropped: a construct the compiler does not read and a module outside the root's directory
or behind a URL. What the import leaves out on purpose is in `linkml.in.losses.yaml`. `write` puts the modules in
a pack's `schema/` and has the compiler read the pack; what it refuses is the import's refusal.

    python edge/plugins/connectors/linkml_schema.py export <pack> <out-dir>   # writes the LinkML schemas
    python edge/plugins/connectors/linkml_schema.py import <root.yaml> <pack> # writes <pack>/schema/
"""

from __future__ import annotations

import dataclasses
import json
import os as os  # The portability test replaces the host path implementation.
import posixpath
import sys
from pathlib import Path, PurePosixPath

import yaml
from rezono_compiler.schemaview import SchemaView
from linkml_runtime.dumpers import json_dumper
from linkml_runtime.linkml_model import meta

from rezono_compiler import modules, pack

STANDARD = "LinkML"
STANDARD_VERSION = "1.12"
TYPES = "linkml:types"

# Documentation that LinkML gives every element: carried as written both ways, read by no rule.
DOCUMENTATION = frozenset(f.name for f in dataclasses.fields(meta.CommonMetadata)) - {
    "in_subset", "from_schema", "imported_from"}
# What a schema reader fills in itself; never written.
INFERRED = frozenset({"@type", "from_schema", "imported_from", "owner", "domain_of", "is_usage_slot",
                      "usage_slot_name", "definition_uri"})
# Per element, the members with a meaning in Rezono: what the compiler reads, and what it refuses with its own
# message (kept, so that the compiler names it). Anything else beside DOCUMENTATION is refused by the import.
SLOT = frozenset({"identifier", "key", "required", "range", "inlined", "inlined_as_list", "multivalued",
                  "minimum_value", "maximum_value", "minimum_cardinality", "maximum_cardinality",
                  "exact_cardinality", "pattern", "equals_string", "equals_number", "slot_uri", "annotations",
                  "equals_expression", "equals_string_in", "any_of", "exactly_one_of", "all_of", "none_of",
                  "array", "ifabsent"})
CLASS = frozenset({"is_a", "abstract", "attributes", "unique_keys", "rules", "represents_relationship",
                   "class_uri", "tree_root", "annotations", "mixins", "slot_usage", "extra_slots"})
ENUM = frozenset({"permissible_values", "enum_uri", "annotations"})
VALUE = frozenset({"meaning", "annotations"})
TYPE = frozenset({"typeof", "base", "uri", "repr", "pattern", "minimum_value", "maximum_value", "annotations"})
# A module's header, in this order, then its documentation; `imports` is rewritten, the rest is written as declared.
HEADER = ("id", "name", "title", "description", "version", "license", "in_language", "prefixes",
          "default_prefix", "default_range")
# The members of a schema, all of them: written (the header, documentation, imports, annotations, elements),
# made attributes of the classes that use them (top-level slots), left out (linkml.in.losses.yaml) or refused.
SCHEMA_WRITTEN = frozenset(HEADER) | DOCUMENTATION | {"imports", "annotations", "types", "enums", "classes"}
SCHEMA_INLINED = frozenset({"slots"})
SCHEMA_DROPPED = frozenset({"subsets", "settings", "emit_prefixes", "default_curi_maps", "metamodel_version",
                            "source_file", "source_file_date", "source_file_size", "generation_date",
                            "slot_names_unique", "id_prefixes", "id_prefixes_are_closed", "definition_uri",
                            "local_names", "conforms_to", "implements", "instantiates", "extensions"})
SCHEMA_REFUSED = frozenset({"bindings"})
# Annotations the export writes and the import does not take over: derived again by the compiler.
DERIVED = ("semantic",)
ROOT_PACKS = "packs"  # the root's annotation: the pin of every imported pack (name, version, sha256)


class LinkMLError(ValueError):
    """The mapping cannot write this correctly; the message names the place and the reason."""


# ---------------------------------------------------------------------------------------------------------------
# The one normal form of a module, shared by both directions


def dump(element, name: str | None = None) -> dict:
    """A LinkML element as plain data, with what a reader infers left out and every keyed member without the key
    it repeats (`name` is the element's own); an annotation as its value, a mapping or a list as `{value: ...}`,
    the form LinkML's metamodel accepts."""
    return _plain(json.loads(json_dumper.dumps(element)), name)


def _plain(value, key=None):
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for k, v in value.items():
        if k in INFERRED or (key is not None and k in ("name", "text", "unique_key_name") and v == key):
            continue
        if k == "annotations":
            out[k] = {t: _annotation(a) for t, a in v.items()}
        elif isinstance(v, dict) and k in ("attributes", "permissible_values", "unique_keys", "slot_conditions",
                                           "slot_usage", "types", "enums", "classes", "slots"):
            out[k] = {n: _plain(d, n) for n, d in v.items()}
        else:
            out[k] = _plain(v)
    return out


def _annotation(a):
    value = a.get("value") if isinstance(a, dict) and "tag" in a else a
    return {"value": value} if isinstance(value, (dict, list)) else value


def ordered(element: dict, cls) -> dict:
    """An element's members in the order of LinkML's metamodel, its annotations last: one order for both
    directions, so that a member added afterwards stands where a reader of the same document would put it."""
    order = {f.name: i for i, f in enumerate(dataclasses.fields(cls)) if f.name != "annotations"}
    return dict(sorted(element.items(), key=lambda kv: order.get(kv[0], len(order))))


def normal(sv: SchemaView) -> tuple[dict, dict, dict]:
    """The types, enums and classes a schema declares, in their order, each class with its own slots as
    attributes (LinkML's induced slots, less what its parent gives) and an explicit range."""
    s = sv.schema
    types = {n: ordered(dump(t, n), meta.TypeDefinition) for n, t in (s.types or {}).items()}
    enums = {n: ordered(dump(e, n), meta.EnumDefinition) for n, e in (s.enums or {}).items()}
    classes = {}
    for cname, c in (s.classes or {}).items():
        out = {k: v for k, v in dump(c, cname).items() if k not in ("attributes", "slots", "slot_usage")}
        inherited = {x.name for x in sv.class_induced_slots(c.is_a)} if c.is_a else set()
        usage = set(c.slot_usage or {})
        if usage & inherited:
            raise LinkMLError(f"class {cname}: slot_usage on {', '.join(sorted(usage & inherited))}, which it "
                              f"inherits; Rezono does not let a subkind change an inherited slot")
        attributes = {}
        for x in sv.class_induced_slots(cname):
            if x.name in inherited:
                continue
            a = dump(x, x.name)
            a["range"] = x.range or s.default_range or "string"
            attributes[x.name] = ordered(a, meta.SlotDefinition)
        if attributes:
            out["attributes"] = attributes
        classes[cname] = ordered(out, meta.ClassDefinition)
    return types, enums, classes


def header(s) -> dict:
    """A schema's header and documentation, as declared."""
    d = dump(s)
    if s.prefixes:
        d["prefixes"] = {p: str(x.prefix_reference) for p, x in s.prefixes.items()}
    if d.get("default_prefix") == f"{s.id}/":
        del d["default_prefix"]  # what LinkML infers when a schema declares none
    rest = ordered({k: v for k, v in d.items() if k in DOCUMENTATION and k not in HEADER}, meta.SchemaDefinition)
    return {f: d[f] for f in HEADER if d.get(f)} | rest


def module_doc(head: dict, imports: list[str], annotations: dict, types: dict, enums: dict, classes: dict) -> dict:
    doc = dict(head)
    doc["imports"] = [TYPES] + imports
    if annotations:
        doc["annotations"] = annotations
    for k, v in (("types", types), ("enums", enums), ("classes", classes)):
        if v:
            doc[k] = v
    return doc


def text(doc: dict) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120)


def relative(src: str, dst: str) -> str:
    """The import that names `dst` from the file `src` (both paths without `.yaml`, relative to one root)."""
    root = PurePosixPath("/")
    return posixpath.relpath(root / dst, (root / src).parent)


# ---------------------------------------------------------------------------------------------------------------
# Out


def doc_path(m: modules.Module) -> str:
    """Where a module is written in the export: `<pack>/<module path>`, without `.yaml`."""
    return f"{m.pack}/{m.id.partition(':')[2] if ':' in m.id else m.id}"


def export(pack_dir: str | Path) -> dict[str, str]:
    """The LinkML schemas of a pack: {relative path: YAML text}. Refuses a pack the compiler refuses."""
    pack_dir = Path(pack_dir)
    model = pack.read(pack_dir)  # raises CompileError: only a checked pack is exported
    meta_ = pack.read_meta(pack_dir)
    errors: list[str] = []
    mods, packs = modules.load(pack_dir, meta_, errors)
    if errors:
        raise LinkMLError("\n".join(errors))
    kinds = {(k.module, k.cls): k for k in model.kinds.values()}
    where = {m.id: doc_path(m) for m in mods}
    out: dict[str, str] = {}
    for m in mods:
        if m.form is not None:
            raise LinkMLError(f"{m.rel}: a module written in Rezono is not exported yet; its LinkML form is the "
                              f"compiler's lowering, which the import could not write back as Rezono")
        types, enums, classes = normal(m.sv)
        for cname, c in classes.items():
            kind = kinds[(m.id, cname)]
            c["annotations"] = (c.get("annotations") or {}) | {"layer": kind.layer}
            for name, a in (c.get("attributes") or {}).items():
                if name in kind.slots:
                    a["annotations"] = (a.get("annotations") or {}) | {
                        "semantic": {"value": kind.slots[name].type.semantic}}
                    c["attributes"][name] = ordered(a, meta.SlotDefinition)
            classes[cname] = ordered(c, meta.ClassDefinition)
        doc = module_doc(header(m.sv.schema), [relative(where[m.id], where[i]) for i in m.imports],
                         dump(m.sv.schema).get("annotations", {}), types, enums, classes)
        out[f"{where[m.id]}.yaml"] = text(doc)
    name = model.meta["name"]
    root = {"id": f"urn:rezono:pack:{name}", "name": name.replace("-", "_"), "version": model.meta["version"],
            "prefixes": {"linkml": "https://w3id.org/linkml/"}, "default_range": "string",
            "imports": [TYPES] + [where[m.id] for m in mods]}
    if packs:
        root["annotations"] = {ROOT_PACKS: {"value": [{"name": p.name, "version": p.version, "sha256": p.sha256}
                                                      for p in packs.values()]}}
    out[f"{name}.yaml"] = text(root)
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------------------------------------------
# In


def _closure(root: Path) -> dict[Path, list[tuple[str, Path | None]]]:
    """Every file the root imports, directly or not, with its imports as written and the file each names
    (None for `linkml:types`). Only relative paths inside the root's directory; nothing is fetched."""
    base = root.parent.resolve()
    found: dict[Path, list[tuple[str, Path | None]]] = {}
    todo = [root.resolve()]
    while todo:
        f = todo.pop()
        if f in found:
            continue
        if not f.is_file():
            raise LinkMLError(f"{f}: an imported schema that does not exist")
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        found[f] = []
        for imp in doc.get("imports") or []:
            imp = str(imp)
            if imp == TYPES:
                found[f].append((imp, None))
                continue
            if ":" in imp:
                raise LinkMLError(f"{f.relative_to(base)}: import '{imp}' is a URL or CURIE; the import reads files "
                                  f"beside the root only, and fetches nothing")
            target = (f.parent / f"{imp}.yaml").resolve()
            if base not in target.parents:
                raise LinkMLError(f"{f.relative_to(base)}: import '{imp}' is outside {base}")
            found[f].append((imp, target))
            todo.append(target)
    return found


def _refuse(kind: str, where: str, element: dict, allowed: frozenset) -> None:
    bad = sorted(set(element) - allowed - DOCUMENTATION)
    if bad:
        raise LinkMLError(f"{kind} {where}: {', '.join(bad)} has no meaning in Rezono yet; refused rather than dropped")


def _check(types: dict, enums: dict, classes: dict, rel: str) -> None:
    for n, t in types.items():
        _refuse("type", f"{rel}#{n}", t, TYPE)
    for n, e in enums.items():
        _refuse("enum", f"{rel}#{n}", e, ENUM)
        for v, pv in (e.get("permissible_values") or {}).items():
            _refuse("value", f"{rel}#{n}.{v}", pv, VALUE)
    for n, c in classes.items():
        _refuse("class", f"{rel}#{n}", c, CLASS)
        for a, s in (c.get("attributes") or {}).items():
            _refuse("slot", f"{rel}#{n}.{a}", s, SLOT)


def _strip(types: dict, enums: dict, classes: dict) -> None:
    """What the import does not take over (linkml.in.losses.yaml): subsets, and the annotations the export
    derives, which the compiler derives again."""
    elements = [*types.values(), *enums.values(), *classes.values()]
    elements += [a for c in classes.values() for a in (c.get("attributes") or {}).values()]
    elements += [v for e in enums.values() for v in (e.get("permissible_values") or {}).values()]
    for e in elements:
        e.pop("in_subset", None)
        for t in DERIVED:
            (e.get("annotations") or {}).pop(t, None)
        if e.get("annotations") == {}:
            del e["annotations"]


def import_schema(root: str | Path, pack_name: str, imported: frozenset[str] = frozenset()) -> dict[str, str]:
    """The modules of pack `pack_name` that the LinkML schema `root` holds: {path under schema/: YAML text}.
    `imported` names the packs it imports: a file `<name>/<path>.yaml` of one of them is that pack's module."""
    root = Path(root)
    base = root.parent.resolve()
    files = _closure(root)

    def module(f: Path) -> tuple[str | None, str]:
        """The pack a file belongs to (None: the one written) and its module path."""
        parts = f.relative_to(base).with_suffix("").parts
        if len(parts) > 1 and parts[0] in (pack_name, *imported):
            return (None if parts[0] == pack_name else parts[0]), "/".join(parts[1:])
        return None, "/".join(parts)

    normals = {}
    for f in files:
        if module(f)[0] is None:
            sv = SchemaView(str(f))
            normals[f] = (sv.schema, *normal(sv))
    written = {f for f, (_, *elements) in normals.items() if any(elements)}

    def names(f: Path, spliced: list[Path], seen: frozenset = frozenset()) -> list[str]:
        """The modules `f` imports, in Rezono's names. A file that declares nothing a module holds (an index, or
        top-level slots that are now attributes) is not written: its own imports stand in its place, and it is
        added to `spliced`."""
        out = []
        for _, target in files[f]:
            if target is None or target in seen:
                continue
            owner, path = module(target)
            if owner is not None:
                out.append(f"{owner}:{path}")
            elif target in written:
                out.append(relative(module(f)[1], path))
            else:
                spliced.append(target)
                out += [n if ":" in n else relative(module(f)[1], str(PurePosixPath(path).parent / n))
                        for n in names(target, spliced, seen | {f})]
        return list(dict.fromkeys(out))

    out: dict[str, str] = {}
    for f in sorted(written):
        s, types, enums, classes = normals[f]
        _strip(types, enums, classes)
        rel = f.relative_to(base).as_posix()
        _refuse("schema", rel, dump(s), SCHEMA_WRITTEN | SCHEMA_INLINED | SCHEMA_DROPPED | INFERRED)
        _check(types, enums, classes, rel)
        spliced: list[Path] = []
        imports = names(f, spliced)
        head = header(s)
        for g in spliced:  # a CURIE of a slot that is now an attribute here keeps its prefix
            head["prefixes"] = header(normals[g][0]).get("prefixes", {}) | head.get("prefixes", {})
        annotations = dump(s).get("annotations", {})
        out[f"{module(f)[1]}.yaml"] = text(module_doc(head, imports, annotations, types, enums, classes))
    return dict(sorted(out.items()))


def write(root: str | Path, pack_dir: str | Path) -> list[str]:
    """Write the modules of `root` into `pack_dir/schema/` (which must not hold a schema yet) and have the compiler
    read the pack. What the compiler refuses is refused here, and nothing the import wrote is left behind."""
    pack_dir = Path(pack_dir)
    target = pack_dir / "schema"
    if target.exists() and any(target.rglob("*.yaml")):
        raise LinkMLError(f"{target}: holds a schema already; the import writes a pack's schema, it merges none")
    meta_ = pack.read_meta(pack_dir)
    errors: list[str] = []
    packs = modules.imported_packs(pack_dir, meta_, errors)
    if errors:
        raise LinkMLError("\n".join(errors))
    files = import_schema(root, meta_["name"], frozenset(packs))
    made: list[Path] = []   # the directories the import creates, so a refusal removes only what it wrote
    for rel, body in files.items():
        path = target / rel
        made += [d for d in (path.parent, *path.parent.parents) if (d == target or target in d.parents) and not d.exists()]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    try:
        pack.read(pack_dir)
    except pack.CompileError as e:
        for rel in files:
            (target / rel).unlink(missing_ok=True)
        for d in sorted(set(made), key=lambda d: len(d.parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
        raise LinkMLError(f"the compiler refuses the imported schema:\n{e}") from e
    return sorted(files)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) == 3 and args[0] == "export":
            for rel, body in export(args[1]).items():
                p = Path(args[2]) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
            return 0
        if len(args) == 3 and args[0] == "import":
            for rel in write(args[1], args[2]):
                print(f"schema/{rel}")
            return 0
    except (LinkMLError, pack.CompileError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(line.strip() for line in __doc__.strip().splitlines()[-2:]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
