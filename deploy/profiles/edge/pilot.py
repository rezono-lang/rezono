"""Validate edge pilot results against the publication manifest."""


def reads_all_in_full(manifest: dict, role: str) -> bool:
    """Check a role's full coverage against all relations in the unscoped manifest."""
    snapshots = manifest.get("snapshots", [])
    relations = {snapshot["relation"] for snapshot in snapshots}
    full = {
        snapshot["relation"]
        for snapshot in snapshots
        if snapshot["role"] == role
        and (snapshot.get("full") is True or snapshot.get("complete") is True)
    }
    return bool(relations) and full == relations
