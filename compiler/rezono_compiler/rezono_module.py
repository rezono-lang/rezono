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

from collections import OrderedDict
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable, Iterator, Mapping, Set
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from . import rezono_alias, rezono_calc, rezono_enum, rezono_extend, rezono_key, rezono_kind, rezono_metadata, rezono_reason, rezono_slot, rezono_unit, strict_yaml
from .native_literals import NATIVE_FORMAT, native_literal_errors
from .schemaview import SchemaView
from linkml_runtime.linkml_model import SchemaDefinition
from linkml_runtime.loaders.yaml_loader import YAMLLoader

FORMAT = "rezono.module/1"
IDENTIFIER_FORMAT = "rezono.module/2"
SAFE_STEP_FORMAT = "rezono.module/4"
REZONO_1_FORMAT = "rezono.module/5"
NATIVE_FORMATS = (NATIVE_FORMAT, SAFE_STEP_FORMAT)
DIR = "rezono"
PACKAGED_READER = Path(__file__).with_name("module_reader") / "src" / "write-form.js"
CHECKOUT_READER = Path(__file__).resolve().parents[2] / DIR / "src" / "write-form.ts"
KEY = "rezono"  # the key of pack.yaml (contract RezonoModule in contracts/pack.yaml)
PAGE = "docs/rezono/publication.md"
DATASET_FORMAT = "rezono.module/2"
DATASET_FORMATS = (DATASET_FORMAT, REZONO_1_FORMAT)
PATH = re.compile(r"^rezono/[a-z][a-z0-9_]*(/[a-z][a-z0-9_]*)*\.(rezono|json)$")
# Declarations this slice does not lower, by the member that names them: what, and where the page says so.
REFUSED = {
    "rounding": ("a rounding is not lowered yet", "§6"),
    "param": ("a parameter is not lowered yet", "§6"),
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
    foreign: list[str] = field(default_factory=list)  # `<pack>:<module>` of the schema modules of the used packs
    reasons: list[tuple[str, str]] = field(default_factory=list)  # (code, label) in declaration order


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
        if not include_datasets and is_dataset_form(pack_dir / form, pack_dir / module):
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


def _load_form(pack_dir: Path, d: Declared, source: Path | bytes, errors: list[str],
               *, authored: bool = False) -> dict | None:
    """Validate and decode a module form from a file path or raw UTF-8 JSON bytes."""
    where = f"{pack_dir.name}/{d.module if authored else d.form}"
    try:
        doc = json.loads(source.read_bytes() if isinstance(source, Path) else source)
    except (OSError, ValueError) as e:
        errors.append(f"{where}: not a JSON file ({e})")
        return None
    module = (
        module_body(doc, FORMAT)
        or module_body(doc, IDENTIFIER_FORMAT)
        or module_body(doc, NATIVE_FORMAT)
        or module_body(doc, SAFE_STEP_FORMAT)
        or module_body(doc, REZONO_1_FORMAT)
    )
    if module is None:
        errors.append(
            f"{where}: not the form of a module ({FORMAT}, {IDENTIFIER_FORMAT}, {NATIVE_FORMAT}, {SAFE_STEP_FORMAT}, or {REZONO_1_FORMAT},"
            " contracts/rezono-module.yaml)"
        )
        return None
    findings = native_literal_errors(doc)
    if findings:
        errors.extend(f"{where}: {finding}" for finding in findings)
        return None
    spans = doc["spans"]
    if not valid_places(module, spans) and not (
        "schema" in module and valid_places(module, spans, legacy_metadata=True)
        and not authored and form_only_source(pack_dir / d.module, doc)
    ):
        errors.append(f"{where}: spans must place each module node once, in order, with a positive line and "
                      "nonnegative start and end offsets in ascending order (contracts/rezono-module.yaml)")
        return None
    return doc


def read_form(pack_dir: Path, d: Declared, errors: list[str],
              *, authored_output: Path | None = None) -> dict | None:
    """The form of a module, if it is one: format, module and spans, and nothing else."""
    path = authored_output if authored_output is not None else pack_dir / d.form
    return _load_form(pack_dir, d, path, errors, authored=authored_output is not None)


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
    fmt = submitted["format"]
    version = "1" if fmt == REZONO_1_FORMAT else "0"
    matches_legacy = not submitted["spans"] and not any(header_errors(module, pack, form_format=fmt))
    header = f"rezono {version}\npack {pack}\ndataset {name}"
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
    if submitted["format"] != NATIVE_FORMAT and legacy(source):
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


_AUTHORED_CACHE_LIMIT = 512
_BATCH_ARGV_LIMIT = 200
_CacheKey = tuple[str, str, str, str]
_CacheValue = tuple[bool, bytes | tuple[str, ...]]
_AUTHORED_CACHE: OrderedDict[_CacheKey, _CacheValue] = OrderedDict()


def clear_form_cache() -> None:
    """Clear memoized authored module forms."""
    _AUTHORED_CACHE.clear()


def _cache_key(pack_dir: Path, d: Declared, reader: Path, node: str, data: bytes) -> _CacheKey:
    return (str((pack_dir / d.module).resolve()), str(reader), node, hashlib.sha256(data).hexdigest())


def _cache_get(key: _CacheKey) -> _CacheValue | None:
    entry = _AUTHORED_CACHE.get(key)
    if entry is not None:
        _AUTHORED_CACHE.move_to_end(key)
    return entry


def _cache_put(key: _CacheKey, value: _CacheValue) -> None:
    _AUTHORED_CACHE[key] = value
    _AUTHORED_CACHE.move_to_end(key)
    while len(_AUTHORED_CACHE) > _AUTHORED_CACHE_LIMIT:
        _AUTHORED_CACHE.popitem(last=False)


def _invoke_reader(reader: Path, node: str, items: list[tuple[_CacheKey, bytes]]) -> dict[_CacheKey, _CacheValue] | None:
    """Run the module reader once for all uncached items, caching deterministic outcomes."""
    by_sha: dict[str, tuple[bytes, list[_CacheKey]]] = {}
    for key, data in items:
        if _cache_get(key) is not None:
            continue
        sha = key[3]
        if sha not in by_sha:
            by_sha[sha] = (data, [key])
        else:
            by_sha[sha][1].append(key)
    if not by_sha:
        return {}
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("NODE_")}
    unique = list(by_sha.values())
    try:
        with TemporaryDirectory(prefix="rezono-module-") as directory:
            base = Path(directory)
            pairs: list[tuple[Path, Path, list[_CacheKey]]] = []
            run_kwargs: dict[str, object] = {}
            if len(unique) == 1:
                source, target = base / "source.rezono", base / "form.json"
                source.write_bytes(unique[0][0])
                pairs.append((source, target, unique[0][1]))
                cmd = [node, str(reader), source.name, target.name]
            else:
                for idx, (data, keys) in enumerate(unique):
                    source, target = base / f"m{idx}.rezono", base / f"m{idx}.json"
                    source.write_bytes(data)
                    pairs.append((source, target, keys))
                if len(pairs) <= _BATCH_ARGV_LIMIT:
                    cmd = [node, str(reader), "--batch", *(name for s, t, _ in pairs for name in (s.name, t.name))]
                else:
                    cmd = [node, str(reader), "--batch"]
                    run_kwargs["input"] = json.dumps([[s.name, t.name] for s, t, _ in pairs])
            result = subprocess.run(
                cmd, cwd=directory, capture_output=True, encoding="utf-8", env=env, **run_kwargs,  # type: ignore[arg-type]
            )
            outcomes: dict[_CacheKey, _CacheValue] = {}
            stderr_lines = result.stderr.splitlines()
            for source, target, keys in pairs:
                if (result.returncode == 0 or len(pairs) > 1) and target.is_file():
                    outcome: _CacheValue = (True, target.read_bytes())
                    for key in keys:
                        _cache_put(key, outcome)
                        outcomes[key] = outcome
                else:
                    prefix = f"{source.name}:"
                    diags = tuple(line.split(":", 1)[1] for line in stderr_lines if line.startswith(prefix))
                    outcome = (False, diags)
                    for key in keys:
                        if diags:
                            _cache_put(key, outcome)
                        outcomes[key] = outcome
            return outcomes
    except (OSError, UnicodeError):
        return None


