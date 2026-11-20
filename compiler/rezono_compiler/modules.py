"""Schema modules and pack imports: which LinkML files make up a pack, and what each name refers to.

Every `schema/**/*.yaml` is a module, named by its path under `schema/` (`platform`, `domains/dc3`).
A module of an imported pack is `<pack>:<path>`. A schema imports `linkml:types`, a module of its own
pack by relative path, or a module of a pack its pack imports as `<pack>:<path>`; nothing else. A pack
import in `pack.yaml` is pinned on the hash of the imported pack's files (`pack_hash`).

A name in a module means the class or enum of that name in the module's import closure; two of them in
one closure is an error. A name declared by one module only keeps its plain engine name (`SomeClass`
→ `some_class`). A name declared by more than one module is qualified by its module everywhere
(`core:Any` → `core_any`), so names from different modules and packs never clash.

A module may declare its interface in its pack's `pack.yaml` (`modules:`): the kinds and enums other modules
may use, each with an optional deprecation date. Another module that names a kind or enum outside that list
(as a parent or a range) is a compile error; one that names a deprecated element gets a warning with the
date. The date is never compared with a clock, so the same pack always gives the same result. A module
without an interface keeps everything public. The module itself, and only it, uses its private elements.
An entry may also, or only, name the `namespace` of the module's kinds; `pack.iris` reads and checks it.

A module written in Rezono (`rezono/**/*.rezono`, named in pack.yaml with its JSON form) is a module of its pack
too, named by its path under `rezono/`: `rezono_module` lowers it to the schema a LinkML file would hold, and it
imports the modules of its pack whose kinds and enums it names (docs/rezono/publication.md §2, §3).
"""

from __future__ import annotations

import datetime as dt
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from linkml_runtime.linkml_model import SchemaDefinition
from .schemaview import SchemaView
from rezono_canon import canonical_sha256, sha256_hex

from . import rezono_module, standard_packs, strict_yaml

# The files that define a pack: everything the compiler reads but facts, scenarios and diagnostics (data)
# and expected output. Its hash covers exactly these: the import pin and the publication's
# definition_sha256. A new kind of definition file is added here, and only here.
DEFINITION = ("pack.yaml", "channels.yaml", "schema/**/*.yaml", "rezono/**/*.rezono", "rezono/**/*.json",
              "labels/*.yaml", "messages/*.mf2", "rules/*.dl", "calc/*.yaml", "sweeps.yaml", "questions.yaml",
              "views.yaml", "icons/*.svg", "icons/sources.yaml")
PACK_NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class Module:
    id: str  # 'platform', 'domains/dc3', or 'shared-terms:terms' in an imported pack
    pack: str  # the name of the pack it belongs to
    pack_dir: Path
    file: Path
    sv: SchemaView
    imports: list[str] = field(default_factory=list)  # module ids, resolved
    # The public kinds and enums, LinkML name -> deprecation date or None; None: no interface, all public.
    interface: dict[str, str | None] | None = None
    form: dict | None = None  # the effective JSON form when `file` is written in Rezono

    @property
    def rel(self) -> str:
        return self.file.relative_to(self.pack_dir).as_posix()


@dataclass
class Imported:
    name: str
    version: str
    sha256: str
    dir: Path
    meta: dict
    imports: list[str]  # names of the packs it imports itself


class _LegacySchemaView(SchemaView):
    """Resolve legacy relative imports without losing their pack in LinkML's closure."""

    def __init__(self, source: Path, importmap: dict[str, str | dict],
                 lowered_paths: dict[Path, SchemaDefinition], relative_imports: dict[Path, dict[str, str]]) -> None:
        super().__init__(source, importmap=importmap)
        self.lowered_paths = lowered_paths
        self.relative_imports = relative_imports

    def load_import(self, imp: str, from_schema: SchemaDefinition | None = None) -> SchemaDefinition:
        source = (from_schema if from_schema is not None else self.schema).source_file
        if self.lowered_paths and source and ":" not in imp:
            path = (Path(source).parent / f"{imp}.yaml").resolve()
            if path in self.lowered_paths:
                return deepcopy(self.lowered_paths[path])
        imported = super().load_import(imp, from_schema=from_schema)
        if self.relative_imports and imported.source_file:
            aliases = self.relative_imports.get(Path(imported.source_file).resolve())
            if aliases:
                # LinkML keys its closure by import name. Qualify relative imports
                # on the dependency copy before it follows them.
                imported.imports = [aliases.get(name, name) for name in imported.imports]
        return imported


