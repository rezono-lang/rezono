"""Compose the bounded-run replay loop across the offline run boundaries."""

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from datetime import datetime, timedelta, timezone
from functools import cache
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator

from loop.replay import replay as _loop_replay
from rezono_compiler import batch, pack, rules
from run.exact_quote import total_micros
from run.installation_input import machines as prepare_machines
from run.inventory_chain import page_facts, resources as chain_resources
from run.journal_claim import claim_once
from run.order_render import render as render_order
from run.order_uncertainty import invoke as invoke_order
from run.price_capture import hourly_micros
from run.request_source import load_request

_RUN = Path(__file__).resolve().parent
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_UTC_INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z")
_APPROVAL_VALIDATOR = Draft202012Validator(
    json.loads((_RUN / "schemas" / "approval.json").read_text(encoding="utf-8"))
)

_ORDER_STEPS = (
    ("submit_order", "authorized", "order_applied"),
    ("observe_machines", "order_applied", "machines_observed"),
)
_INSTALL_STEPS = (
    ("apply_installation", "machines_observed", "installation_applied"),
    ("observe_delivery", "installation_applied", "delivery_observed"),
    ("delete_resources", "delivery_observed", "resources_deleted"),
    ("list_inventory", "resources_deleted", "inventory_cleaned"),
)


@cache
def _dispatch_program() -> rules.Program:
    return rules.load(pack.read(_RUN / "packs" / "dispatch").rules)


@cache
def _cleanup_program() -> rules.Program:
    return rules.load(pack.read(_RUN / "packs" / "cleanup").rules)


def _utc_micros(value: object) -> int:
    if not isinstance(value, str) or _UTC_INSTANT.fullmatch(value) is None:
        raise ValueError("timestamp must be a UTC instant ending in Z")
    return (datetime.fromisoformat(value) - _EPOCH) // timedelta(microseconds=1)


def _quote_cost(plan: Mapping[str, object], price_bytes: bytes) -> int:
    digest = plan.get("price_facts_sha256")
    currency = plan.get("currency")
    lines = plan.get("lines")
    if not isinstance(digest, str) or not isinstance(currency, str) or not isinstance(lines, list):
        raise ValueError("plan must declare currency, price_facts_sha256, and lines")

    prices = hourly_micros(price_bytes, digest)
    quote_lines: list[dict[str, object]] = []
    for line in lines:
        if not isinstance(line, Mapping):
            raise ValueError("each plan line must be an object")
        sku = line.get("sku")
        if not isinstance(sku, str) or sku not in prices:
            raise ValueError(f"missing captured price for SKU {sku!r}")
        quote_lines.append(
            {
                "currency": currency,
                "quantity": line.get("quantity"),
                "billed_periods": line.get("billed_periods"),
                "period_price_micros": prices[sku],
                "setup_price_micros": line.get("setup_price_micros", 0),
            }
        )
    return total_micros(quote_lines, currency)


def _dispatch_authorized(
    plan_hash: str,
    currency: str,
    cost_micros: int,
    approval: object,
    event_us: int,
) -> bool:
    if not isinstance(approval, Mapping) or not _APPROVAL_VALIDATOR.is_valid(dict(approval)):
        raise ValueError("approval does not match schema")
    if type(cost_micros) is not int or not (0 <= cost_micros <= pack.BIGINT[1]):
        raise ValueError("cost_micros must be within the supported integer range")

    cap_micros = min(approval["budget_cents"] * 10_000, pack.BIGINT[1])
    sources = {
        "plan": {"plan_hash": plan_hash, "currency": currency},
        "quote": {"plan_hash": plan_hash, "currency": currency, "cost_micros": cost_micros},
        "approval": {
            "plan_hash": approval["plan_hash"],
            "currency": approval["currency"],
            "decision": approval["decision"],
            "cap_micros": cap_micros,
            "expires_us": _utc_micros(approval["expires_at"]),
        },
        "observation": {"event_us": event_us},
    }
    facts: dict[str, list[tuple[str | int, ...]]] = {"candidate": [(plan_hash,)]}
    for kind, fields in sources.items():
        facts[kind] = [(kind,)]
        facts[f"{kind}__candidate"] = [(kind, plan_hash)]
        for field, value in fields.items():
            facts[f"{kind}__{field}"] = [(kind, value)]

    program = _dispatch_program()
    with closing(batch.connect(program, facts)) as connection:
        batch.compute(connection, program)
        return (plan_hash,) in batch.read(connection, program, ["authorized"])["authorized"]


