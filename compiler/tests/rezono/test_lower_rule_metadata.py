"""Rule annotations in a relational block must mean what they mean in the same Datalog file."""

import json
from pathlib import Path
import shutil

from rezono_compiler import emit, pack, rules
from support import FIXTURE
from test_rezono_module import declare


LINES = [
    ".decl listed(item: symbol)",
    "// @explain fold",
    ".decl staged(item: symbol)",
    "staged(x) :- alpha(x).",
    "listed(x) :- staged(x).",
    "// @explain on_demand",
    ".decl paired(left: symbol, right: symbol)",
    "paired(x, y) :- alpha(x), alpha(y).",
    ".output listed",
    ".output paired",
]


def written(tmp_path, form):
    directory = Path(shutil.copytree(FIXTURE, tmp_path / form / "minimal"))
    with (directory / "labels/nl.yaml").open("a", encoding="utf-8") as labels:
        labels.write("\nlisted: opgenomen\npaired: gepaard\n")
    with (directory / "messages/nl.mf2").open("a", encoding="utf-8") as messages:
        messages.write("\nrule.listed = {{Dit item is opgenomen.}}\nrule.paired = {{Deze items zijn gepaard.}}\n")
    if form == "datalog":
        (directory / "rules").mkdir()
        (directory / "rules/eligibility.dl").write_text("\n".join(LINES) + "\n", encoding="utf-8")
        return directory
    (directory / "rezono").mkdir()
    text = "rezono 0\npack minimal\nrules eligibility\n" + "".join(f"  | {line}\n" for line in LINES)
    (directory / "rezono/eligibility.rezono").write_text(text, encoding="utf-8")
    form_doc = {"format": "rezono.module/2", "spans": [{"at": "/decls/0", "line": "3", "start": "28", "end": "39"}],
                "module": {"rezono": "0", "pack": "minimal", "use": [],
                           "decls": [{"rules": "eligibility", "lines": LINES}]}}
    (directory / "rezono/eligibility.json").write_text(json.dumps(form_doc), encoding="utf-8")
    declare(directory, [{"module": "rezono/eligibility.rezono", "form": "rezono/eligibility.json", "layer": "facts"}])
    return directory


def meaning(directory):
    model = pack.read(directory)
    bundle = emit.bundle(model, [], rules.load(model.rules))
    modes = {relation["id"]: relation.get("explain") for relation in bundle["relations"]
             if relation["id"] in {"listed", "staged", "paired"}}
    return sorted(model.folds), modes


def test_lower_rule_metadata(tmp_path):
    expected = meaning(written(tmp_path, "datalog"))
    # The annotations in the Datalog file are the oracle: a fold helper and an on-demand relation.
    assert expected[0] == ["staged"]
    assert expected[1]["paired"] == "on_demand"
    assert meaning(written(tmp_path, "rezono")) == expected