def pack_hash(pack_dir: str | Path) -> str:
    """The canonical hash of {path: sha256 of the file's bytes} over every definition file."""
    pack_dir = Path(pack_dir)
    files = {p for g in DEFINITION for p in pack_dir.glob(g) if p.is_file()}
    return canonical_sha256({p.relative_to(pack_dir).as_posix(): sha256_hex(p.read_bytes()) for p in files})


def definition_files(pack_dir: str | Path) -> list[Path]:
    """The files `pack_hash` covers, sorted."""
    pack_dir = Path(pack_dir)
    return sorted({p for g in DEFINITION for p in pack_dir.glob(g) if p.is_file()})


def closure(pack_dir: str | Path) -> tuple[Path, list[tuple[str, Path]]]:
    """What must travel with a pack for its imports to resolve: the directory that holds the pack and every
    pack it imports (directly or not), and each directory an import names, with the pack's name. A pack
    reached by two paths (a diamond) is listed at both, since each importer's pack.yaml names its own path.
    Each import is checked against its pinned hash first. Paths stay as written: an import
    through a symbolic link is refused, as a copy could not keep the link's alias. An import is a path
    relative to the pack, so a copy keeps them where they are relative to each other: under that common
    directory. Raises ValueError for an import that does not hold."""
    pack_dir = Path(os.path.abspath(pack_dir))
    meta = strict_yaml.read(pack_dir / "pack.yaml") or {}
    errors: list[str] = []
    imported_packs(pack_dir, meta, errors)  # names, pins and cycles, as the compiler checks them
    if errors:
        raise ValueError("; ".join(errors))
    found: dict[Path, str] = {}
    todo = [(pack_dir, meta)]
    while todo:
        at, m = todo.pop()
        for imp in m.get("imports") or []:
            d = Path(os.path.normpath(at / str(imp["path"])))
            if os.path.relpath(d, at) != os.path.relpath(d.resolve(), at.resolve()):
                raise ValueError(f"{at.name}/pack.yaml: import {imp['name']} goes through a symbolic link ({imp['path']})")
            if pack_hash(d) != imp["sha256"]:
                raise ValueError(f"{at.name}/pack.yaml: import {imp['name']} is not the pinned {imp['sha256']}")
            if d not in found:
                found[d] = str(imp["name"])
                todo.append((d, strict_yaml.read(d / "pack.yaml") or {}))
    dirs = sorted((name, d) for d, name in found.items())
    return Path(os.path.commonpath([pack_dir, *(d for _, d in dirs)])), dirs


# Never copied with a pack: expected output and caches are no part of it.
NOT_COPIED = {"expected", "__pycache__"}


def closure_files(pack_dir: str | Path) -> tuple[Path, list[tuple[str, Path]]]:
    """The pack's own files and the definition files of every pack it imports, each with its path relative
    to the common directory of `closure`, and the pack's own path there ("." when it imports nothing).
    Only definition files of an imported pack: exactly what its pinned hash covers."""
    pack_dir = Path(os.path.abspath(pack_dir))
    base, imports = closure(pack_dir)
    out = {}
    for p in sorted(pack_dir.rglob("*")):
        rel = p.relative_to(pack_dir)
        if p.is_file() and not NOT_COPIED.intersection(rel.parts):
            out[p.relative_to(base).as_posix()] = p
    for _, d in imports:
        for p in definition_files(d):
            out.setdefault(p.relative_to(base).as_posix(), p)
    return pack_dir.relative_to(base), sorted(out.items())


def copy_closure(pack_dir: str | Path, dest: str | Path, check=None) -> Path:
    """Copy the pack with every pack it imports into `dest` (which must not exist yet), laid out as in
    `closure_files`, and return where the pack is in the copy. Its imports resolve there and are checked
    against their pins whenever the copy is read. `check(path)` runs on the pack's place in the copy
    before anything is written (the writer's work-dir check)."""
    dest = Path(dest)
    at, files = closure_files(pack_dir)
    if check:
        check(dest / at)
    dest.mkdir(parents=True)
    for rel, src in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
    return dest / at


def module_id(pack: str | None, rel: str) -> str:
    return rel if pack is None else f"{pack}:{rel}"


