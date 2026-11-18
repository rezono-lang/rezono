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


def asked(gate, role: str, pack: str, manifest: str, question: str) -> list[dict]:
    """Read all pages of one typed question from a role-scoped gate."""
    path = f"/{pack}/{manifest}/ask"
    headers = {"Content-Type": "application/json"}
    pages = []
    identity = None
    seen = set()
    body = {"ask": question}
    while True:
        status, answer = gate.call(path, method="POST", body=body, headers=headers)
        if status != 200 or not isinstance(answer, dict):
            raise SystemExit(f"{role} ask: expected a successful answer page")
        if (answer.get("format") != "rezono.answer/1" or answer.get("question") != "ask"
                or answer.get("manifest_id") != manifest):
            raise SystemExit(f"{role} ask: answer format, question or manifest mismatch")

        expression, dataset = answer.get("expression"), answer.get("dataset")
        if not isinstance(expression, dict) or expression.get("text") != question:
            raise SystemExit(f"{role} ask: answer expression mismatch")
        schema, expression_hash = answer.get("output_schema"), expression.get("hash")
        if (not isinstance(schema, str) or not schema
                or not isinstance(expression_hash, str) or not expression_hash
                or not isinstance(dataset, dict) or dataset.get("$schema") != schema):
            raise SystemExit(f"{role} ask: missing or mismatched schema or expression hash")
        current = (schema, expression_hash, dataset.get("schema"))
        if identity is not None and current != identity:
            raise SystemExit(f"{role} ask: answer schema or expression changed between pages")
        identity = current

        rows = dataset.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise SystemExit(f"{role} ask: expected a list of answer rows")
        pages.extend(rows)
        after = answer.get("next")
        if after is None:
            return pages
        if not isinstance(after, str) or not after or after in seen:
            raise SystemExit(f"{role} ask: invalid or repeated cursor")
        seen.add(after)
        body = {"ask": question, "after": after}