def _pending_authored(pack_dir: Path, meta: dict, decls: Iterable[Declared],
                      reader: Path, node: str, *, datasets_only: bool = False) -> list[tuple[_CacheKey, bytes]]:
    """Collect uncached (cache_key, source_bytes) pairs for declared modules that invoke the reader."""
    pack_name = str(meta.get("name", ""))
    source_dir = pack_dir.resolve() / DIR
    out: list[tuple[_CacheKey, bytes]] = []
    for d in decls:
        mod_path, form_path = pack_dir / d.module, pack_dir / d.form
        try:
            if not (mod_path.resolve().is_relative_to(source_dir) and form_path.resolve().is_relative_to(source_dir)):
                continue
            submitted = json.loads(form_path.read_bytes())
            data = mod_path.read_bytes()
            source = data.decode("utf-8")
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(submitted, dict):
            continue
        fmt = submitted.get("format")
        if fmt not in (FORMAT, IDENTIFIER_FORMAT, NATIVE_FORMAT, SAFE_STEP_FORMAT, REZONO_1_FORMAT):
            continue
        if module_body(submitted, fmt) is None:
            continue
        if datasets_only:
            plain = module_body(submitted, FORMAT) or module_body(submitted, REZONO_1_FORMAT)
            if plain is not None and fact_tables_only(plain):
                if form_only_source(mod_path, submitted):
                    continue
            else:
                mod = module_body(submitted, DATASET_FORMAT) or module_body(submitted, REZONO_1_FORMAT)
                if mod is None or not any(isinstance(decl, dict) and "dataset" in decl for decl in mod["decls"]):
                    continue
                ds_only = dataset_only(submitted)
                ds_mod = ds_only["module"]
                name = Path(d.module).stem
                version = "1" if fmt == REZONO_1_FORMAT else "0"
                if (not ds_only["spans"] and not any(header_errors(ds_mod, pack_name, form_format=fmt))
                        and source.replace("\r\n", "\n").removesuffix("\n") == f"rezono {version}\npack {pack_name}\ndataset {name}"):
                    continue
        elif fmt != NATIVE_FORMAT:
            try:
                if legacy_header(source, submitted):
                    continue
            except (KeyError, TypeError):
                continue
            ds_mod = module_body(submitted, DATASET_FORMAT) or module_body(submitted, REZONO_1_FORMAT)
            if ds_mod is not None and named_dataset(ds_mod) is not None:
                name = Path(d.module).stem
                version = "1" if fmt == REZONO_1_FORMAT else "0"
                if (not submitted["spans"] and not any(header_errors(ds_mod, pack_name, form_format=fmt))
                        and source.replace("\r\n", "\n").removesuffix("\n") == f"rezono {version}\npack {pack_name}\ndataset {name}"):
                    continue
        key = _cache_key(pack_dir, d, reader, node, data)
        if _cache_get(key) is None:
            out.append((key, data))
    return out


