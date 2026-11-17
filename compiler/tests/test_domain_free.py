"""The core holds no domain knowledge (AGENTS.md rule 1, decision S4).

Names that only an example can give, such as a use case, a pack name with a hyphen, a compound kind name, or a
compound id of a role the example's facts name (a domain role, which the core reaches only through the generic
capabilities of std-access; roles in two layers, B19), must not appear in the code of the compiler, the checker, the viewer, the publisher or the gate, nor in
the compiler's own tests: a test that fixes one example's names lives with that example (RV-M08). Single words
such as `plan` or `rule` are also ordinary programming words, so they are not checked.
"""

import re
from pathlib import Path

import yaml

from rede_compiler.pack import snake

ROOT = Path(__file__).resolve().parents[2]
CORE = [ROOT / "compiler" / "rede_compiler", ROOT / "checker" / "rede_checker", ROOT / "viewer" / "src",
        ROOT / "edge" / "publisher" / "rede_publisher", ROOT / "edge" / "gate" / "src", ROOT / "compiler" / "tests"]
SUFFIXES = {".py", ".ts", ".svelte", ".js"}
# Names the engine itself gives meaning to, so an example uses them by design: the closing fact of a seal
# (decision E3, docs/compiler.md#design-m3-the-seal).
ENGINE = {"period_close"}
# One line on purpose, by the start of its text: the Catlab oracle's one real pack (test_catlab.py reads it through
# test_operate.py). catlab.yml runs compiler/tests/test_catlab.py alone with Julia, so the sample stays there
# until that workflow also runs a case from the example; every other line of these files is scanned.
SAMPLE = {"compiler/tests/test_operate.py": "STEEL_THREAD = REPO / "}
ENTRY_TEXT = re.compile(r"^[a-z][a-z0-9_.]*\s*=\s*")


def vocabulary() -> set[str]:
    terms: set[str] = set()
    for meta in (ROOT / "examples").rglob("pack.yaml"):
        if "expected" in meta.parts:
            continue
        name = str((yaml.safe_load(meta.read_text(encoding="utf-8")) or {}).get("name", ""))
        if "-" in name:
            terms.add(name)
        if meta.parent.parent != ROOT / "examples":  # examples/<use case>/<pack>/
            terms.add(meta.parent.parent.name)
        for schema in sorted((meta.parent / "schema").glob("*.yaml")):
            classes = (yaml.safe_load(schema.read_text(encoding="utf-8")) or {}).get("classes") or {}
            terms |= {snake(c) for c in classes if "_" in snake(c)}
        terms |= roles(meta.parent)
    return terms - ENGINE


def roles(pack: Path) -> set[str]:
    """The compound ids of the roles a pack's facts name (kind `role` of std-access)."""
    out = set()
    for facts in sorted(pack.glob("**/facts/*.yaml")):
        if "expected" in facts.relative_to(pack).parts:
            continue
        rows = (yaml.safe_load(facts.read_text(encoding="utf-8")) or {})
        for row in (rows.get("role") or []) if isinstance(rows, dict) else []:
            ident = str(row.get("id", "")) if isinstance(row, dict) else ""
            if "_" in ident or "-" in ident:
                out.add(ident)
    return out


def test_the_vocabulary_names_domain_roles():
    assert any(roles(meta.parent) for meta in (ROOT / "examples").rglob("pack.yaml")), "no domain role found"


def core_files():
    for root in CORE:
        for path in sorted(root.rglob("*")):
            if path.suffix in SUFFIXES and ".test." not in path.name and "node_modules" not in path.parts:
                yield path


def test_the_vocabulary_is_not_empty():
    assert vocabulary(), "no example packs found"


def test_no_example_name_in_the_core():
    pattern = re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(sorted(map(re.escape, vocabulary()))) + r")(?![A-Za-z0-9_-])",
                         re.IGNORECASE)
    hits = [f"{p.relative_to(ROOT)}:{n}: {m.group(1)}"
            for p in core_files()
            for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1)
            if not line.startswith(SAMPLE.get(p.relative_to(ROOT).as_posix(), "\0"))
            for m in [pattern.search(line)] if m]
    assert not hits, "domain names in the core (move them to a pack or examples/):\n" + "\n".join(hits)


def test_standard_schemas_and_messages_have_no_domain_words():
    # These are owner-supplied vocabulary examples, not compiler semantics.
    terms = ("uitval", "cluster", "boeking", "artikel", "belasting", "zone", "product")
    pattern = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(terms) + r")(?![A-Za-z0-9])", re.IGNORECASE)
    files = sorted({path for pack in (ROOT / "packs").glob("std-*")
                    for glob in ("schema/**/*.yaml", "messages/*.mf2") for path in pack.glob(glob)})
    assert files, "no standard schemas or messages found"
    hits = [f"{path.relative_to(ROOT)}:{n}: {match.group()}"
            for path in files
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            # MF2 entry ids are stable keys (map.cluster is a neutral grouping); scan their message text.
            for content in [ENTRY_TEXT.sub("", line) if path.suffix == ".mf2" else line]
            for match in pattern.finditer(content)]
    assert not hits, "domain words in standard schemas/messages:\n" + "\n".join(hits)
