"""A small client for the Feldera HTTP API, for engine tests and measurements (FELDERA_URL)."""

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

URL = os.environ.get("FELDERA_URL")


def call(method, path, body=None, raw=False):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(URL + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        text = r.read().decode()
    return text if raw else (json.loads(text) if text.strip() else None)


def wait(name, field, done, timeout=3600):
    end = time.time() + timeout
    while time.time() < end:
        p = call("GET", f"/v0/pipelines/{name}")
        if p[field] in done:
            return p
        if p.get("program_status", "").endswith("Error"):
            raise RuntimeError(json.dumps(p.get("program_error"))[:4000])
        time.sleep(1)
    raise TimeoutError(f"{name}: {field} did not reach {done}")


def deploy(name, program, profile=None, workers=4, udf_rust="", udf_toml=""):
    """(Re)create a pipeline with this program (and Rust UDFs), start it, and return how long compiling took."""
    # The build profile does not change what the SQL means; `unoptimized` builds in seconds instead of
    # minutes, so the correctness tests can use it (FELDERA_PROFILE), and a smoke test keeps `optimized`.
    profile = profile or os.environ.get("FELDERA_PROFILE", "optimized")
    if not udf_rust and "CREATE FUNCTION rede_" in program:  # the calculation's UDF (udf/, docs/compiler.md)
        udf = Path(__file__).resolve().parents[2] / "udf"
        udf_rust, udf_toml = (udf / "udf.rs").read_text(), (udf / "udf.toml").read_text()
    try:
        call("POST", f"/v0/pipelines/{name}/stop?force=true")
        wait(name, "deployment_status", {"Stopped"})
        call("POST", f"/v0/pipelines/{name}/clear")
        wait(name, "storage_status", {"Cleared"})
        call("DELETE", f"/v0/pipelines/{name}")
    except urllib.error.HTTPError:
        pass
    start = time.time()
    call("PUT", f"/v0/pipelines/{name}", {"name": name, "program_code": program, "runtime_config": {"workers": workers},
                                          "program_config": {"profile": profile}, "udf_rust": udf_rust, "udf_toml": udf_toml})
    wait(name, "program_status", {"Success"})
    compiled = time.time() - start
    call("POST", f"/v0/pipelines/{name}/start")
    wait(name, "deployment_status", {"Running"})
    return compiled


def stop(name):
    call("POST", f"/v0/pipelines/{name}/stop?force=true")
    wait(name, "deployment_status", {"Stopped"})
    call("POST", f"/v0/pipelines/{name}/clear")


def push(name, updates, chunk=100_000):
    """Send {table: [{"insert"|"delete": row}]} and return the completion tokens."""
    tokens = []
    for table, rows in updates.items():
        for k in range(0, len(rows), chunk):
            q = urllib.parse.urlencode({"format": "json", "update_format": "insert_delete", "array": "true"})
            body = json.dumps(rows[k:k + chunk]).encode()
            tokens.append(call("POST", f"/v0/pipelines/{name}/ingress/{urllib.parse.quote(table)}?{q}", body)["token"])
    return tokens


def processed(name, tokens):
    """The processing barrier: return once every view has seen everything sent before these tokens."""
    for t in tokens:
        while call("GET", f"/v0/pipelines/{name}/completion_status?token={t}")["status"] != "complete":
            time.sleep(0.002)


def query(name, sql):
    q = urllib.parse.urlencode({"sql": sql, "format": "json"})
    return [json.loads(x) for x in call("GET", f"/v0/pipelines/{name}/query?{q}", raw=True).splitlines() if x]