def warm_packs(entries: Iterable[tuple[Path, dict, bool]]) -> None:
    """Batch-parse all uncached authored Rezono modules across packs in a single reader invocation."""
    reader = PACKAGED_READER if PACKAGED_READER.is_file() else CHECKOUT_READER
    if not reader.is_file():
        return
    node = os.environ.get("REZONO_NODE", "node")
    pending: list[tuple[_CacheKey, bytes]] = []
    for pack_dir, meta, include_datasets in entries:
        if not isinstance(meta, dict):
            continue
        decls = declared(meta, pack_dir, [], reject_undeclared=False, include_datasets=include_datasets)
        pending.extend(_pending_authored(pack_dir, meta, decls, reader, node))
    if pending:
        _invoke_reader(reader, node, pending)


def warm_pack_modules(pack_dir: Path, meta: dict, decls: Iterable[Declared], *, datasets_only: bool = False) -> None:
    """Batch-parse all uncached authored Rezono modules in `decls` in a single reader invocation."""
    reader = PACKAGED_READER if PACKAGED_READER.is_file() else CHECKOUT_READER
    if not reader.is_file():
        return
    node = os.environ.get("REZONO_NODE", "node")
    pending = _pending_authored(pack_dir, meta, decls, reader, node, datasets_only=datasets_only)
    if pending:
        _invoke_reader(reader, node, pending)


