"""Validate std-view, the example packs and the example fixtures against the contracts, with LinkML.

Usage: python contracts/validate.py   (needs `pip install linkml`)
Checks every file and reports each; exits non-zero when one does not validate.
"""
import functools
import json
import pathlib
import sys

import yaml
from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from linkml_runtime.linkml_model.meta import SchemaDefinition
from linkml_runtime.loaders import yaml_loader

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=None)
def validator(schema):
    """One validator per contract, reused for every instance.

    `linkml.validator.validate` kept about 1.8 MiB per call: over the 5,586 instances of 15-11-2026 the
    process grew to 10.6 GiB, and runner pods of 8 GiB were killed in this step. A reused `Validator` stays
    near 110 MiB and gives the same reports.
    """
    # Built as `linkml.validator.validate` builds its default validator: the schema loaded as a
    # SchemaDefinition (so relative imports resolve from its file), and JSON Schema, closed (an undeclared
    # slot fails).
    definition = yaml_loader.load(str(ROOT / "contracts" / schema), target_class=SchemaDefinition)
    return Validator(definition, validation_plugins=[JsonschemaValidationPlugin(closed=True)])


def module_form_errors(document: object) -> list[str]:
    """Check a module form against its closed LinkML shape and native literal supplement."""
    from rezono_compiler.native_literals import native_literal_errors

    report = validator("rezono-module.yaml").validate(document, "ModuleForm")
    return [result.message for result in report.results] or native_literal_errors(document)


def check(label, instance, schema, target_class):
    report = validator(schema).validate(instance, target_class)
    for result in report.results:
        print(f"FAIL {label}: {result.message}")
    if report.results:
        return False
    print(f"ok   {label} ({target_class})")
    return True


def jobs():
    """Each instance to validate, loaded only when its turn comes, so at most one file is held at a time."""
    view = ROOT / "packs" / "std-view"
    # The Key is palette.yaml and key.yaml together, as the compiler puts it in the bundle.
    yield ("packs/std-view/{palette,key}.yaml", {**load(view / "palette.yaml"), **load(view / "key.yaml")}, "view.yaml", "Key")
    yield ("packs/std-view/sheets.yaml", load(view / "sheets.yaml"), "view.yaml", "Sheets")
    for path in sorted((ROOT / "examples").glob("*/manifests/*.yaml")):
        yield (str(path.relative_to(ROOT)), load(path), "manifest.yaml", "Manifest")
    for path in sorted((ROOT / "examples").glob("*/proofs/*/*.yaml")):
        for i, proof in enumerate(load(path)):
            yield (f"{path.relative_to(ROOT)}[{i}]", proof, "proof.yaml", "Proof")
    # Every example pack at any depth (examples/<use case>/<pack>/ too): its pack files, and its
    # compiled bundle as the compiler wrote it (expected/compiled/).
    for path in sorted((ROOT / "examples").rglob("pack.yaml")):
        yield (str(path.relative_to(ROOT)), load(path), "pack.yaml", "PackMeta")
        channels = path.parent / "channels.yaml"
        if channels.exists():
            yield (str(channels.relative_to(ROOT)), load(channels) or {}, "pack.yaml", "ChannelTable")
    # What the compiler wrote for every example pack, at any depth (examples/**/expected/compiled/): the
    # bundle, and for a pack with rules the rule IR and the pipeline partition, for a pack with calculation
    # rules the bound program; the explained proofs.
    compiled = [("bundle/schema-bundle.json", "bundle.yaml", "Bundle"), ("ir/rules.json", "rules.yaml", "RuleProgram"),
                ("engine/pipelines.json", "pipelines.yaml", "PipelinePlan"), ("ir/calc.json", "calc.yaml", "CalcIR")]
    for name, schema, cls in compiled:
        for path in sorted((ROOT / "examples").glob(f"**/expected/compiled/{name}")):
            yield (str(path.relative_to(ROOT)), json.loads(path.read_text(encoding="utf-8")), schema, cls)
    for path in sorted((ROOT / "examples").glob("**/expected/explained/*/proofs.json")):
        for i, proof in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            yield (f"{path.relative_to(ROOT)}[{i}]", proof, "proof.yaml", "Proof")


def main():
    ok = True
    for job in jobs():
        ok = check(*job) and ok  # every file is checked and reported, as before
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
