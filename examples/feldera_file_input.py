"""Native appendable JSON file connectors for the isolated multi-pipeline oracle."""

import json
import re
import time
from pathlib import PurePosixPath

from rezono_compiler import feldera_names
from rezono_compiler.sqltext import literal

from feldera import call


MOUNT = PurePosixPath("/tmp/rezono-oracle-input")
# The compiler emits one quoted CREATE TABLE per line. Touch only its trailing semicolon.
_TABLE = re.compile(r'^CREATE TABLE ("(?:[^"]|"")+") \([^;\n]*\);$', re.MULTILINE)


class FileInputs:
    def __init__(self, directory, tables):
        self.directory = directory
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)
        self.paths = {}
        self.expected = {}
        for index, name in enumerate(sorted(tables)):
            path = directory / f"{index}.ndjson"
            path.touch(exist_ok=False)
            path.chmod(0o644)
            self.paths[name] = path
            self.expected[feldera_names.physical(name)] = 0

    def connect(self, program):
        clauses = {}
        for table, path in self.paths.items():
            guest_path = MOUNT / self.directory.parent.name / self.directory.name / path.name
            connector = {
                "transport": {"name": "file_input", "config": {"path": str(guest_path), "follow": True}},
                "format": {"name": "json", "config": {"update_format": "insert_delete", "array": False, "lines": "single"}},
            }
            clauses[feldera_names.quoted(table)] = literal(json.dumps([connector]))
        attached = set()

        def add(match):
            table = match[1]
            if table not in clauses:
                return match[0]
            if table in attached:
                raise ValueError(f"duplicate table declaration: {table}")
            attached.add(table)
            return match[0][:-1] + f" WITH ('connectors' = {clauses[table]});"

        result = _TABLE.sub(add, program)
        if attached != clauses.keys():
            raise ValueError(f"missing input declarations: {sorted(clauses.keys() - attached)}")
        return result

    def send(self, pipeline, updates):
        for table, events in updates.items():
            if not events:
                continue
            with self.paths[table].open("a", encoding="utf-8", newline="\n") as stream:
                for event in events:
                    stream.write(json.dumps(event, allow_nan=False) + "\n")
            self.expected[feldera_names.physical(table)] += len(events)

        deadline = time.monotonic() + 120
        while True:
            stats = call("GET", f"/v0/pipelines/{pipeline}/stats")
            received = {}
            for endpoint in stats["inputs"]:
                table = endpoint["config"]["stream"]
                if table not in self.expected:
                    continue
                metrics = endpoint["metrics"]
                if endpoint.get("fatal_error") or metrics["num_parse_errors"] or metrics["num_transport_errors"]:
                    raise RuntimeError(f"{pipeline}: file input failed for {table}")
                if table in received or metrics["total_records"] > self.expected[table]:
                    raise RuntimeError(f"{pipeline}: unexpected input records for {table}")
                received[table] = metrics["total_records"]
            global_metrics = stats["global_metrics"]
            if (received == self.expected and global_metrics["total_input_records"] >= sum(self.expected.values())
                    and global_metrics["total_completed_records"] >= global_metrics["total_input_records"]):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{pipeline}: file inputs did not reach their completed record counts")
            time.sleep(0.1)