def authored_form(pack_dir: Path, d: Declared, data: bytes, errors: list[str]) -> dict | None:
    where = f"{pack_dir.name}/{d.module}"
    reader = PACKAGED_READER if PACKAGED_READER.is_file() else CHECKOUT_READER
    if not reader.is_file():
        errors.append(f"{where}: the compiler installation does not include the module reader")
        return None
    hint = "use Node 24" if reader == PACKAGED_READER else "use Node 24 and run npm ci in rezono/"
    node = os.environ.get("REZONO_NODE", "node")
    key = _cache_key(pack_dir, d, reader, node, data)
    outcome = _cache_get(key)
    if outcome is None:
        outcomes = _invoke_reader(reader, node, [(key, data)])
        if outcomes is None:
            errors.append(f"{where}: cannot run the module reader; {hint}")
            return None
        outcome = outcomes[key]
    ok, payload = outcome
    if ok:
        return _load_form(pack_dir, d, cast(bytes, payload), errors, authored=True)
    diags = cast(tuple[str, ...], payload)
    errors.extend([f"{where}:{line}" for line in diags] or [f"{where}: the module reader failed; {hint}"])
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
    if expected_format in (IDENTIFIER_FORMAT, REZONO_1_FORMAT):
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


def trailing_dataset(module: dict) -> bool:
    """A module whose last declaration is its named dataset, after declarations that are none
    (decisions/language-library-datasets.md): the declarations before it lower like any other module's."""
    declarations = module["decls"]
    return (len(declarations) > 1 and named_dataset(module | {"decls": declarations[-1:]}) is not None
            and not any(isinstance(decl, dict) and "dataset" in decl for decl in declarations[:-1]))


def dataset_only(form: dict) -> dict:
    """The form of a module with its trailing dataset as the form of that dataset alone; the places of the dataset
    keep their lines, and the places of the declarations before it are dropped. Any other form is returned as is."""
    module = form["module"]
    if not trailing_dataset(module):
        return form
    last = f"/decls/{len(module['decls']) - 1}"
    spans = []
    for span in form["spans"]:
        at = span["at"]
        if at == last or at.startswith(last + "/"):
            spans.append(span | {"at": "/decls/0" + at[len(last):]})
        elif not at.startswith("/decls/"):
            spans.append(span)
    return form | {"module": module | {"decls": module["decls"][-1:]}, "spans": spans}


def fact_tables_only(module: dict) -> bool:
    """A module whose declarations are all fact tables (§5.3): the form of a base fact file."""
    declarations = module["decls"]
    return bool(declarations) and all(
        isinstance(decl, dict) and isinstance(decl.get("fact"), str) and "columns" in decl and "rows" in decl
        for decl in declarations)


def is_dataset_form(path: Path, source: Path | None = None) -> bool:
    """Dispatch only recognized dataset forms; leave other documents to ordinary schema validation. With its
    source, an authored module of fact tables is one too; a form-only module is left to the refusal."""
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return False
    for fmt in DATASET_FORMATS:
        module = module_body(doc, fmt)
        if module is not None and named_dataset(module) is not None:
            return True
    for fmt in (FORMAT, REZONO_1_FORMAT):
        module = module_body(doc, fmt)
        if (source is not None and module is not None and fact_tables_only(module)
                and not form_only_source(source, doc)):
            return True
    return False


