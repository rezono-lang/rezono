"""RV-K10: the Soufflé oracle on a pack's source reads the import closure (tests/souffle.py, decision S28).

An imported pack brings its rules, and the program is the union over the import closure. So the oracle's
program is the rule text as written, of the pack and of every pack it imports, the imported text under the
importing pack's names. The tests of the text need no Soufflé. The last one runs it (in CI, where Soufflé is
installed): the union equals what the batch backend derives, and a planted difference in an imported rule
does not.
"""

import re
import shutil

import pytest
import yaml

import souffle
from rezono_compiler import batch, pack
from rezono_compiler import rules as ir
from rezono_compiler.rules_dl import parse_file, remap_statement
from test_rule_imports import imported, pin, program, write_rules  # noqa: F401 (imported is a fixture)

REGISTERED = "registered(x) :- party(x)."  # the rule of the imported pack (the fixture `imported`)
MISSING = ".decl missing(x: symbol)\nmissing(x) :- alpha(x), !registered(x).\n"
MAY_READ = ".decl may_read(r: symbol, k: symbol, x: symbol)\n"


def decls(text: str) -> list[str]:
    return re.findall(r"^\.decl\s+([a-z0-9_]+)", text, flags=re.M)


def test_the_source_is_the_union_over_the_import_closure(imported):
    _, consumer = imported
    write_rules(consumer, MISSING)
    prog = program(consumer)
    text = souffle.pack_source(prog, consumer)
    assert REGISTERED in text and "missing(x) :- alpha(x), !registered(x)." in text
    assert sorted(decls(text)) == sorted(prog.relations), "every relation of the program is declared once"
    # What RV-K10 found: the pack's own files alone leave the imported relation without a declaration.
    assert "registered" not in decls(souffle.source(prog, [(consumer / "rules" / "core.dl").read_text()]))


def test_a_pack_reached_twice_brings_its_rules_once(imported, tmp_path):
    owner, consumer = imported
    middle = tmp_path / "middle"
    (middle / "schema").mkdir(parents=True)
    (middle / "pack.yaml").write_text("name: middle\nversion: 0.1.0\ndefault_language: nl\n")
    (middle / "schema" / "empty.yaml").write_text(
        "id: https://rezono.example/empty\nname: empty\nimports: [linkml:types]\n")
    write_rules(middle, ".decl known(x: symbol)\nknown(x) :- registered(x).\n")
    pin(middle, owner)
    pin(consumer, middle, owner)
    text = souffle.pack_source(program(consumer), consumer)
    assert text.count(REGISTERED) == 1
    assert text.index(REGISTERED) < text.index("known(x) :- registered(x)."), "a pack after the packs it imports"


def test_an_extension_declared_again_is_declared_once(imported):
    """An importing pack repeats the declaration of an imported `@extend` relation (every pack with read
    rules does, for std-access's may_read). Soufflé refuses a relation declared twice."""
    owner, consumer = imported
    write_rules(owner, "// @extend\n" + MAY_READ)
    pin(consumer, owner)
    grant = 'may_read("reader", "alpha", x) :- alpha(x).'
    write_rules(consumer, MAY_READ + grant + "\n", "access")
    text = souffle.pack_source(program(consumer), consumer)
    assert decls(text).count("may_read") == 1 and grant in text


@pytest.mark.parametrize("texts", [
    [".decl registered(x: symbol)\n", ".decl registered(x: number)\n"],  # other columns
    [".decl registered(x: symbol)\n.decl registered(x: symbol)\n"],  # twice in one file
], ids=["other-columns", "one-file"])
def test_any_other_second_declaration_is_left_for_souffle_to_refuse(imported, texts):
    prog = program(imported[1])
    assert decls(souffle.source(prog, texts)).count("registered") == 2


def clash(consumer):
    """The consumer gets a class of its own with the name of the owner's: the owner's is then another table."""
    f = consumer / "schema" / "minimal.yaml"
    doc = yaml.safe_load(f.read_text())
    doc["classes"]["Party"] = {"attributes": {"id": {"identifier": True}}}
    f.write_text(yaml.safe_dump(doc))


def test_imported_text_is_bound_to_the_importing_names(imported):
    owner, consumer = imported
    clash(consumer)
    write_rules(owner, "// @extend\n" + MAY_READ + 'may_read("reader", "party", x) :- party__grade(x, "plain").\n')
    pin(consumer, owner)
    prog = program(consumer)
    text = souffle.pack_source(prog, consumer)
    assert ('may_read("reader", "shared_terms_terms_party", x) :- shared_terms_terms_party__grade(x, "plain").'
            in text)
    assert sorted(decls(text)) == sorted(prog.relations)
    rule = prog.rules["may_read"]  # the compiler bound the same names
    assert (rule.head.terms[1], rule.body[0].atom.relation) == ("shared_terms_terms_party",
                                                                "shared_terms_terms_party__grade")


