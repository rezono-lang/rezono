"""Live provider command entrypoint wired to the shared loop executor and durable Git claim."""

import argparse
from collections.abc import Callable, Mapping, Sequence
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from run.git_claim import claim_once
from run.offline_replay import execute_run

_REQUIRED_PORTS = (
    "submit_order",
    "order_status",
    "observe_machines",
    "deliver",
    "delete_resources",
    "list_inventory",
)


def _validate_ports(ports: object) -> Mapping[str, Callable[..., Any]]:
    if not isinstance(ports, Mapping):
        raise ValueError("ports must be a mapping")
    missing = [name for name in _REQUIRED_PORTS if not callable(ports.get(name))]
    if missing:
        raise ValueError(f"missing callable provider ports: {', '.join(missing)}")
    return ports


def run_live(
    spec: Mapping[str, object],
    fixture_dir: str | Path,
    ports: Mapping[str, Callable[..., Any]],
    *,
    claim_remote: str | Path,
    run_id: str,
    execute: Callable[..., tuple[list[list[str]], str]] | None = None,
) -> dict[str, object]:
    """Execute one approved live run using recording/provider ports and a durable Git claim."""
    validated_ports = _validate_ports(ports)
    if not isinstance(claim_remote, (str, Path)) or not str(claim_remote).strip():
        raise ValueError("claim_remote must be a nonempty string or path")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a nonempty string")
    remote_target = str(claim_remote)

    return execute_run(
        spec,
        fixture_dir,
        claim=lambda key: claim_once(remote_target, key, run_id),
        submit_order=validated_ports["submit_order"],
        order_status=validated_ports["order_status"],
        observe_machines=validated_ports["observe_machines"],
        deliver=validated_ports["deliver"],
        delete_resources=validated_ports["delete_resources"],
        list_inventory=validated_ports["list_inventory"],
        scope="live",
        execute=execute,
    )


def _load_ports(target: str) -> Mapping[str, Callable[..., Any]]:
    module_name, sep, attr_name = target.partition(":")
    if not sep or not module_name.strip() or not attr_name.strip():
        raise ValueError("ports must be given as '<module>:<callable>'")
    module = importlib.import_module(module_name)
    resolved: object = module
    for part in attr_name.split("."):
        resolved = getattr(resolved, part)
    if callable(resolved):
        resolved = resolved()
    return _validate_ports(resolved)


def _require_nonempty(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint invoked by the protected provider-run workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default=os.environ.get("REZONO_RUN_SPEC", ""))
    parser.add_argument("--fixture-dir", default=os.environ.get("REZONO_FIXTURE_DIR", ""))
    parser.add_argument("--claim-remote", default=os.environ.get("REZONO_CLAIM_REMOTE", ""))
    parser.add_argument("--ports", default=os.environ.get("REZONO_PROVIDER_PORTS", ""))
    parser.add_argument("--run-id", default=os.environ.get("REZONO_RUN_ID", ""))
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        spec_path = Path(_require_nonempty(args.spec, "--spec"))
        claim_remote = _require_nonempty(args.claim_remote, "--claim-remote")
        ports_target = _require_nonempty(args.ports, "--ports")
        run_id = _require_nonempty(args.run_id, "--run-id")
        fixture_dir = Path(args.fixture_dir.strip()) if args.fixture_dir.strip() else spec_path.resolve().parent
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        ports = _load_ports(ports_target)
        result = run_live(spec, fixture_dir, ports, claim_remote=claim_remote, run_id=run_id)
    except (OSError, ValueError, RuntimeError, ImportError, AttributeError) as exc:
        print(f"provider_run failed closed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