def pack_language_version(forms: Iterable[dict]) -> str:
    """Declared Rezono language version of a pack from its module forms ('1' if any uses rezono.module/5, else '0')."""
    for form in forms:
        if isinstance(form, dict) and form.get("format") == REZONO_1_FORMAT:
            return "1"
    return "0"


def header_errors(module: dict, pack: str, *, native_rules: bool = False,
                  schema: bool = False, form_format: str = FORMAT,
                  pack_version: str | None = None) -> Iterator[tuple[str, str, str]]:
    """Header refusals shared by schema lowering and dataset admission."""
    if pack_version == "1" or form_format == REZONO_1_FORMAT:
        if "rezono" not in module:
            yield "rezono", "missing `rezono 1` line in a `rezono 1` pack (R028)", "§3"
        elif module.get("rezono") != "1":
            yield "rezono", f"pack {pack} uses `rezono 1`, not `{module.get('rezono')}` (R027)", "§3"
        elif form_format != REZONO_1_FORMAT:
            yield "rezono", f"a `rezono 1` module requires {REZONO_1_FORMAT}, not {form_format} (R027)", "§3"
    elif module.get("rezono") != "0":
        yield "rezono", f"the `rezono` line says 0, not {module.get('rezono', 'nothing')}", "§3"
    if module["pack"] != pack:
        yield "pack", f"the `pack` line names {module['pack']}, not this pack, {pack}", "§3"
    if not native_rules and not schema:
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
    name = decl.get("kind", decl.get("enum", decl.get("type") if "base" in decl else decl.get("unit")))
    return name if isinstance(name, str) else None


def names(form: dict) -> dict[str, str]:
    """The schema names a form declares and the pointer of each first declaration."""
    out: dict[str, str] = {}
    for i, decl in enumerate(form["module"]["decls"]):
        name = declaration_name(decl) if isinstance(decl, dict) else None
        if name is not None:
            out.setdefault(name, f"/decls/{i}")
    return out


def type_bases(form: dict) -> dict[str, str]:
    """Declared unit and scalar-alias bases of one module form, mapping units and `Int` to `integer`."""
    out: dict[str, str] = {}
    for decl in form["module"]["decls"]:
        if not isinstance(decl, dict):
            continue
        if isinstance(decl.get("unit"), str):
            out[decl["unit"]] = "integer"
        elif isinstance(decl.get("type"), str) and isinstance(decl.get("base"), str):
            out[decl["type"]] = rezono_alias.BASES.get(decl["base"], decl["base"])
    return out


def integer_type_names(tnames: Iterable[str], bases: Mapping[str, str],
                       known_ints: Set[str] = frozenset()) -> set[str]:
    """Return the type names whose base chain in `bases` reaches `integer` or an external `known_ints`."""
    ints: set[str] = set()
    for tname in tnames:
        cur: str | None = bases.get(tname)
        seen: set[str] = {tname}
        while cur:
            if cur == "integer":
                ints.add(tname)
                break
            if cur in seen:
                break
            seen.add(cur)
            if cur in bases:
                cur = bases[cur]
                continue
            if cur in known_ints:
                ints.add(tname)
            break
    return ints


