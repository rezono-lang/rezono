"""An unscoped publication with two relations and differing role visibility."""

TRUTH = {"id": "m-1", "snapshots": [
    {"relation": "node", "role": "propose", "complete": False, "full": False},
    {"relation": "node", "role": "auditor", "complete": False, "full": True},
    {"relation": "host", "role": "auditor", "complete": False, "full": True},
    {"relation": "host", "role": "server", "complete": True},
], "checks": [{"name": "a", "status": "green", "violations": 0}, {"name": "b", "status": "warning", "violations": 2}]}
