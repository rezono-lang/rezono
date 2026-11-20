"""Path equations in the reference platform schema reject cross-product pins and cross-cluster worker nodes."""

from pathlib import Path

from rezono_compiler import scenarios
from support import violations

PLATFORM = Path(__file__).resolve().parent


def _main_rows(model):
    states = scenarios.fact_states(model, PLATFORM, diagnostics=False)
    rows, = [rows for kind, _, _, rows in states if kind == "facts"]
    return {table: list(values) for table, values in rows.items()}


def test_pin_same_product_path_equation_rejects_mismatched_release(committed_packs):
    compiled = committed_packs.compiled(PLATFORM)
    rows = _main_rows(committed_packs.model(PLATFORM))
    assert violations(compiled, rows) == {}

    rows["pin"].append(("pin-wrong-product",))
    rows["pin__service"].append(("pin-wrong-product", "reg"))
    rows["pin__release"].append(("pin-wrong-product", "postgresql-16"))
    assert violations(compiled, rows) == {
        "pin__same_product__path_equation": {("pin-wrong-product", "registry <> postgresql")},
    }


def test_cluster_worker_node_same_cluster_path_equation_rejects_foreign_endpoint(committed_packs):
    compiled = committed_packs.compiled(PLATFORM)
    rows = _main_rows(committed_packs.model(PLATFORM))
    assert violations(compiled, rows) == {}

    rows["cluster_worker_node"].append(("node-wrong-cluster",))
    rows["cluster_worker_node__owner"].append(("node-wrong-cluster", "production"))
    rows["cluster_worker_node__endpoint"].append(("node-wrong-cluster", "workers-development"))
    assert violations(compiled, rows) == {
        "cluster_worker_node__same_cluster__path_equation": {
            ("node-wrong-cluster", "development <> production"),
        },
    }
