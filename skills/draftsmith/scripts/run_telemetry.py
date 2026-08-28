#!/usr/bin/env python3
"""Record privacy-minimal, deduplicated draftsmith run telemetry."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from delivery_state import ENTRIES, GOALS, StateError, load, parse_timestamp, resolve, state_lock
from git_storage import StorageError, atomic_json, metadata_dir


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


def validate_receipt(receipt: dict[str, Any]) -> None:
    if set(receipt) != RECEIPT_KEYS or receipt.get("schema_version") != SCHEMA_VERSION:
        raise TelemetryError("invalid v2 receipt schema")
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


def finish(
    repo: str, run_id: str, final_phase: str, delivery_key: str | None, expected_revision: int
) -> tuple[Path, str | None]:
    run_path, receipt_path = paths(repo, run_id, create=False)
    with state_lock(run_path):
        if receipt_path.is_file():
            existing = load_json(receipt_path)
            validate_receipt(existing)
            if existing["final_phase"] != final_phase:
                raise TelemetryError("finished receipt has a different final phase")
            return receipt_path, retention_warning(receipt_path.parent)
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
        validate_receipt(receipt)
        atomic_json(receipt_path, receipt, immutable=True)
        run_path.unlink()
    return receipt_path, retention_warning(receipt_path.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("--lane", choices=LANES, required=True)
    start_parser.add_argument("--entry", choices=ENTRIES, required=True)
    start_parser.add_argument("--goal", choices=GOALS, required=True)
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
    args = parser.parse_args()
    try:
        if args.command == "start":
            result = start(args.repo, args.lane, args.entry, args.goal)
            run = load_json(result)
            print(
                json.dumps(
                    {"run_id": result.stem, "path": str(result), "revision": run["revision"]},
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
            result, warning = finish(
                args.repo,
                args.run_id,
                args.final_phase,
                args.delivery_key,
                args.expect_revision,
            )
            print(result)
            if warning:
                print(warning, file=sys.stderr)
    except (StateError, StorageError, TelemetryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