NAMES = {"party": "terms_party", "grade": "grade"}
# (as written in the imported pack, under the importing names; None: unchanged)
BOUND = {
    "a relation and its slot table": ('seen(x) :- party(x), !party__grade(x, "plain").',
                                      'seen(x) :- terms_party(x), !terms_party__grade(x, "plain").'),
    "a value is no kind": ('seen(x) :- party__grade(x, "party").', 'seen(x) :- terms_party__grade(x, "party").'),
    "the kind of an access atom": ('may_read("reader", "party", x) :- party(x).',
                                   'may_read("reader", "terms_party", x) :- terms_party(x).'),
    "a kind compared with a variable": ('may_read(r, k, x) :- grant(r, k, x), k = "party".',
                                        'may_read(r, k, x) :- grant(r, k, x), k = "terms_party".'),
    "through an equality of variables": ('may_read(r, k, x) :- grant(r, j, x), "party" = j, j = k.',
                                         'may_read(r, k, x) :- grant(r, j, x), "terms_party" = j, j = k.'),
    "any comparison with that variable": ('may_read(r, k, x) :- grant(r, k, x), k != "party", "party" <= k.',
                                          'may_read(r, k, x) :- grant(r, k, x), k != "terms_party", "terms_party" <= k.'),
    "an inequality of variables is no alias": ('may_read(r, k, x) :- grant(r, k, j), k != j, j = "party".', None),
    "an unnamed kind column": ('seen(x) :- may_read(x, _, "party").', None),
    "a variable of that name": ('may_read(r, "role", party) :- role(r), role(party), party != "party".', None),
    "the next rule has its own variables": ('may_read(r, k, x) :- grant(r, k, x).\nseen(k) :- grade(k), k = "party".',
                                            None),
    "a declaration and a comment": ('// party(x) reads "party"\n.decl seen(party: symbol)\nseen(x) :- role(x).', None),
    "a declaration of the access relation": (MAY_READ + 'seen(k) :- role(k), k = "party".', None),
    "an aggregate": ("busy(x, n) :- role(x), n = count : { party__grade(_, x) }.",
                     "busy(x, n) :- role(x), n = count : { terms_party__grade(_, x) }."),
}


@pytest.mark.parametrize("case", list(BOUND))
def test_bound_rewrites_relations_and_access_kinds_and_nothing_else(case):
    written, want = BOUND[case]
    got = souffle.bound(written, NAMES)
    assert got == (written if want is None else want)
    # And it is the compiler's binding: the rewritten text parses to the statements the compiler remaps to.
    assert parse_file(got, "rules/x.dl") == [remap_statement(s, NAMES) for s in parse_file(written, "rules/x.dl")]


def test_bound_leaves_text_alone_when_no_name_differs():
    text = "// anything  at all\nseen(x) :- party(x) .\n"
    assert souffle.bound(text, {"party": "party"}) is text


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_the_union_on_souffle_equals_the_batch_backend_and_a_planted_difference_does_not(imported, tmp_path):
    """The owner's table is bound to another name here (`clash`), and the consumer's rule negates the
    imported relation, so a wrong binding, a missing imported rule and a changed one all show."""
    owner, consumer = imported
    clash(consumer)
    write_rules(consumer, MISSING)
    prog = ir.load(pack.read(consumer).rules)
    party = prog.rules["registered"].body[0].atom.relation
    data = {party: [("a",)], "alpha": [("a",), ("b",)]}
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    derived = batch.read(con, prog)
    assert derived["missing"] == {("b",)}
    texts = souffle.closure(consumer)
    assert souffle.run(prog, data, tmp_path, program_text=souffle.source(prog, texts)) == derived
    # Planted: the imported rule as Soufflé reads it leaves out the one party; the compiled one is unchanged.
    # (Only relations of the compiled program are declared, so the planted rule reads no other table.)
    planted = [t.replace(f"registered(x) :- {party}(x).", f'registered(x) :- {party}(x), x != "a".') for t in texts]
    assert planted != texts
    got = souffle.run(prog, data, tmp_path, program_text=souffle.source(prog, planted))
    assert got != derived and got["missing"] == {("a",), ("b",)}