def _cleanup_status(
    pages: list[dict[str, Any]],
    sweep_id: str,
    plan_hash: str,
    run_id: str,
    delete_receipt: object,
    dispatched_us: int,
    *,
    scope: str = "offline",
) -> str:
    if not isinstance(delete_receipt, Mapping) or delete_receipt.get("accepted") is not True:
        return "unknown"
    attempt_id = delete_receipt.get("id")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        return "unknown"
    if chain_resources(pages, sweep_id, "root") is None:
        return "unknown"
    evidence = page_facts(pages, sweep_id, "root")
    if evidence is None:
        return "unknown"

    facts: dict[str, list[tuple[str | int, ...]]] = {
        **evidence,
        "sweep__run": [(sweep_id, run_id)],
        "sweep__scope": [(sweep_id, scope)],
        "sweep__attempt": [(sweep_id, attempt_id)],
        "sweep__plan_hash": [(sweep_id, plan_hash)],
        "sweep__started_us": [(sweep_id, dispatched_us + 1)],
        "attempt": [(attempt_id,)],
        "attempt__operation": [(attempt_id, "delete_resources")],
        "attempt__run": [(attempt_id, run_id)],
        "attempt__scope": [(attempt_id, scope)],
        "attempt__plan_hash": [(attempt_id, plan_hash)],
        "attempt__dispatched_us": [(attempt_id, dispatched_us)],
    }
    program = _cleanup_program()
    with closing(batch.connect(program, facts)) as connection:
        batch.compute(connection, program)
        cleaned = batch.read(connection, program, ["cleaned"])["cleaned"]
    return "cleaned" if (sweep_id,) in cleaned else "unknown"


def _load_committed_request(scenario: Mapping[str, object], fixture_path: Path) -> str:
    request_file = scenario.get("request_file")
    request_digest = scenario.get("request_sha256")
    if not isinstance(request_file, str) or not isinstance(request_digest, str):
        raise ValueError("scenario must declare request_file and request_sha256")
    provenance = scenario.get("request_provenance")
    if provenance is None:
        provenance = {
            "repository": "rezono-lang/rezono",
            "commit": "0" * 40,
            "path": Path(request_file).as_posix(),
        }
    if not isinstance(provenance, Mapping):
        raise ValueError("request_provenance must be a mapping")
    raw = (fixture_path / request_file).read_bytes()
    sourced = load_request(raw, provenance, request_digest)
    request_id = sourced["request"].get("id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request must contain a nonempty id")
    return request_id


def _run_phase(
    loop_execute: Callable[..., tuple[list[list[str]], str]],
    run_id: str,
    steps: tuple[tuple[str, str, str], ...],
    initial: Sequence[tuple[str, str]],
    observations: Sequence[tuple[str, str]],
) -> tuple[list[list[str]], str]:
    """Execute one bounded phase of the shared loop from its declared steps and observations."""
    requirements = {step: (required,) for step, required, _ in steps}
    completion = {step: done for step, _, done in steps}
    initial_rows = [(run_id, token, value) for token, value in initial]
    sweeps = [[(run_id, token, value)] for token, value in observations]
    return loop_execute(run_id, requirements, completion, initial_rows, sweeps, len(steps))


