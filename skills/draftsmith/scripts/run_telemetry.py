#!/usr/bin/env python3
"""Record privacy-minimal, deduplicated draftsmith run telemetry."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from delivery_state import ENTRIES, GOALS, StateError, load, parse_timestamp, resolve, state_lock
from git_storage import StorageError, atomic_json, metadata_dir
from run_cost import ROLES as COST_ROLES
from run_cost import CostError, collect as collect_cost


SCHEMA_VERSION = 2
LANES = ("full", "light", "unknown")
COUNTER_FIELDS = {
    "designer_round": "designer_rounds",
    "auditor_round": "auditor_rounds",
    "reviewer_round": "reviewer_rounds",
    "light_to_full": "light_to_full",
    "audit_traceability_miss": "audit_traceability_miss",
    "audit_adr_unjustified": "audit_adr_unjustified",
    "audit_prediction_divergence": "audit_prediction_divergence",
    "audit_anchor_mismatch": "audit_anchor_mismatch",
    "audit_scope_creep": "audit_scope_creep",
    "audit_requirement_misread": "audit_requirement_misread",
    "test_failure": "test_failures",
    "ci_failure": "ci_failures",
    "implementation_finding": "implementation_findings",
    "design_finding": "design_findings",
    "human_decision": "human_decisions",
}
EVENTS = tuple(COUNTER_FIELDS)
GOAL_FINAL_PHASES = {
    "implemented": "implemented",
    "pr_open": "pr_open",
    "review_requested": "wait_human_review",
    "review_complete": "review_complete",
    "merge_ready": "merge_ready",
    "merged": "done",
}
TERMINAL_PHASES = set(GOAL_FINAL_PHASES.values()) | {"blocked"}
DELIVERY_COUNTER_FIELDS = {
    "ci_failures",
    "implementation_findings",
    "design_findings",
    "human_decisions",
    "reviewer_rounds",
}
OPAQUE_ID_RE = re.compile(r"[0-9a-f]{32}")
RECEIPT_KEYS = {
    "schema_version", "run_id", "lane", "entry", "goal", "final_phase", "counters",
    "delivery_counters", "duration_seconds", "started_at", "finished_at",
}
# Additive, optional per-role cost block projected from a session transcript. Numbers and role
# enums only; schema_version of the receipt stays at 2.
RECEIPT_OPTIONAL_KEYS = {"cost"}
COST_METRIC_FIELDS = {
    "turns",
    "avg_context_tokens",
    "max_context_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "duration_seconds",
    "agents",
}
COST_KEYS = {"schema_version", "roles", "total", "unmapped_subagents"}
PLAN_STATUS_RE = re.compile(r"^(\s*-\s*Status:\s*)(\S+)(\s*)$")
PLAN_STATUSES = ("designed", "implemented")
AUDIT_LEDGER = Path(__file__).resolve().parents[3] / "scripts" / "audit-ledger.sh"


class TelemetryError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def paths(repo: str, run_id: str | None = None, *, create: bool = False) -> tuple[Path, Path]:
    runs = metadata_dir(repo, "draftsmith-runs", create=create)
    receipts = metadata_dir(repo, "draftsmith-delivery-receipts", create=create)
    if run_id is None:
        return runs, receipts
    if not OPAQUE_ID_RE.fullmatch(run_id):
        raise TelemetryError("run_id must be a 32 character opaque lowercase hex id")
    return runs / f"{run_id}.json", receipts / f"{run_id}.json"


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TelemetryError(f"cannot read telemetry file: {exc}") from exc
    if not isinstance(value, dict):
        raise TelemetryError("telemetry file must be a JSON object")
    return value


def validate_run(run: dict[str, Any]) -> None:
    expected = {
        "schema_version", "run_id", "lane", "entry", "goal", "counters", "event_ids",
        "revision", "started_at"
    }
    if set(run) != expected or run.get("schema_version") != SCHEMA_VERSION:
        raise TelemetryError("invalid run telemetry schema")
    if not OPAQUE_ID_RE.fullmatch(run.get("run_id", "")) or run.get("lane") not in LANES:
        raise TelemetryError("invalid run id or lane")
    if run.get("entry") not in ENTRIES or run.get("goal") not in GOALS:
        raise TelemetryError("invalid run entry or goal")
    if run["entry"] == "delivery" and run["goal"] == "implemented":
        raise TelemetryError("delivery entry requires a goal after implemented")
    if set(run.get("counters", {})) != set(COUNTER_FIELDS.values()):
        raise TelemetryError("invalid telemetry counters")
    if any(not isinstance(value, int) or value < 0 for value in run["counters"].values()):
        raise TelemetryError("telemetry counters must be non-negative integers")
    if not isinstance(run.get("revision"), int) or run["revision"] < 0:
        raise TelemetryError("telemetry revision must be a non-negative integer")
    ids = run.get("event_ids")
    if not isinstance(ids, list) or len(ids) != len(set(ids)):
        raise TelemetryError("event ids must be a unique list")
    if any(not OPAQUE_ID_RE.fullmatch(value) for value in ids):
        raise TelemetryError("event ids must be opaque lowercase hex ids")
    parse_timestamp(run["started_at"])


def validate_cost(cost: Any) -> None:
    if not isinstance(cost, dict) or set(cost) != COST_KEYS:
        raise TelemetryError("invalid receipt cost block")
    if not isinstance(cost.get("schema_version"), int):
        raise TelemetryError("invalid receipt cost schema version")
    if not isinstance(cost.get("unmapped_subagents"), int) or cost["unmapped_subagents"] < 0:
        raise TelemetryError("invalid receipt cost unmapped count")
    roles = cost.get("roles")
    if not isinstance(roles, dict) or any(role not in COST_ROLES for role in roles):
        raise TelemetryError("receipt cost roles must be draftsmith role enums")
    for metrics in list(roles.values()) + [cost.get("total")]:
        if not isinstance(metrics, dict) or set(metrics) != COST_METRIC_FIELDS:
            raise TelemetryError("invalid receipt cost metrics")
        if any(not isinstance(value, int) or value < 0 for value in metrics.values()):
            raise TelemetryError("receipt cost metrics must be non-negative integers")


def validate_receipt(receipt: dict[str, Any]) -> None:
    keys = set(receipt)
    if (
        not RECEIPT_KEYS <= keys
        or keys - RECEIPT_KEYS - RECEIPT_OPTIONAL_KEYS
        or receipt.get("schema_version") != SCHEMA_VERSION
    ):
        raise TelemetryError("invalid v2 receipt schema")
    if "cost" in receipt:
        validate_cost(receipt["cost"])
    if not OPAQUE_ID_RE.fullmatch(receipt.get("run_id", "")):
        raise TelemetryError("invalid v2 receipt run id")
    if receipt.get("lane") not in LANES:
        raise TelemetryError("invalid v2 receipt lane")
    if receipt.get("entry") not in {"requirements", "delivery"}:
        raise TelemetryError("invalid v2 receipt entry")
    if receipt.get("goal") not in GOALS:
        raise TelemetryError("invalid v2 receipt goal")
    if receipt.get("final_phase") not in TERMINAL_PHASES:
        raise TelemetryError("invalid v2 receipt final phase")
    if receipt["final_phase"] not in {GOAL_FINAL_PHASES[receipt["goal"]], "blocked"}:
        raise TelemetryError("v2 receipt goal and final phase do not match")
    if set(receipt.get("counters", {})) != set(COUNTER_FIELDS.values()):
        raise TelemetryError("invalid v2 receipt counters")
    if set(receipt.get("delivery_counters", {})) != DELIVERY_COUNTER_FIELDS:
        raise TelemetryError("invalid v2 delivery counters")
    if any(
        not isinstance(value, int) or value < 0
        for value in receipt["delivery_counters"].values()
    ):
        raise TelemetryError("v2 delivery counters must be non-negative integers")
    if not isinstance(receipt.get("duration_seconds"), int) or receipt["duration_seconds"] < 0:
        raise TelemetryError("invalid v2 receipt duration")
    parse_timestamp(receipt["started_at"])
    parse_timestamp(receipt["finished_at"])


def start(repo: str, lane: str, entry: str, goal: str) -> Path:
    # delivery_state remains the only PR-lifecycle state. A default implemented run does not
    # create it merely to collect telemetry.
    if lane == "unknown" and entry != "delivery":
        raise TelemetryError("unknown lane is reserved for delivery entry")
    runs, _receipts = paths(repo, create=True)
    with state_lock(runs / ".start"):
        active = sorted(runs.glob("*.json"))
        if len(active) > 1:
            raise TelemetryError("multiple active telemetry runs exist in this worktree")
        if active:
            run = load_json(active[0])
            validate_run(run)
            if (run["lane"], run["entry"], run["goal"]) != (lane, entry, goal):
                raise TelemetryError("active telemetry run does not match the requested route")
            return active[0]
        run_id = secrets.token_hex(16)
        run_path, _receipt_path = paths(repo, run_id, create=True)
        run = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "lane": lane,
            "entry": entry,
            "goal": goal,
            "counters": {field: 0 for field in COUNTER_FIELDS.values()},
            "event_ids": [],
            "revision": 0,
            "started_at": now(),
        }
        validate_run(run)
        atomic_json(run_path, run, immutable=True)
    return run_path


def event(
    repo: str, run_id: str, event_name: str, event_id: str, expected_revision: int
) -> tuple[Path, int]:
    run_path, receipt_path = paths(repo, run_id, create=False)
    with state_lock(run_path):
        if receipt_path.exists():
            raise TelemetryError("finished run telemetry is immutable")
        run = load_json(run_path)
        validate_run(run)
        if run["revision"] != expected_revision:
            raise TelemetryError(
                f"revision conflict: expected {expected_revision}, current {run['revision']}"
            )
        if event_id in run["event_ids"]:
            return run_path, run["revision"]
        if not OPAQUE_ID_RE.fullmatch(event_id):
            raise TelemetryError("event_id must be a 32 character opaque lowercase hex id")
        run["event_ids"].append(event_id)
        run["counters"][COUNTER_FIELDS[event_name]] += 1
        run["revision"] += 1
        validate_run(run)
        atomic_json(run_path, run)
    return run_path, run["revision"]


def retention_warning(receipt_dir: Path) -> str | None:
    receipts = list(receipt_dir.glob("*.json"))
    if len(receipts) > 100:
        return f"warning: {len(receipts)} receipts retained; review local retention policy"
    return None


def promote_check() -> dict[str, Any]:
    """Run audit-ledger promote-check; absence or failure is a warning, never a finish error."""
    if not AUDIT_LEDGER.is_file():
        return {"status": "missing", "warning": "audit-ledger.sh not found; promote-check skipped"}
    try:
        result = subprocess.run(
            ["bash", str(AUDIT_LEDGER), "promote-check"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "warning": f"promote-check failed: {exc}"}
    if result.returncode != 0:
        return {
            "status": "failed",
            "returncode": result.returncode,
            "warning": f"promote-check exited {result.returncode}",
        }
    proposals = Path(os.path.expanduser("~/.local/state/draftsmith/improvement-proposals"))
    count = len(list(proposals.glob("*.json"))) if proposals.is_dir() else 0
    return {"status": "ok", "proposals": count}


def update_plan_status(plan_file: Path, status: str) -> dict[str, Any]:
    if status not in PLAN_STATUSES:
        raise TelemetryError("plan status must be designed or implemented")
    if not plan_file.is_file():
        raise TelemetryError(f"plan file not found: {plan_file}")
    lines = plan_file.read_text(encoding="utf-8").splitlines(keepends=True)
    replaced = 0
    previous: str | None = None
    for index, line in enumerate(lines):
        match = PLAN_STATUS_RE.match(line.rstrip("\n"))
        if match:
            previous = match.group(2)
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{match.group(1)}{status}{newline}"
            replaced += 1
    if replaced != 1:
        raise TelemetryError("plan file must contain exactly one '- Status:' line")
    plan_file.write_text("".join(lines), encoding="utf-8")
    return {"path": str(plan_file), "previous": previous, "status": status}


def finish(
    repo: str,
    run_id: str,
    final_phase: str,
    delivery_key: str | None,
    expected_revision: int,
    *,
    cost: dict[str, Any] | None = None,
    force_empty: bool = False,
) -> tuple[Path, list[str]]:
    run_path, receipt_path = paths(repo, run_id, create=False)
    with state_lock(run_path):
        if receipt_path.is_file():
            existing = load_json(receipt_path)
            validate_receipt(existing)
            if existing["final_phase"] != final_phase:
                raise TelemetryError("finished receipt has a different final phase")
            warnings = [w for w in (retention_warning(receipt_path.parent),) if w]
            return receipt_path, warnings
        run = load_json(run_path)
        validate_run(run)
        if run["revision"] != expected_revision:
            raise TelemetryError(
                f"revision conflict: expected {expected_revision}, current {run['revision']}"
            )
        if final_phase not in TERMINAL_PHASES:
            raise TelemetryError("finish requires a terminal phase")
        expected_phase = GOAL_FINAL_PHASES[run["goal"]]
        if final_phase not in {expected_phase, "blocked"}:
            raise TelemetryError(
                f"goal {run['goal']} must finish at {expected_phase} or blocked"
            )
        needs_delivery_state = run["entry"] == "delivery" or (
            run["goal"] != "implemented" and final_phase != "blocked"
        )
        if needs_delivery_state and delivery_key is None:
            raise TelemetryError("delivery goals require --delivery-key at finish")
        if delivery_key is not None:
            _root, _branch, _key, state_path = resolve(repo, delivery_key)
            state = load(state_path)
            if state["phase"] != final_phase:
                raise TelemetryError("delivery state and telemetry final phase do not match")
            if (state["entry"], state["goal"]) != (run["entry"], run["goal"]):
                raise TelemetryError("delivery state and telemetry route do not match")
        delivery_counters = {field: 0 for field in DELIVERY_COUNTER_FIELDS}
        if delivery_key is not None:
            # delivery_state owns deduplicated PR-review workflow observations. Project them into
            # the final v2 receipt once; callers must not mirror the same delivery event through
            # the telemetry event command.
            for metric in (
                "ci_failures",
                "implementation_findings",
                "design_findings",
                "human_decisions",
            ):
                delivery_counters[metric] = state["metrics"][metric]
            delivery_counters["reviewer_rounds"] = state["review_cycles"]
        finished_at = now()
        duration = max(
            0,
            int((parse_timestamp(finished_at) - parse_timestamp(run["started_at"])).total_seconds()),
        )
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "lane": run["lane"],
            "entry": run["entry"],
            "goal": run["goal"],
            "final_phase": final_phase,
            "counters": run["counters"],
            "delivery_counters": delivery_counters,
            "duration_seconds": duration,
            "started_at": run["started_at"],
            "finished_at": finished_at,
        }
        if cost is not None:
            receipt["cost"] = cost
        validate_receipt(receipt)
        warnings: list[str] = []
        if not force_empty and not any(run["counters"].values()):
            # Every agent round should have left an event; an all-zero receipt usually means the
            # run recorded nothing, not that nothing happened.
            warnings.append(
                "warning: all telemetry counters are 0; events were not recorded "
                "(pass --force-empty to silence)"
            )
        atomic_json(receipt_path, receipt, immutable=True)
        run_path.unlink()
    retention = retention_warning(receipt_path.parent)
    if retention:
        warnings.append(retention)
    return receipt_path, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("--lane", choices=LANES, required=True)
    start_parser.add_argument("--entry", choices=ENTRIES, required=True)
    start_parser.add_argument("--goal", choices=GOALS, required=True)
    start_parser.add_argument(
        "--run-card",
        action="store_true",
        help="print the read-only run card together with the start result in one JSON object",
    )
    start_parser.add_argument("--through-review", action="store_true")
    event_parser = commands.add_parser("event")
    event_parser.add_argument("--run-id", required=True)
    event_parser.add_argument("--event", choices=EVENTS, required=True)
    event_parser.add_argument("--event-id")
    event_parser.add_argument("--expect-revision", type=int, required=True)
    finish_parser = commands.add_parser("finish")
    finish_parser.add_argument("--run-id", required=True)
    finish_parser.add_argument("--final-phase", choices=sorted(TERMINAL_PHASES), required=True)
    finish_parser.add_argument("--delivery-key")
    finish_parser.add_argument("--expect-revision", type=int, required=True)
    finish_parser.add_argument(
        "--promote-check",
        action="store_true",
        help="run scripts/audit-ledger.sh promote-check after finishing (failure is a warning)",
    )
    finish_parser.add_argument("--plan-file", type=Path)
    finish_parser.add_argument("--plan-status", choices=PLAN_STATUSES)
    finish_parser.add_argument(
        "--cost-from",
        type=Path,
        metavar="MAIN_JSONL",
        help="project per-role cost from a session transcript into the receipt",
    )
    finish_parser.add_argument(
        "--force-empty",
        action="store_true",
        help="silence the warning for receipts whose counters are all 0",
    )
    args = parser.parse_args()
    try:
        if args.command == "start":
            card: dict[str, Any] | None = None
            if args.run_card:
                # run_inspect imports this module; import lazily to keep run_inspect importable.
                from run_inspect import run_card

                card = run_card(args.entry, args.goal, args.through_review, args.lane)
            result = start(args.repo, args.lane, args.entry, args.goal)
            run = load_json(result)
            started = {"run_id": result.stem, "path": str(result), "revision": run["revision"]}
            if card is None:
                print(json.dumps(started, sort_keys=True))
            else:
                print(
                    json.dumps(
                        {"run_card": card, "run": started},
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                )
        elif args.command == "event":
            result, revision = event(
                args.repo,
                args.run_id,
                args.event,
                args.event_id or secrets.token_hex(16),
                args.expect_revision,
            )
            print(json.dumps({"path": str(result), "revision": revision}, sort_keys=True))
        else:
            if (args.plan_file is None) != (args.plan_status is None):
                raise TelemetryError("--plan-file and --plan-status must be given together")
            cost: dict[str, Any] | None = None
            if args.cost_from is not None:
                try:
                    cost = collect_cost(args.cost_from)
                except CostError as exc:
                    raise TelemetryError(f"cannot collect cost: {exc}") from exc
            result, warnings = finish(
                args.repo,
                args.run_id,
                args.final_phase,
                args.delivery_key,
                args.expect_revision,
                cost=cost,
                force_empty=args.force_empty,
            )
            print(result)
            extras: dict[str, Any] = {}
            # The bundled bookkeeping runs after the receipt is immutable, so a re-run of the same
            # finish command is safe: the receipt is returned as-is and the extras are repeated.
            if args.promote_check:
                extras["promote_check"] = promote_check()
                if "warning" in extras["promote_check"]:
                    warnings.append(extras["promote_check"]["warning"])
            if args.plan_file is not None:
                extras["plan"] = update_plan_status(args.plan_file, args.plan_status)
            if cost is not None:
                extras["cost"] = "projected" if "cost" in load_json(result) else "skipped"
            if extras:
                print(json.dumps(extras, ensure_ascii=False, sort_keys=True))
            for warning in warnings:
                print(warning, file=sys.stderr)
    except (StateError, StorageError, TelemetryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