def imported_packs(pack_dir: Path, meta: dict, errors: list[str]) -> dict[str, Imported]:
    """Every pack imported directly or indirectly, by name, each checked against its pinned hash."""
    found: dict[str, Imported] = {}

    def visit(at: Path, meta: dict, stack: list[str]) -> list[str]:
        imports = meta.get("imports") or []
        if not isinstance(imports, list):
            errors.append(f"{at.name}/pack.yaml: imports must be a list")
            return []
        names = []
        for imp in imports:
            where = f"{at.name}/pack.yaml: import {imp}"
            if not isinstance(imp, dict) or set(imp) != {"name", "path", "sha256"}:
                errors.append(f"{where}: needs exactly name, path and sha256")
                continue
            name, d = str(imp["name"]), (at / str(imp["path"])).resolve()
            if not PACK_NAME.match(name) or not SHA256.match(str(imp["sha256"])):
                errors.append(f"{where}: name must be a pack name and sha256 64 lower-case hex digits")
                continue
            if name in stack:
                errors.append(f"{where}: imports form a cycle ({' -> '.join(stack + [name])})")
                continue
            if not (d / "pack.yaml").is_file():
                errors.append(f"{where}: no pack.yaml in {d}")
                continue
            sub = strict_yaml.read(d / "pack.yaml") or {}
            if sub.get("name") != name:
                errors.append(f"{where}: the pack in {imp['path']} is named {sub.get('name')!r}")
                continue
            digest = pack_hash(d)
            why = (f"the files hash to {digest}, not the pinned {imp['sha256']}" if digest != imp["sha256"]
                   else standard_packs.refusal(name, digest))
            if why:
                errors.append(f"{where}: {why}")
                continue
            if name in found and found[name].sha256 != digest:
                errors.append(f"{where}: pack {name} is imported twice with different contents")
                continue
            names.append(name)
            if name not in found:
                found[name] = Imported(name, str(sub.get("version", "")), digest, d, sub, [])
                found[name].imports = visit(d, sub, stack + [name])
        return sorted(names)

    visit(pack_dir, meta, [meta.get("name", "")])
    return dict(sorted(found.items()))


def load(pack_dir: Path, meta: dict, errors: list[str]) -> tuple[list[Module], dict[str, Imported]]:
    """The modules of the pack and of every imported pack, with their imports resolved to module ids."""
    packs = imported_packs(pack_dir, meta, errors)
    sources = [(None, pack_dir, [p for p in packs if p in direct(meta)])] + \
              [(name, p.dir, p.imports) for name, p in packs.items()]
    modules: dict[str, Module] = {}
    authored: dict[str | None, dict[str, dict]] = {}
    lowered_paths: dict[Path, SchemaDefinition] = {}
    relative_imports: dict[Path, dict[str, str]] = {}
    views: list[tuple[dict[str, str | dict], list[str | None]]] = []
    for name, d, imports in sources:
        visible = dependency_order(packs, imports)
        pack = name or meta["name"]
        importmap: dict[str, str | dict] = {f"{n}:": str(packs[n].dir / "schema") for n in visible}
        importmap[f"{pack}:"] = str((d / "schema").resolve())
        views.append((importmap, [*visible, name]))
        own_meta = packs[name].meta if name else meta
        here: dict[Path, Module] = {}  # by the path a schema file of the module has, or would have, under schema/
        for f in sorted((d / "schema").rglob("*.yaml")):
            rel = f.relative_to(d / "schema").with_suffix("").as_posix()
            try:
                sv = _LegacySchemaView(f, importmap, lowered_paths, relative_imports)
                sv.schema  # noqa: B018 -- LinkML parses on first use; a parse error is a compile error
            except (TypeError, ValueError) as e:
                errors.append(f"{f.relative_to(d).as_posix()}: LinkML cannot read it ({e}); an annotation whose value is "
                              "a mapping is written `tag: {value: {...}}`")
                continue
            here[f.relative_to(d / "schema")] = Module(module_id(name, rel), pack, d, f, sv)
        lowered, authored[name] = rezono_modules(d, own_meta, name, pack, here, importmap, errors, packs)
        here |= lowered
        lowered_paths.update({(d / "schema" / path).resolve(): m.sv.schema for path, m in lowered.items()})
        modules |= {m.id: m for _, m in sorted(here.items())}
        for rel, interface in interfaces(own_meta, d, errors).items():
            mid = module_id(name, rel)
            if mid in modules:
                modules[mid].interface = interface
            else:
                errors.append(f"{d.name}/pack.yaml: modules: '{rel}' is not a module (a path under schema/ without .yaml)")
    for m in modules.values():
        if m.form is not None:  # a module written in Rezono: its imports are the modules whose names it uses
            continue
        own = None if m.pack == meta["name"] else m.pack
        allowed = packs[own].imports if own else [p for p in packs if p in direct(meta)]
        aliases: dict[str, str] = {}
        for imp in m.sv.schema.imports or []:
            imp = str(imp)
            prefix, _, rest = imp.partition(":")
            if imp == "linkml:types":
                continue
            if rest and prefix in allowed:
                target = module_id(prefix, rest)
            elif rest:
                errors.append(f"{m.rel}: import '{imp}' names no pack that {m.pack} imports")
                continue
            else:
                path = (m.file.parent / f"{imp}.yaml").resolve()
                schema_dir = (m.pack_dir / "schema").resolve()
                if schema_dir not in path.parents:
                    errors.append(f"{m.rel}: import '{imp}' is outside schema/; import another pack in pack.yaml")
                    continue
                target = module_id(own, path.relative_to(schema_dir).with_suffix("").as_posix())
            if target not in modules:
                errors.append(f"{m.rel}: import '{imp}' is not a module")
                continue
            m.imports.append(target)
            if not rest:
                aliases[imp] = target if own else module_id(m.pack, target)
        m.imports.sort()
        if aliases:
            relative_imports[m.file.resolve()] = aliases
    # A SchemaView can traverse another pack's imports. Make every lowered schema in
    # that pinned closure available under its logical name before LinkML follows it.
    for importmap, visible in views:
        for name in visible:
            importmap.update(authored[name])
    if not errors:
        for m in modules.values():
            if m.form is not None:
                try:
                    classes = m.sv.all_classes()
                    for kind in m.sv.schema.classes.values():
                        for slot in kind.attributes.values():
                            if slot.inlined and slot.range not in classes:
                                errors.append(f"{m.pack_dir.name}/{m.rel}: {kind.name}.{slot.name}: "
                                              f"an embedded reference must name a kind, not {slot.range}")
                except (TypeError, ValueError, OSError) as e:
                    errors.append(f"{m.pack_dir.name}/{m.rel}: LinkML cannot read its lowered schema ({e})")
    return list(modules.values()), packs