def lower_pack(pack_dir: Path, meta: dict, pack: str, declared_by: Mapping[str, Set[str]],
               errors: list[str], imported: bool = False,
               pinned: Mapping[str, Mapping[str, Set[str]]] | None = None,
               integer_types: Mapping[str, Set[str]] | None = None) -> list[Lowered]:
    """Lower every module of one pack. `pinned` holds, by pack name, the names each schema module declares of every
    pack that pack.yaml pins (the packs a `use` line may name). `pack` is the pack's name, `declared_by` the LinkML names each schema
    module of the pack declares, by module id within the pack, `imported` whether another pack imports it. Every
    refusal names the module's file and line."""
    decls = declared(meta, pack_dir, errors)
    warm_pack_modules(pack_dir, meta, decls)
    forms = {d: effective_form(pack_dir, d, errors) for d in decls}
    owners: dict[str, list[str]] = {}
    ints: dict[str, set[str]] = {mid: set(ns) for mid, ns in (integer_types or {}).items()}
    for mid, ns in sorted(declared_by.items()):
        for n in ns:
            owners.setdefault(n, []).append(mid)
    local_type_bases: dict[str, str] = {}
    by_module: dict[str, dict[str, str]] = {}
    reason_owners: dict[str, list[str]] = {}
    for d, form in forms.items():
        if d.id in declared_by:
            errors.append(f"{pack_dir.name}/{d.module}: module '{d.id}' is also a schema module (schema/{d.id}.yaml)")
        for n in names(form) if form else {}:
            owners.setdefault(n, []).append(d.id)
        for code in rezono_reason.codes(form) if form else ():
            reason_owners.setdefault(code, []).append(d.id)
        if form:
            mod_bases = type_bases(form)
            if mod_bases:
                by_module[d.id] = mod_bases
                local_type_bases.update(mod_bases)
    known_ints = {tname for ns in ints.values() for tname in ns}
    for mid, mod_bases in by_module.items():
        if local_ints := integer_type_names(mod_bases, local_type_bases, known_ints):
            ints.setdefault(mid, set()).update(local_ints)
    default_lang = str(meta.get("default_language", ""))
    defined_reasons = rezono_reason.defined_in_catalog(pack_dir, default_lang)
    pack_version = pack_language_version(form for form in forms.values() if form is not None)
    return [lower(pack_dir, d, form, pack, owners, errors, imported, pinned or {}, ints,
                  reason_owners=reason_owners, defined_reasons=defined_reasons, default_language=default_lang,
                  pack_version=pack_version)
            for d, form in forms.items() if form is not None]


