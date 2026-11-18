"""Discover declared data modules through the compiler entry point used by publication."""

import json

import pytest
import yaml

from rezono_compiler import facts


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Discover declared datasets through facts.files in compiler/rezono_compiler/facts.py. Read decisions/language-library-datasets.md. Waits for test_scalar_dataset_rows (shared facts.py).")
def test_named_dataset_discovery(tmp_path):
    source = tmp_path / "rezono"
    source.mkdir()
    manifest = []
    for name in ("valid", "errors", "schema", "unlisted"):
        decls = [] if name == "schema" else [{"dataset": name, "decls": []}]
        form = {"format": "rezono.module/2", "spans": [], "module": {
            "rezono": "0", "pack": "library", "use": [], "decls": decls,
        }}
        (source / f"{name}.json").write_text(json.dumps(form), encoding="utf-8")
        text = "rezono 0\npack library\n"
        if decls:
            text += f"dataset {name}\n"
        (source / f"{name}.rezono").write_text(text, encoding="utf-8")
        if name != "unlisted":
            manifest.append({"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "facts"})
    meta = {"name": "library", "version": "0.1.0", "imports": [], "rezono": manifest}
    (tmp_path / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    assert sorted(facts.files(tmp_path)) == [source / "errors.json", source / "valid.json"]

    path = source / "valid.json"
    wrong = json.loads(path.read_bytes())
    wrong["module"]["decls"][0]["dataset"] = "alternate"
    path.write_text(json.dumps(wrong), encoding="utf-8")
    (source / "valid.rezono").write_text("rezono 0\npack library\ndataset alternate\n", encoding="utf-8")
    with pytest.raises(facts.LoadError) as caught:
        facts.files(tmp_path)
    assert "valid" in str(caught.value) and "alternate" in str(caught.value)
