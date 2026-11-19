"""Migration equivalence compares the union of checked grounds per conclusion.

See decisions/language-expression-semantics.md, section 4 and the rows `migration-ground-union`
and `migration-changed-ground` in section 6. Every variant below is a hand-written Datalog source
over the same facts. Each one derives the same rows; only its proof graph differs.
"""

import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest
from rezono_publisher import batch as publisher_batch
from support import FIXTURE

from scripts import convert_pack

PAIR = Path(__file__).parent / "fixtures" / "migration-grounds"
ROLES = {"checker": "complete", "viewer": "may_read"}
TIME = "2026-01-01T00:00:00Z"
SOURCE = "rules/derive.dl"


class GroupScopeNotCompared(Exception):
    """The comparator accepted a count whose group scope changed while its contributors did not."""


def build(path, variant):
    directory = path / variant / "minimal"
    shutil.copytree(FIXTURE / "schema", directory / "schema")
    shutil.copyfile(FIXTURE / "channels.yaml", directory / "channels.yaml")
    shutil.copytree(PAIR / "common", directory, dirs_exist_ok=True)
    (directory / "pack.yaml").write_text('name: minimal\nversion: "0"\ndefault_language: en\nimports: []\n',
                                         encoding="utf-8")
    shutil.copyfile(PAIR / variant / "derive.dl", directory / SOURCE)
    position = sha256((directory / SOURCE).read_bytes()).hexdigest()
    return publisher_batch.epoch(directory, epoch=1, knowledge_time=TIME, sources=[("rules", position)])


def key(*parts):
    return json.dumps(parts, separators=(",", ":"))


# The rows every variant derives from facts/base.yaml (a1 and a2 open, a3 closed).
CONCLUSIONS = {
    "mid": {("a1",), ("a2",)},
    "other": {("a1",), ("a2",)},
    "tagged": {("left", "a1"), ("left", "a2"), ("left", "a3")},
    "listed": {("a1",), ("a2",)},
    "unmarked": {("a3",)},
    "total": {("3",)},
}


def meaning(epoch, directory):
    published = convert_pack.read_publication(epoch, directory, ROLES)
    assert {relation: set(published.rows[relation]) for relation in CONCLUSIONS} == CONCLUSIONS
    return published


def rejection(baseline, trial):
    with pytest.raises(convert_pack.ConversionError) as caught:
        convert_pack.compare_publications(baseline, trial, ROLES)
    return str(caught.value)


@pytest.mark.xfail(strict=True, raises=GroupScopeNotCompared, reason=(
    "Make the semantic grounds comparator record the group scope (relation and fixed terms) of every "
    "non-empty aggregate next to its contributor keys, in aggregate_grounds in "
    "checker/rezono_checker/grounds.py; read decisions/language-expression-semantics.md section 4."
))
def test_migration_ground_union(tmp_path):
    baseline = build(tmp_path, "baseline")
    renamed = build(tmp_path, "renamed")
    assert baseline.definition_sha256 != renamed.definition_sha256
    expected = meaning(baseline, tmp_path / "baseline-store")
    observed = meaning(renamed, tmp_path / "renamed-store")
    assert observed.rows == expected.rows

    # Both founded alternatives of listed(a1) contribute. The intermediate row mid(a1) stays a ground,
    # and the renamed source's repeated reads of alpha(a1), mid(a1) and alpha__title(a1, open) collapse.
    union = {("read", "mid", key("a1")), ("read", "alpha", key("a1")), ("read", "alpha__title", key("a1", "open"))}
    assert expected.grounds["listed", key("a1")] == union
    assert observed.grounds["listed", key("a1")] == union
    # The negative premise keeps its relation and exact absent key.
    absent = {("read", "alpha", key("a3")), ("absent", "mid", key("a3"))}
    assert absent <= expected.grounds["unmarked", key("a3")]
    assert absent <= observed.grounds["unmarked", key("a3")]
    # Three distinct contributor keys remain three grounds.
    contributors = {("read", "tagged", key("left", item)) for item in ("a1", "a2", "a3")}
    assert contributors <= expected.grounds["total", key("3")]
    assert contributors <= observed.grounds["total", key("3")]

    # Renamed variables, renumbered clauses and repeated reads with the same grounds pass.
    convert_pack.compare_publications(baseline, renamed, ROLES)

    # Dropping only the intermediate ground mid(a1), or a whole founded alternative, fails.
    for variant in ("dropped-intermediate", "dropped-alternative"):
        trial = build(tmp_path, variant)
        assert meaning(trial, tmp_path / f"{variant}-store").rows == expected.rows
        assert rejection(baseline, trial) == "the candidate changed the grounds for listed [\"a1\"]"

    # Counting tagged(_, _) instead of tagged("left", _) reaches the same three contributors and the
    # same count, but the group scope is a ground of its own.
    widened = build(tmp_path, "widened-scope")
    assert meaning(widened, tmp_path / "widened-store").rows == expected.rows
    try:
        convert_pack.compare_publications(baseline, widened, ROLES)
    except convert_pack.ConversionError as error:
        assert str(error) == "the candidate changed the grounds for total [\"3\"]"
    else:
        raise GroupScopeNotCompared("a changed group scope with equal contributors compared equal")


def test_migration_changed_ground(tmp_path):
    """Positive control: a premise replaced by another relation with the same keys must fail."""
    baseline = build(tmp_path, "baseline")
    substituted = build(tmp_path, "substituted")
    expected = meaning(baseline, tmp_path / "baseline-store")
    observed = meaning(substituted, tmp_path / "substituted-store")
    # Both publications are independently valid and agree on every fact, conclusion, count,
    # typed column, role view and displayed message.
    assert observed.rows == expected.rows
    assert observed.columns == expected.columns
    assert observed.visible == expected.visible
    assert observed.messages == expected.messages
    assert expected.rows["other"] == expected.rows["mid"]
    _, _, displayed, _ = expected.visible["checker"]
    for conclusion, sentence in (("mid", "This item is open."), ("total", "This is the size of the left cohort.")):
        [(kind, text)] = displayed[conclusion, key("a1") if conclusion == "mid" else key("3")]["en"]
        assert kind == "text" and sentence in text
    # listed(a1) now reads other(a1) where it read mid(a1).
    assert ("read", "mid", key("a1")) in expected.grounds["listed", key("a1")]
    assert ("read", "other", key("a1")) in observed.grounds["listed", key("a1")]
    assert rejection(baseline, substituted) == "the candidate changed the grounds for listed [\"a1\"]"