def schema_names(pack_dir: Path) -> dict[str, set[str]]:
    """The kinds, enums and types each schema file of a pack declares, by module id within the pack."""
    out: dict[str, set[str]] = {}
    for f in sorted((pack_dir / "schema").rglob("*.yaml")):
        try:
            doc = strict_yaml.read(f) or {}
        except (OSError, ValueError, yaml.YAMLError):
            continue  # load() reports a file LinkML cannot read
        if isinstance(doc, dict):
            out[f.relative_to(pack_dir / "schema").with_suffix("").as_posix()] = {
                str(n) for key in ("classes", "enums", "types") if isinstance(doc.get(key), dict) for n in doc[key]}
    return out


def _integer_type_names(tnames: list[str] | set[str], bases: dict[str, str]) -> set[str]:
    """Return the type names whose typeof chain in `bases` reaches `integer`."""
    ints: set[str] = set()
    for tname in tnames:
        cur, seen = bases.get(tname), set()
        while cur and cur not in seen:
            if cur == "integer":
                ints.add(tname)
                break
            seen.add(cur)
            cur = bases.get(cur)
    return ints


def _integer_types(local: dict[str, Module], packs: dict[str, Imported] | None,
                   pinned: dict[str, dict[str, set[str]]]) -> dict[str, set[str]]:
    """Scalar types in local or pinned LinkML schemas whose typeof chain reaches integer."""
    out: dict[str, set[str]] = {}
    local_bases = {
        str(tname): body.typeof
        for m in local.values()
        for tname, body in (m.sv.schema.types or {}).items()
        if body.typeof
    }
    for mid, m in local.items():
        if ints := _integer_type_names({str(tname) for tname in (m.sv.schema.types or {})}, local_bases):
            out[mid] = ints
    for n in pinned:
        bases: dict[str, str] = {}
        by_module: dict[str, list[str]] = {}
        for f in sorted((packs[n].dir / "schema").rglob("*.yaml")):
            try:
                doc = strict_yaml.read(f) or {}
            except (OSError, ValueError, yaml.YAMLError):
                continue
            if isinstance(doc, dict) and isinstance(doc.get("types"), dict):
                mid = f.relative_to(packs[n].dir / "schema").with_suffix("").as_posix()
                for tname, body in doc["types"].items():
                    if isinstance(body, dict) and isinstance(body.get("typeof"), str):
                        bases[str(tname)] = body["typeof"]
                        by_module.setdefault(mid, []).append(str(tname))
        for mid, tnames in by_module.items():
            if ints := _integer_type_names(tnames, bases):
                out[f"{n}:{mid}"] = ints
    return out


