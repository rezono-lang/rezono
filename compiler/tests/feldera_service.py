"""Give each hosted oracle compilation its own disposable engine on the same isolated loopback."""

import os
from pathlib import Path
import shutil
import subprocess


def release_engine(sandbox, reports):
    service = sandbox + "-engine"
    inspect = subprocess.run(["docker", "container", "inspect", service],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if inspect.returncode == 0:
        with (reports / "engine.log").open("ab") as log:
            subprocess.run(["docker", "logs", "--tail", "250", service],
                           stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(["docker", "rm", "--force", "--volumes", service], check=True)


def start_engine(sandbox, pipeline):
    reports = Path(os.environ["FELDERA_ORACLE_REPORTS"])
    before = shutil.disk_usage(reports).free
    release_engine(sandbox, reports)
    with (reports / "storage.log").open("a", encoding="utf-8") as log:
        print(f"{pipeline}: runner free bytes before release={before} "
              f"after release={shutil.disk_usage(reports).free}", file=log)
    inputs = os.environ["FELDERA_ORACLE_INPUT_DIR"]
    subprocess.run([
        "docker", "run", "--detach", "--name", sandbox + "-engine", "--network", "container:" + sandbox,
        "--env", "CARGO_NET_OFFLINE=true", "--log-driver", "local", "--log-opt", "max-size=8m",
        "--log-opt", "max-file=2", "--mount", f"type=bind,src={inputs},dst=/tmp/rezono-oracle-input,readonly",
        os.environ["FELDERA_ORACLE_IMAGE"],
    ], check=True)
    subprocess.run(["curl", "--fail", "--silent", "--show-error", "--retry", "45", "--retry-connrefused",
                    "--retry-delay", "2", "--retry-max-time", "95", "--max-time", "5",
                    os.environ["FELDERA_URL"] + "/healthz"], check=True)


if __name__ == "__main__":
    release_engine(os.environ["FELDERA_ORACLE_SANDBOX"], Path(os.environ["FELDERA_ORACLE_REPORTS"]))