def execute_run(
    spec: Mapping[str, object],
    fixture_dir: str | Path,
    *,
    claim: Callable[[str], bool],
    submit_order: Callable[[str], Mapping[str, object] | None],
    order_status: Callable[[str], Mapping[str, object] | None],
    observe_machines: Callable[[str], Sequence[Mapping[str, object]]],
    deliver: Callable[[str], Mapping[str, object] | None],
    delete_resources: Callable[[str], Mapping[str, object] | None],
    list_inventory: Callable[[str], list[dict[str, Any]]],
    scope: str = "offline",
    execute: Callable[..., tuple[list[list[str]], str]] | None = None,
) -> dict[str, object]:
    """Execute one bounded run across order, installation, and cleanup phases."""
    if not isinstance(spec, Mapping):
        raise ValueError("spec must be a mapping")
    loop_execute = _loop_replay if execute is None else execute
    fixture_path = Path(fixture_dir)

    request_id = _load_committed_request(spec, fixture_path)
    plan_file = spec.get("plan_file")
    price_file = spec.get("price_file")
    if not isinstance(plan_file, str) or not isinstance(price_file, str):
        raise ValueError("spec must declare plan_file and price_file")

    plan_bytes = (fixture_path / plan_file).read_bytes()
    plan_hash = sha256(plan_bytes).hexdigest()
    render_order(plan_bytes, plan_hash)
    plan = json.loads(plan_bytes.decode("utf-8"))
    cost_micros = _quote_cost(plan, (fixture_path / price_file).read_bytes())

    event_us = _utc_micros(spec.get("clock"))
    authorized = _dispatch_authorized(plan_hash, plan["currency"], cost_micros, spec.get("approval"), event_us)

    orders = 0

    def _apply(key: str) -> Mapping[str, object] | None:
        nonlocal orders
        orders += 1
        return submit_order(key)

    if authorized:
        order_state, order_receipt = invoke_order(plan_hash, claim, _apply, order_status)
    else:
        order_state, order_receipt = "refused", None

    sweep_id = "after"
    order_applied = order_state == "applied" or orders > 0
    cleanup_ran = False

    def _run_cleanup() -> tuple[object, str]:
        nonlocal cleanup_ran
        cleanup_ran = True
        receipt = delete_resources(plan_hash)
        pages = list_inventory(plan_hash)
        if not isinstance(pages, list):
            raise ValueError("inventory must be a list of pages")
        status = _cleanup_status(
            pages, sweep_id, plan_hash, plan_hash, receipt, event_us, scope=scope
        )
        return receipt, status

    try:
        machines = (
            prepare_machines(observe_machines(plan_hash))
            if order_state == "applied"
            else []
        )

        order_obs: list[tuple[str, str]] = []
        if authorized and order_state == "applied" and order_receipt is not None:
            order_obs.append(("order_applied", str(order_receipt["id"])))
            if machines:
                order_obs.append(("machines_observed", str(len(machines))))
        order_trace, order_outcome = _run_phase(
            loop_execute,
            plan_hash,
            _ORDER_STEPS,
            [("authorized", plan_hash)] if authorized else [],
            order_obs,
        )

        installation = (
            deliver(plan_hash)
            if order_outcome == "success" and bool(machines)
            else None
        )
        delivered = (
            order_outcome == "success"
            and bool(machines)
            and isinstance(installation, Mapping)
            and installation.get("ready") is True
            and installation.get("request_id") == request_id
            and plan.get("request_id") == request_id
        )

        if order_applied:
            delete_receipt, cleanup_evidence = _run_cleanup()
        else:
            delete_receipt = None
            cleanup_evidence = "unknown"
    finally:
        if order_applied and not cleanup_ran:
            try:
                _run_cleanup()
            except Exception:
                pass

    install_obs: list[tuple[str, str]] = []
    if order_outcome == "success" and machines:
        install_obs.append(("installation_applied", request_id))
        if delivered:
            install_obs.append(("delivery_observed", request_id))
            if isinstance(delete_receipt, Mapping) and delete_receipt.get("accepted") is True:
                install_obs.append(("resources_deleted", str(delete_receipt.get("id"))))
                if cleanup_evidence == "cleaned":
                    install_obs.append(("inventory_cleaned", sweep_id))
    install_trace, install_outcome = _run_phase(
        loop_execute,
        plan_hash,
        _INSTALL_STEPS,
        [("machines_observed", str(len(machines)))] if (order_outcome == "success" and machines) else [],
        install_obs,
    )

    operations = [step for step_list in (*order_trace, *install_trace) for step in step_list]
    cleanup = (
        cleanup_evidence
        if scope == "live"
        or (
            install_outcome == "success"
            and "delete_resources" in operations
            and "list_inventory" in operations
        )
        else "unknown"
    )
    return {
        "plan_hash": plan_hash,
        "cost_micros": cost_micros,
        "orders": orders,
        "request": request_id,
        "delivered": delivered,
        "cleanup": cleanup,
        "sweep": sweep_id,
        "loop_phases": ["order", "installation"],
        "operations": operations,
    }


def replay(
    scenario: Mapping[str, object],
    fixture_dir: str | Path,
    db_path: str | Path,
    *,
    execute: Callable[..., tuple[list[list[str]], str]] | None = None,
) -> dict[str, object]:
    """Replay the bounded offline run through both loop phases and return its summary."""
    if not isinstance(scenario, Mapping):
        raise ValueError("scenario must be a mapping")
    raw_inventory = scenario.get("inventory", ())
    if not isinstance(raw_inventory, list):
        raise ValueError("scenario inventory must be a list of pages")
    journal_path = Path(db_path)
    receipt = scenario.get("order_receipt")
    recorded_receipt = receipt if isinstance(receipt, Mapping) else None
    return execute_run(
        scenario,
        fixture_dir,
        claim=lambda key: claim_once(journal_path, key),
        submit_order=lambda _: recorded_receipt,
        order_status=lambda _: recorded_receipt,
        observe_machines=lambda _: scenario.get("machine_observations", ()),
        deliver=lambda _: scenario.get("installation"),
        delete_resources=lambda _: scenario.get("delete_receipt"),
        list_inventory=lambda _: raw_inventory,
        scope="offline",
        execute=execute,
    )
