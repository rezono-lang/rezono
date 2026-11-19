"""Full library acceptance: independent builds for every declared dataset."""

from collections import Counter
from copy import deepcopy
from pathlib import Path
import json
import re
import shutil

import pytest
import yaml

from rezono_compiler import emit, facts, pack
from support import text, violations


LIBRARY = Path(__file__).resolve().parents[3] / "examples/library"
DATASETS = {"valid", "errors"}


def isolated(tmp_path, form):
    directory = tmp_path / form / "library"
    directory.mkdir(parents=True)
    for name in ("channels.yaml", "pack.yaml"):
        shutil.copy(LIBRARY / name, directory / name)
    for name in ("labels", "messages"):
        shutil.copytree(LIBRARY / name, directory / name)
    if form == "legacy":
        for name in ("schema", "facts"):
            shutil.copytree(LIBRARY / name, directory / name)
    else:
        # The candidate stages outside the pack's own rezono/ (decisions/language-library-acceptance.md).
        authored = LIBRARY / "candidate"
        modules = ["library", *sorted(DATASETS)]
        for name in modules:
            for suffix in ("rezono", "json"):
                assert (authored / f"{name}.{suffix}").is_file(), f"missing {name}.{suffix}"
        shutil.copytree(authored, directory / "rezono")
        meta_path = directory / "pack.yaml"
        meta = yaml.safe_load(meta_path.read_bytes())
        meta["rezono"] = [
            {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "facts"} for name in modules
        ]
        meta_path.write_text(yaml.safe_dump(meta), encoding="utf-8")
    return directory


def local_line(directory, span):
    source = (directory / span["file"]).resolve()
    assert source.is_relative_to(directory.resolve())
    lines = source.read_text(encoding="utf-8").splitlines()
    line, column = int(span["line"]), int(span["column"])
    assert 1 <= line <= len(lines) and 1 <= column <= len(lines[line - 1])
    return lines[line - 1][column - 1:]


def semantic_bundle(directory, published, form):
    bundle = deepcopy(published)
    source = "schema/library.yaml" if form == "legacy" else "rezono/library.rezono"
    [schema] = bundle["schemas"]
    assert schema.pop("file") == source
    source_lines = (directory / source).read_text(encoding="utf-8").splitlines()
    owners = {}
    current_kind = None
    for number, line in enumerate(source_lines, 1):
        if form == "legacy":
            declaration = re.fullmatch(r"  ([A-Z]\w*):", line)
        else:
            declaration = re.match(r"(?:(?:abstract|embedded) )?kind (\w+)\b", line)
        if declaration:
            current_kind = declaration[1]
        owners[number] = current_kind
    named_classes = {item["id"]: item["class"] for item in bundle["kinds"]}
    for group in ("kinds", "arrows", "attributes", "unique_keys", "path_equations"):
        for item in bundle[group]:
            name = item.get("class") if group == "kinds" else item["id"].split(".")[-1]
            for owner in (item, item.get("sentence", {})):
                if owner is item and group in ("unique_keys", "path_equations"):
                    continue
                if not owner:
                    continue
                span = owner.pop("span")
                assert span["file"] == source
                kind_id = item["id"].split(".")[0]
                assert owners[int(span["line"])] == named_classes[kind_id]
                tail = local_line(directory, span)
                # The legacy path-equation anchor is on its name key in the annotated YAML sequence.
                if form == "legacy" and group == "path_equations":
                    assert re.match(rf"name:\s*{re.escape(name)}\b", tail)
                else:
                    assert re.match(rf"{re.escape(name)}\b", tail), (group, name, tail)
    for entry in bundle["channels"]["sources"]:
        span = entry.pop("span")
        assert span["file"] == "channels.yaml"
        kind, element = entry["id"].split("/", 1)
        assert yaml.safe_load(local_line(directory, span))[{"kinds": "kind", "arrows": "arrow"}[kind]] == element
    return bundle


def witness(rows, loan):
    def target(relation, subject):
        [value] = [value for key, value in rows[relation] if key == subject]
        return value
    copy = target("loan__copy", loan)
    staff = target("loan__lent_by", loan)
    return copy, target("copy__branch", copy), staff, target("staff__branch", staff)


def check_example(directory, form):
    model = pack.read(directory)
    files = emit.compile_pack(model)
    bundle = semantic_bundle(directory, json.loads(files["bundle/schema-bundle.json"]), form)
    assert {"format", "pack", "kinds", "arrows", "attributes", "checks", "pages", "labels", "messages", "channels"} <= bundle.keys()
    assert bundle["rules"] == []
    assert any(page["kind"] == "loan" for page in bundle["pages"])
    assert any(label["element"] == "address" and label["text"] == "adres" for label in bundle["labels"])
    [equation] = bundle["path_equations"]
    assert (equation["id"], equation["left"], equation["right"]) == (
        "loan.lent_at_home", ["copy", "branch"], ["lent_by", "branch"],
    )
    datasets = facts.files(directory)
    assert Counter(p.stem for p in datasets) == Counter(sorted(DATASETS))
    results = {}
    for path in datasets:
        rows = facts.load(model, path)
        findings = violations(files, rows)
        expected = json.loads((LIBRARY / "expected/violations" / f"{path.stem}.json").read_text(encoding="utf-8"))
        assert findings == text({name: {tuple(row) for row in matches} for name, matches in expected.items()})
        loan, known = (
            ("l2", (1002, "oost", "s2", "oost")) if path.stem == "valid"
            else ("l3", (1003, "centrum", "s2", "oost"))
        )
        assert witness(rows, loan) == known
        authored = path if form == "legacy" else directory / "rezono" / f"{path.stem}.rezono"
        lines = authored.read_text(encoding="utf-8").splitlines()
        if form == "legacy":
            [row] = [line for line in lines if re.search(rf"\bid:\s*{loan}\b", line)]
            assert yaml.safe_load(row)[0]["copy"] == known[0]
        else:
            candidate = json.loads(authored.with_suffix(".json").read_text(encoding="utf-8"))
            [dataset] = [d for d in candidate["module"]["decls"] if d.get("dataset") == path.stem]
            [table] = [d for d in dataset["decls"] if d.get("fact", "").lower() == "loan"]
            identity = table["columns"].index("id")
            copy_column = table["columns"].index("copy")
            in_loans = False
            matches = []
            for line in lines:
                if line.strip().startswith("fact "):
                    in_loans = line.strip().lower() == "fact loan"
                if in_loans and line.strip().startswith("|"):
                    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                    if cells[identity] == loan:
                        matches.append(cells[copy_column])
            assert matches == [str(known[0])]
        results[path.stem] = (rows, findings)
    return bundle, results


def test_authored_library_has_expected_states(tmp_path):
    check_example(isolated(tmp_path, "legacy"), "legacy")


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="M3: decisions/language-library-acceptance.md: Stage the complete library migration in examples/library/candidate/ (library, valid and errors, each .rezono with its form), not in examples/library/rezono/. Waits for library schema lowering, named typed datasets, source validation and discovery, and the conditional-rule and metadata constructs. The authored modules also need a dataset name in backticks (valid is a keyword), placed list and record cells, and a list cell in a single-valued slot.")
def test_whole_library_has_the_same_meaning(tmp_path):
    expected = check_example(isolated(tmp_path, "legacy"), "legacy")
    actual = check_example(isolated(tmp_path, "rezono"), "rezono")
    assert actual == expected