def rezono_modules(d: Path, meta: dict, name: str | None, pack: str, schemas: dict[Path, Module], importmap: dict,
                   errors: list[str], packs: dict[str, Imported] | None = None) -> tuple[dict[Path, Module], dict[str, dict]]:
    """The modules written in Rezono of one pack, lowered (`rezono_module`), each with the path a schema file of
    it would have, so that it takes its place among the pack's schema modules as that file would. A lowered
    module imports the modules of its pack whose names it uses: a schema file by `<pack>:<path>`, another
    module by its schema, which LinkML reads from the import map."""
    local = {m.id.partition(":")[2] if name else m.id: m for m in schemas.values()}
    declared_by = {mid: set(m.sv.all_classes(imports=False)) | set(m.sv.all_enums(imports=False))
                   | set(m.sv.all_types(imports=False))
                   for mid, m in local.items()}
    pinned = {n: schema_names(packs[n].dir) for n in direct(meta) if packs and n in packs}
    integer_types = _integer_types(local, packs or {}, pinned)
    lowered = rezono_module.lower_pack(d, meta, pack, declared_by, errors, imported=name is not None,
                                       pinned=pinned, integer_types=integer_types)
    key = {x: f"{pack}:{x}" for x in local} | {low.declared.id: f"{pack}:{rezono_module.DIR}/{low.declared.id}.rezono"
                                                 for low in lowered}
    for low in lowered:
        low.schema["imports"] += [key[x] for x in low.uses]
    out, authored = {}, {}
    for low in lowered:
        mid = low.declared.id
        try:
            sv = rezono_module.view(low.schema, importmap)
        except (TypeError, ValueError, OSError) as e:
            errors.append(f"{d.name}/{low.declared.module}: LinkML cannot read its lowered schema ({e})")
            continue
        out[Path(f"{mid}.yaml")] = Module(module_id(name, mid), pack, d, d / low.declared.module, sv,
                                          sorted([module_id(name, x) for x in low.uses] + low.foreign), form=low.form)
        authored[key[mid]] = low.schema
        authored[f"{pack}:{mid}"] = low.schema
    return out, authored


def interfaces(meta: dict, pack_dir: Path, errors: list[str]) -> dict[str, dict[str, str | None]]:
    """The module interfaces a pack.yaml declares: {module path: {public name: deprecation date or None}}."""
    where = f"{pack_dir.name}/pack.yaml: modules"
    declared = meta.get("modules")
    if declared is None:
        return {}
    if not isinstance(declared, list):
        errors.append(f"{where}: a list of {{module, public, namespace}}")
        return {}
    out: dict[str, dict[str, str | None]] = {}
    seen: set[str] = set()
    for i, entry in enumerate(declared):
        # `namespace` is the namespace of the module's kinds (pack.yaml `iri:`, read by pack.iris); an entry with
        # only a namespace declares no interface, so its module keeps everything public.
        if not isinstance(entry, dict) or "module" not in entry or set(entry) - {"module", "public", "namespace"} \
                or not ({"public", "namespace"} & set(entry)) or not isinstance(entry.get("public", []), list):
            errors.append(f"{where}[{i}]: needs 'module' and a list 'public', a 'namespace', or both")
            continue
        rel = str(entry["module"])
        if rel in seen:
            errors.append(f"{where}: module '{rel}' is declared twice")
            continue
        seen.add(rel)
        if "public" not in entry:
            continue
        public: dict[str, str | None] = {}
        for j, item in enumerate(entry["public"]):
            if not isinstance(item, dict) or "name" not in item or set(item) - {"name", "deprecated"}:
                errors.append(f"{where}[{i}].public[{j}]: needs 'name' and may have 'deprecated' (a date)")
                continue
            name, date = str(item["name"]), item.get("deprecated")
            if name in public:
                errors.append(f"{where}: '{name}' is public twice in module '{rel}'")
            if date is not None:
                date = date.isoformat() if isinstance(date, dt.date) else str(date)
                try:
                    if dt.date.fromisoformat(date).isoformat() != date:
                        raise ValueError(date)
                except ValueError:
                    errors.append(f"{where}: deprecated date of '{name}' is not a date YYYY-MM-DD: {date!r}")
                    date = None
            public[name] = date
        out[rel] = public
    return out