def lower(pack_dir: Path, d: Declared, form: dict, pack: str, owners: dict[str, list[str]],
          errors: list[str], imported: bool = False,
          pinned: Mapping[str, Mapping[str, Set[str]]] | None = None,
          integer_types: Mapping[str, Set[str]] | None = None, *,
          reason_owners: Mapping[str, list[str]] | None = None,
          defined_reasons: Set[str] = frozenset(),
          default_language: str = "",
          pack_version: str = "0") -> Lowered:
    """One module's form as the LinkML schema that says the same (§5.1, §5.2), or a refusal at a line. An `extend`
    adds nothing to the schema: its tables are rules, which rezono_table writes once the pack's model is read
    (§9.1)."""
    where, line, module = f"{pack_dir.name}/{d.module}", lines(form), form["module"]
    rezono_1 = form["format"] == REZONO_1_FORMAT
    metadata_format = form["format"] in (IDENTIFIER_FORMAT, REZONO_1_FORMAT)

    def refuse(at: str | int, what: str, section: str = "§6") -> None:
        n = at if isinstance(at, int) else line.get(at) or line.get("/".join(at.split("/")[:3])) or 1
        errors.append(f"{where}:{n}: {what} ({PAGE} {section})")

    native_rules = form["format"] in NATIVE_FORMATS
    extended_format = form["format"] in (IDENTIFIER_FORMAT, *NATIVE_FORMATS, REZONO_1_FORMAT)
    for key, message, section in header_errors(
        module, pack, native_rules=native_rules, schema=True,
        form_format=form["format"], pack_version=pack_version,
    ):
        place = key if key.startswith("/") else header_line(pack_dir, d, key)
        refuse(place, message, section)
    pinned = pinned or {}
    used: list[str] = []  # the pinned packs this module imports via `use`, in the order of the lines
    unaliased: set[str] = set()
    prefixes: dict[str, dict[str, list[str]]] = {}  # prefix -> {declared name -> [<pack>:<module>, ...]}
    if not native_rules:
        owners = {name: list(found) for name, found in owners.items()}
        for i, line_ in enumerate(module["use"]):
            at = f"/use/{i}"
            target = line_.get("use") if isinstance(line_, dict) else None
            alias = line_.get("as") if isinstance(line_, dict) else None
            if not isinstance(target, str) or set(line_) - {"use", "as"} or (
                "as" in line_ and not isinstance(alias, str)
            ):
                refuse(at, "not a `use` line of the form")
            elif "." in target:
                if rezono_1:
                    refuse(at, "a `use` line with a dotted pack name is removed in `rezono 1` (R028)")
                else:
                    refuse(at, "a `use` line with a dotted pack name is not lowered yet")
            elif target not in pinned:
                refuse(at, f"{target} is not a pack that pack.yaml pins (R046)")
            elif alias is not None and alias in prefixes:
                refuse(at, f"prefix {alias} is declared twice (R046)")
            else:
                if target not in used:
                    used.append(target)
                if alias is not None:
                    prefixed: dict[str, list[str]] = {}
                    for mid, ns in sorted(pinned[target].items()):
                        for n in ns:
                            prefixed.setdefault(n, []).append(f"{target}:{mid}")
                    prefixes[alias] = prefixed
                elif target not in unaliased:
                    unaliased.add(target)
                    for mid, ns in sorted(pinned[target].items()):
                        for n in ns:
                            owners.setdefault(n, []).append(f"{target}:{mid}")
    own = names(form)
    reasons: list[tuple[str, str]] = []
    seen_reasons: set[str] = set()
    reason_owners = reason_owners or {}
    declared_names = own.keys() | owners.keys()
    uses: set[str] = set()
    enums: dict[str, dict] = {}
    classes: dict[str, dict] = {}
    aliases: dict[str, dict] = {}
    # The slots of each kind of this module, which an inverse slot reads (decisions/language-inverse-references.md).
    kinds: dict[str, list] = {}
    for decl in module["decls"]:
        if isinstance(decl, dict) and isinstance(decl.get("kind"), str):
            kinds.setdefault(decl["kind"], decl.get("slots") or [])
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
            if extended_format and "abstract" in decl:
                abstract = rezono_kind.lower_abstract(decl, at, refuse)
                if abstract is None:
                    continue
                decl, kind_fields = abstract
            keys = {}
            if extended_format and "keys" in decl:
                decl = decl.copy()
                if (keys := rezono_key.lower(decl.pop("keys"), f"{at}/keys", refuse)) is None:
                    continue
            lowered_kind = rezono_kind.lower(
                decl, at, own, owners, declared_names, uses, refuse,
                extended_format=extended_format, aliases=prefixes, kinds=kinds,
                integer_types=integer_types, own_module=d.id, rezono_1=rezono_1,
                layer=d.layer,
            )
            if lowered_kind is not None:
                if keys:
                    lowered_kind["unique_keys"] = keys
                classes[decl["kind"]] = lowered_kind | kind_fields
        elif "enum" in decl:
            lowered_enum = rezono_enum.lower(decl, at, refuse, extended=extended_format)
            if lowered_enum is not None:
                enums[decl["enum"]] = lowered_enum
        elif "rule" in decl and rezono_1:
            refuse(at, "a `rule` declaration is removed in `rezono 1` (R028)")
        elif "rule" in decl and native_rules:
            continue  # The rule assembler needs the checked schema and pinned imports.
        elif "step" in decl:
            if form["format"] not in (SAFE_STEP_FORMAT, REZONO_1_FORMAT):
                refuse(at, "a step declaration requires rezono.module/4 or rezono.module/5", "§6")
            continue  # Step declarations are lowered after native rules and schema resolution.
        elif "extend" in decl:
            rezono_extend.validate(decl, at, imported, refuse, extended_format=extended_format, rezono_1=rezono_1)
        elif "asOf" in decl and extended_format:
            rezono_calc.validate_as_of(decl, at, refuse)
        elif "param" in decl and extended_format:
            rezono_calc.validate_param(decl, at, refuse)
        elif "rules" in decl and rezono_1:
            refuse(at, "a `rules` block is removed in `rezono 1` (R028)")
        elif "rules" in decl and form["format"] == IDENTIFIER_FORMAT:
            from .rezono_relational import valid_block

            if not valid_block(decl):
                refuse(at, "a rules block needs a name and its written lines")
        elif "fact" in decl:
            if "columns" in decl:
                refuse(at, "a fact table is not lowered yet", "§5.3")
            else:
                refuse(at, "a fact row is not lowered (no ticket yet)")
        elif "unit" in decl:
            if unit := rezono_unit.lower(decl, at, refuse):
                aliases[decl["unit"]] = unit
        elif "type" in decl and "base" in decl:
            if not extended_format:
                refuse(at, "a scalar alias requires rezono.module/2", "§5.1")
            elif alias := rezono_alias.lower(decl, at, refuse):
                aliases[decl["type"]] = alias
        elif "reason" in decl:
            code = decl.get("reason")
            elsewhere = [o for o in reason_owners.get(code, []) if o != d.id] if isinstance(code, str) else ()
            lowered_reason = rezono_reason.lower(
                decl, at, refuse,
                seen=seen_reasons,
                elsewhere=elsewhere,
                defined=defined_reasons,
                default_language=default_language,
            )
            if isinstance(code, str) and rezono_reason.CODE.fullmatch(code):
                seen_reasons.add(code)
            if lowered_reason is not None:
                reasons.append(lowered_reason)
        elif "dataset" in decl and form["format"] in (DATASET_FORMAT, REZONO_1_FORMAT) and trailing_dataset(module):
            continue  # The fact loader reads the dataset's tables (decisions/language-library-datasets.md).
        else:
            refuse(at, *next((REFUSED[k] for k in REFUSED if k in decl), ("not a declaration this compiler reads",)))
    if extended_format:
        rezono_calc.validate_module(module["decls"], refuse)
    schema = {"id": f"https://rezono.org/rezono/{pack}/{d.id}", "name": d.id.replace("/", "_"),
              "imports": ["linkml:types"], "default_range": "string", "annotations": {"layer": d.layer},
              "enums": enums, "classes": classes}
    if aliases:
        schema["types"] = aliases
    if metadata_format and "schema" in module:
        range_name = module.get("defaultRange", "Text")
        schema = rezono_metadata.header(
            module, schema, d.layer,
            rezono_slot.builtin_range(range_name, range_name in declared_names), refuse,
        )
    foreign = [f"{u}:{mid}" for u in used for mid in sorted(pinned[u])]
    schema["imports"] += foreign
    return Lowered(d, schema, form, sorted(u for u in uses if u.partition(":")[2] == ""), foreign, reasons)


def view(schema: dict, importmap: dict) -> SchemaView:
    """The SchemaView of a lowered module, its imports resolved through `importmap`."""
    loaded = cast(SchemaDefinition, YAMLLoader().load(schema, target_class=SchemaDefinition))
    return SchemaView(loaded, importmap=importmap)


def schema_classes(pack_dir: Path, rel: str) -> dict:
    """The classes of a compilable pack's module, with ranges from the compiler's name resolution."""
    from . import modules  # The schema loader also calls this module's lowering functions.

    meta = strict_yaml.read(pack_dir / "pack.yaml") or {}
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
    meta = strict_yaml.read(pack_dir / "pack.yaml") or {}
    d = next(d for d in declared(meta, pack_dir, []) if d.module == rel)
    form = effective_form(pack_dir, d, []) or {"module": {"decls": []}}
    return {decl["kind"]: ([] if decl.get("embedded") is True else ["id"])
            + [s["slot"] for s in decl.get("slots") or []]
            for decl in form["module"]["decls"] if isinstance(decl, dict) and "kind" in decl}
