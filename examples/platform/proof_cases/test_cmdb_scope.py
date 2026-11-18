"""Compare a mapped inventory export with placements already derived from platform facts."""
import hashlib
import json
import shutil
import subprocess
import sys

import pytest
import yaml

from case_support import ROOT, engine, verified
from rezono_compiler import sources
from rules_support import states


PLACED = {"user": "edge", "lb": "edge", "idp": "base", "dns": "base"}


class MissingReferenceImport(Exception):
    pass


def compare(reported, scoped):
    wrong = {(s, c, reported[s]) for s, c in PLACED.items() if s in reported and c != reported[s]}
    absent = {s for s in PLACED if s not in reported and s in scoped}
    unknown = PLACED.keys() - reported.keys() - scoped
    return wrong, absent, unknown


def test_fixture_matches_real_domain_placements_without_a_cmdb():
    model, baseline = engine()
    assert set(PLACED.items()) <= baseline.derived["cluster_service_placement"]
    assert compare({"user":"edge", "lb":"storage"}, {"user","idp"}) == (
        {("lb","edge","storage")}, {"idp"}, {"dns"})
    assert ("cluster_service_binding__service", ("idp","idp")) in verified(
        "cluster_service_placement", ("idp","base"), state=(model,baseline))


def test_mapped_cmdb_scope_does_not_write_domain_placements(tmp_path):
    # The only inbound data is a source-system JSON export. The test never writes normalized reference rows.
    cli = ROOT / "portal" / "import_cmdb.py"
    template = ROOT / "reference" / "cmdb-import.yaml"
    if not (cli.is_file() and template.is_file()):
        raise MissingReferenceImport("mapped CMDB intake and reference/cmdb-import.yaml")
    _, baseline = engine()
    derived = baseline.derived["cluster_service_placement"]
    shutil.copytree(ROOT.parents[1] / "packs", tmp_path / "packs")
    for n, (alias, scope, target) in enumerate([
            ("location", ["user","idp"], "storage"), ("wherePlaced", ["user"], "storage"),
            ("wherePlaced", ["user","idp"], "edge")]):
        dest = tmp_path / f"world{n}" / "platform"
        shutil.copytree(ROOT, dest)
        mapping = yaml.safe_load(template.read_text(encoding="utf-8"))
        mapping["placement_fields"]["cluster"] = alias
        mapping_file = dest / "reference" / "cmdb-import.yaml"
        mapping_file.write_text(yaml.safe_dump(mapping), encoding="utf-8")
        doc = {"export": "spring", "observations": [{"workload": "user", alias: "edge"},
                      {"workload": "lb", alias: target}], "complete_services": scope}
        if alias != "location":
            for record in doc["observations"]:
                record["location"] = "decoy"
        path = tmp_path / f"spring-{n}.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        other = tmp_path / f"other-{n}.json"
        other.write_text(json.dumps({"export":"previous","observations":[],"complete_services":["idp","dns"]}))
        for source in (other,path):
            subprocess.run([sys.executable,str(cli),"--pack",str(dest),"--mapping",str(mapping_file),
                            "--source",str(source)],check=True)
        model, prog, snapshots = states(dest)
        state = snapshots[0]
        assert state.derived["cluster_service_placement"] == derived
        independent = compare({r["workload"]:r[alias] for r in doc["observations"]},set(scope))
        outcomes = (("cmdb_mismatch",independent[0]),("cmdb_missing",{(s,) for s in independent[1]}),
                    ("cmdb_unknown",{(s,) for s in independent[2]}))
        for rel, expected in outcomes:
            assert not prog.reaches("cmdb_observation", "cluster_service_placement")
            actual = {row[1:] for row in state.derived[rel] if row[0]=="spring" and row[1] in PLACED}
            assert actual == expected
        # Reference content, its scope and the domain service are separately owned and separately sourced.
        import_dir = dest / "schema" / "cmdb_reference"
        classes = {k for file in import_dir.glob("*.yaml") for k in yaml.safe_load(file.read_text())["classes"]}
        assert {"CmdbObservation","CmdbScope"} <= classes
        assert not {"Service","Cluster","ClusterServiceBinding"} & classes
        index = {(e["row"]["relation"],tuple(json.loads(e["row"]["key"]))):e["sources"]
                 for e in sources.read(model,dest)}
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for rel, wanted in outcomes[:2]:
            for item in wanted:
                leaves = verified(rel, ("spring",*item), state=(model,state))
                assert ("cluster_service_binding__service",(item[0],item[0])) in leaves
                ref = "cmdb_observation__cluster" if rel=="cmdb_mismatch" else "cmdb_scope__service"
                pointer = "/observations/1" if rel=="cmdb_mismatch" else "/complete_services/1"
                assert any(src["name"]==path.name and src["revision"]==digest and src["position"]==pointer
                           for leaf in leaves if leaf[0]==ref for src in index[leaf])