def dependency_order(packs: dict[str, Imported], roots: list[str]) -> list[str]:
    """Imported pack names, every pack after the packs it imports, so that a later one can override."""
    out: list[str] = []

    def visit(name: str) -> None:
        if name in out:
            return
        for dep in packs[name].imports:
            visit(dep)
        out.append(name)

    for name in sorted(roots):
        if name in packs:
            visit(name)
    return out


def direct(meta: dict) -> list[str]:
    return [str(i.get("name")) for i in meta.get("imports") or [] if isinstance(i, dict)]


class Names:
    """Engine names for classes and enums, and what a name means inside a module."""

    def __init__(self, modules: list[Module], snake, errors: list[str], root: str | None = None,
                 warnings: list[str] | None = None):
        self.modules = {m.id: m for m in modules}
        self.root = root  # name the modules of this pack as it does on its own, without '<pack>:'
        self.snake = snake
        self.errors = errors
        self.warnings = [] if warnings is None else warnings
        self.used: set[tuple[str, str, str]] = set()  # (module, owner, name) already checked against the interface
        self.declared: dict[str, dict[str, str]] = {}  # module id -> {LinkML name: 'class' or 'enum'}
        for m in modules:
            self.declared[m.id] = {**{c: "enum" for c in m.sv.all_enums(imports=False)},
                                   **{c: "class" for c in m.sv.all_classes(imports=False)}}
            for n in sorted(set(m.interface or {}) - set(self.declared[m.id])):
                errors.append(f"{m.pack}/pack.yaml: module '{m.rel}' lists '{n}' as public, but declares no class "
                              f"or enum of that name")
        owners: dict[str, list[str]] = {}
        for mid, names in self.declared.items():
            for n in names:
                owners.setdefault(snake(n), []).append(mid)
        self.shared = {n for n, ms in owners.items() if len(ms) > 1}
        self.closures = {mid: self.closure(mid) for mid in self.modules}
        for mid, closure in sorted(self.closures.items()):
            seen: dict[str, str] = {}
            for other in closure:
                for n in self.declared[other]:
                    if n in seen and seen[n] != other:
                        errors.append(f"{self.modules[mid].rel}: '{n}' is declared in modules {seen[n]} and {other}, "
                                      f"which it both imports")
                    seen.setdefault(n, other)

    def closure(self, mid: str) -> list[str]:
        out, todo = [], [mid]
        while todo:
            x = todo.pop()
            if x not in out:
                out.append(x)
                todo += self.modules[x].imports
        return sorted(out)

    def name(self, mid: str, linkml_name: str) -> str:
        """The engine name of a class or enum declared in module `mid`."""
        base = self.snake(linkml_name)
        local = mid.partition(":")[2] if self.root and mid.startswith(f"{self.root}:") else mid
        return f"{re.sub(r'[/:-]', '_', local)}_{base}" if base in self.shared else base

    def owner(self, mid: str, linkml_name: str) -> str | None:
        """The module, in the import closure of `mid`, that declares `linkml_name`."""
        if linkml_name in self.declared[mid]:
            return mid
        return next((o for o in self.closures[mid] if linkml_name in self.declared[o]), None)

    def resolve(self, mid: str, linkml_name: str) -> str | None:
        """The engine name of `linkml_name` as module `mid` uses it, held to the owner's interface."""
        o = self.owner(mid, linkml_name)
        if o is None:
            return None
        if o != mid and (mid, o, linkml_name) not in self.used:
            self.used.add((mid, o, linkml_name))
            interface, user = self.modules[o].interface, self.modules[mid].rel
            if interface is not None and linkml_name not in interface:
                self.errors.append(f"{user}: uses '{linkml_name}' of module {o}, which is not in that "
                                   f"module's public interface (pack.yaml, modules)")
            elif interface and interface[linkml_name]:
                self.warnings.append(f"{user}: uses '{linkml_name}' of module {o}, deprecated from "
                                     f"{interface[linkml_name]}")
        return self.name(o, linkml_name)
