#!/usr/bin/env python3
"""Read v1/v2 receipts and emit proposal-only repeated-signal improvements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from git_storage import StorageError, metadata_dir
from run_telemetry import COUNTER_FIELDS, TelemetryError, validate_receipt


V1_METRICS = {
    "ci_failures": "ci_failures",
    "implementation_findings": "implementation_findings",
    "design_findings": "design_findings",
    "human_decisions": "human_decisions",
}
TARGETS = {
    "designer_rounds": "skill",
    "auditor_rounds": "skill",
    "reviewer_rounds": "driver",
    "light_to_full": "skill",
    "audit_traceability_miss": "rubric",
    "audit_adr_unjustified": "skill",
    "audit_prediction_divergence": "rubric",
    "audit_anchor_mismatch": "skill",
    "audit_scope_creep": "rubric",
    "audit_requirement_misread": "skill",
    "test_failures": "test",
    "ci_failures": "ci",
    "implementation_findings": "test",
    "design_findings": "skill",
    "human_decisions": "rubric",
    "delivery_ci_failures": "ci",
    "delivery_implementation_findings": "test",
    "delivery_design_findings": "skill",
    "delivery_human_decisions": "rubric",
    "delivery_reviewer_rounds": "driver",
}


def normalized_counters(payload: dict[str, Any]) -> dict[str, int] | None:
    version = payload.get("schema_version")
    if version == 2:
        try:
            validate_receipt(payload)
        except TelemetryError:
            return None
        result = dict(payload["counters"])
        result.update(
            {f"delivery_{key}": value for key, value in payload["delivery_counters"].items()}
        )
        return result
    if version == 1:
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict):
            return None
        result = {field: 0 for field in TARGETS}
        for old, new in V1_METRICS.items():
            value = metrics.get(old, 0)
            if not isinstance(value, int) or value < 0:
                return None
            result[f"delivery_{new}"] = value
        cycles = payload.get("review_cycles", 0)
        if isinstance(cycles, int) and cycles >= 0:
            result["delivery_reviewer_rounds"] = cycles
        return result
    return None


def build(receipt_dir: Path) -> dict[str, Any]:
    receipts: list[dict[str, int]] = []
    versions = {"v1": 0, "v2": 0}
    if receipt_dir.is_dir():
        for path in sorted(receipt_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(raw, dict):
                continue
            counters = normalized_counters(raw)
            if counters is None:
                continue
            versions[f"v{raw['schema_version']}"] += 1
            receipts.append(counters)
    proposals = []
    for counter in TARGETS:
        occurrences = sum(1 for item in receipts if item.get(counter, 0) > 0)
        if occurrences < 2:
            continue
        proposals.append(
            {
                "signal": counter,
                "target": TARGETS[counter],
                "evidence": {"receipt_count": occurrences},
                "before": f"{counter} recurs without a deterministic prevention gate",
                "after": f"add a targeted {TARGETS[counter]} check for the repeated condition",
                "expected_effect": f"reduce receipts containing {counter}",
                "falsification": f"the next measured runs do not reduce {counter}",
            }
        )
    return {"schema_version": 1, "receipts_read": len(receipts), "versions": versions, "proposals": proposals}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    try:
        receipt_dir = metadata_dir(args.repo, "draftsmith-delivery-receipts", create=False)
        print(json.dumps(build(receipt_dir), ensure_ascii=False, indent=2, sort_keys=True))
    except StorageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
