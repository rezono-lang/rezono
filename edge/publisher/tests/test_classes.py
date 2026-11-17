"""SO-5: a pack says what it is, a profile says what it carries, and the publisher refuses a mismatch before it
computes or writes anything. The check knows no class by name (an invented class shows it), and every profile in
the repository carries every pack it lists: this test is the per-pull-request check."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rede_publisher import __main__ as cli, classes

ROOT = Path(__file__).resolve().parents[3]
PROFILES = sorted((ROOT / "deploy" / "profiles").glob("*.yaml"))


def pack(tmp_path: Path, cls: str | None) -> Path:
    d = tmp_path / "pack"
    d.mkdir()
    meta = {"name": "p", "version": "0.1.0", "default_language": "en"} | ({"class": cls} if cls else {})
    (d / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    return d


def profile(tmp_path: Path, listed: list[str] | None) -> Path:
    p = tmp_path / "profile.yaml"
    body = {"storage": {"url": (tmp_path / "store").as_uri()}, "access": {"roles": {"viewer": "may_read"}}}
    if listed is not None:
        body["publish"] = {"classes": listed}
    p.write_text(yaml.safe_dump(body), encoding="utf-8")
    return p


@pytest.mark.parametrize("profile_path", PROFILES, ids=[p.name for p in PROFILES])
def test_every_profile_carries_every_pack_it_lists(profile_path):
    assert classes.check(profile_path, ROOT) == []


def test_an_invented_class_is_carried_only_where_it_is_listed(tmp_path):
    d = pack(tmp_path, "quokka-grade")
    assert classes.pack_class(d) == "quokka-grade"
    assert classes.refusal(d, {"publish": {"classes": ["quokka-grade"]}}, "a.yaml") is None
    reason = classes.refusal(d, {"publish": {"classes": ["unclassified"]}}, "b.yaml")
    assert "'quokka-grade'" in reason and "b.yaml" in reason and "unclassified" in reason


def test_no_class_is_unclassified_and_must_be_listed(tmp_path):
    d = pack(tmp_path, None)
    assert classes.pack_class(d) == classes.UNCLASSIFIED
    assert classes.refusal(d, {"publish": {"classes": ["unclassified"]}}, "a.yaml") is None
    assert "unclassified" in classes.refusal(d, {"publish": {"classes": ["security"]}}, "a.yaml")


def test_a_profile_without_a_list_carries_nothing(tmp_path):
    reason = classes.refusal(pack(tmp_path, None), {"publish": {"packs": ["x"]}}, "a.yaml")
    assert "carries nothing" in reason


def test_a_misspelt_class_fails_closed(tmp_path):
    assert classes.refusal(pack(tmp_path, "securty"), {"publish": {"classes": ["security", "unclassified"]}}, "a.yaml")


def test_the_check_reads_published_and_live_packs(tmp_path):
    pack(tmp_path, "secret-ish")
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump({"publish": {"classes": ["unclassified"]}, "live": {"packs": ["pack"]}}), encoding="utf-8")
    (reason,) = classes.check(p, tmp_path)
    assert "secret-ish" in reason
    assert classes.main([]) == 1


def test_the_publisher_refuses_before_it_opens_the_store(tmp_path, capsys):
    d = pack(tmp_path, "quokka-grade")
    code = cli.main([str(d), "--profile", str(profile(tmp_path, ["unclassified"])), "--epoch", "1",
                     "--knowledge-time", "2026-11-11T00:00:00+00:00"])
    assert code == 2
    assert "blocked:" in capsys.readouterr().err
    assert not (tmp_path / "store").exists(), "nothing is written for a refused pack"


def test_the_code_names_no_class_but_unclassified():
    source = (ROOT / "edge" / "publisher" / "rede_publisher" / "classes.py").read_text(encoding="utf-8")
    assert "security" not in source
