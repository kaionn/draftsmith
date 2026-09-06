#!/usr/bin/env python3
"""Read-only cross-run summary over the locally stored v1/v2 delivery receipts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from delivery_state import StateError
from git_storage import metadata_dir
from run_telemetry import TelemetryError, load_json, validate_receipt


SCHEMA_VERSION = 1
RECEIPT_DIR = "draftsmith-delivery-receipts"
UNKNOWN_KEY = "unknown"
# Only additive fields are summed. avg_context_tokens is a mean and max_context_tokens is an
# extremum, so adding either across receipts would produce a meaningless number.
COST_SUM_FIELDS = ("turns", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


def _count(bucket: dict[str, int], value: Any) -> None:
    """Count one receipt into a dimension bucket. Absent or non-string keys fall back."""
    key = value if isinstance(value, str) and value else UNKNOWN_KEY
    bucket[key] = bucket.get(key, 0) + 1


def _add_cost(roles: dict[str, dict[str, int]], cost: dict[str, Any]) -> None:
    """Fold one validated cost block into the per-role totals. Numbers and role enums only."""
    for role, metrics in cost.get("roles", {}).items():
        bucket = roles.get(role)
        if bucket is None:
            bucket = {field: 0 for field in COST_SUM_FIELDS}
            bucket["receipt_count"] = 0
            roles[role] = bucket
        bucket["receipt_count"] += 1
        for field in COST_SUM_FIELDS:
            bucket[field] += metrics.get(field, 0)


def summarize(receipt_dir: Path) -> dict[str, Any]:
    """Aggregate every readable receipt. A broken receipt is skipped and counted, never fatal."""
    lanes: dict[str, int] = {}
    goals: dict[str, int] = {}
    final_phases: dict[str, int] = {}
    roles: dict[str, dict[str, int]] = {}
    versions = {"v1": 0, "v2": 0}
    receipts_read = 0
    receipts_with_cost = 0
    skipped = 0
    paths = sorted(receipt_dir.glob("*.json")) if receipt_dir.is_dir() else []
    for path in paths:
        try:
            receipt = load_json(path)
        except TelemetryError:
            skipped += 1
            continue
        version = receipt.get("schema_version")
        # bool is a subclass of int and True == 1, so it is excluded explicitly. Any version
        # outside the two known schemas is an unknown receipt, not a v1 one.
        if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 2):
            skipped += 1
            continue
        if version == 2:
            # v1 predates this schema and has no validator in this codebase; it is accepted by
            # version alone. validate_receipt raises StateError, not TelemetryError, when a
            # timestamp is malformed (run_telemetry.py:188-189).
            try:
                validate_receipt(receipt)
            except (TelemetryError, StateError):
                skipped += 1
                continue
        receipts_read += 1
        versions["v2" if version == 2 else "v1"] += 1
        _count(lanes, receipt.get("lane"))
        _count(goals, receipt.get("goal"))
        _count(final_phases, receipt.get("final_phase"))
        cost = receipt.get("cost")
        if version == 2 and isinstance(cost, dict):
            # validate_receipt already checked the cost block shape for v2 receipts.
            receipts_with_cost += 1
            _add_cost(roles, cost)
    return {
        "read_only": True,
        "schema_version": SCHEMA_VERSION,
        "receipts_read": receipts_read,
        "skipped": skipped,
        "versions": versions,
        "lanes": lanes,
        "goals": goals,
        "final_phases": final_phases,
        "cost": {"receipts_with_cost": receipts_with_cost, "roles": roles},
    }


def summary(repo: str) -> dict[str, Any]:
    """Resolve this worktree's receipt directory and summarize it. Writes nothing."""
    return summarize(metadata_dir(repo, RECEIPT_DIR, create=False))
