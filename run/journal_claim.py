"""Store one durable effect claim per exact plan digest."""

from contextlib import closing
from pathlib import Path
import re
import sqlite3


def claim_once(database: str | Path, plan_hash: str) -> bool:
    """Return whether this caller inserted and committed the plan's claim."""
    if not isinstance(plan_hash, str) or re.fullmatch(r"[0-9a-f]{64}", plan_hash) is None:
        raise ValueError("the plan hash must contain 64 lowercase hexadecimal characters")

    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        connection.execute("CREATE TABLE IF NOT EXISTS effect_claim (plan_hash TEXT NOT NULL PRIMARY KEY)")
        inserted = connection.execute(
            "INSERT INTO effect_claim (plan_hash) VALUES (?) ON CONFLICT(plan_hash) DO NOTHING",
            (plan_hash,),
        ).rowcount == 1
    return inserted
