#!/usr/bin/env python3
"""Persist, decide, and evaluate privacy-minimal draftsmith improvement proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from delivery_state import state_lock
from git_storage import StorageError, atomic_json, metadata_dir
from receipt_proposals import build


EVALUATION_WINDOW = 5
STATUSES = {"proposed", "accepted", "rejected", "evaluated"}


class ProposalError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def proposal_id(signal: str) -> str:
    return hashlib.sha256(signal.encode("utf-8")).hexdigest()[:16]


def proposal_dir(repo: str, *, create: bool) -> Path:
    return metadata_dir(repo, "draftsmith-improvement-proposals", create=create)


def receipt_summary(repo: str) -> dict[str, Any]:
    receipts = metadata_dir(repo, "draftsmith-delivery-receipts", create=False)
    return build(receipts)


def validate(payload: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "proposal_id",
        "signal",
        "target",
        "change",
        "expected_effect",
        "falsification",
        "status",
        "revision",
        "baseline",
        "decision",
        "evaluation",
    }
    if set(payload) != required or payload.get("schema_version") != 1:
        raise ProposalError("invalid proposal schema")
    if payload.get("proposal_id") != proposal_id(payload.get("signal", "")):
        raise ProposalError("invalid proposal id")
    if payload.get("status") not in STATUSES:
        raise ProposalError("invalid proposal status")
    if not isinstance(payload.get("revision"), int) or payload["revision"] < 0:
        raise ProposalError("invalid proposal revision")
    baseline = payload.get("baseline")
    if not isinstance(baseline, dict) or set(baseline) != {"receipts", "occurrences"}:
        raise ProposalError("invalid proposal baseline")
    if any(not isinstance(value, int) or value < 0 for value in baseline.values()):
        raise ProposalError("invalid proposal baseline counters")
    if payload["decision"] is not None and not isinstance(payload["decision"], dict):
        raise ProposalError("invalid proposal decision")
    if payload["evaluation"] is not None and not isinstance(payload["evaluation"], dict):
        raise ProposalError("invalid proposal evaluation")


def load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalError(f"cannot read proposal: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProposalError("proposal must be an object")
    validate(payload)
    return payload


def sync(repo: str) -> list[Path]:
    summary = receipt_summary(repo)
    output_dir = proposal_dir(repo, create=True)
    outputs: list[Path] = []
    for candidate in summary["proposals"]:
        identifier = proposal_id(candidate["signal"])
        path = output_dir / f"{identifier}.json"
        if path.exists():
            load(path)
            outputs.append(path)
            continue
        payload = {
            "schema_version": 1,
            "proposal_id": identifier,
            "signal": candidate["signal"],
            "target": candidate["target"],
            "change": {"before": candidate["before"], "after": candidate["after"]},
            "expected_effect": candidate["expected_effect"],
            "falsification": candidate["falsification"],
            "status": "proposed",
            "revision": 0,
            "baseline": {
                "receipts": summary["receipts_read"],
                "occurrences": candidate["evidence"]["receipt_count"],
            },
            "decision": None,
            "evaluation": None,
        }
        validate(payload)
        atomic_json(path, payload, immutable=True)
        outputs.append(path)
    return outputs


def update_decision(
    repo: str, identifier: str, decision: str, expected_revision: int
) -> Path:
    path = proposal_dir(repo, create=False) / f"{identifier}.json"
    with state_lock(path):
        payload = load(path)
        if payload["revision"] != expected_revision:
            raise ProposalError(
                f"revision conflict: expected {expected_revision}, current {payload['revision']}"
            )
        if payload["status"] != "proposed":
            raise ProposalError("only proposed improvements can be decided")
        if decision == "accepted":
            summary = receipt_summary(repo)
            occurrences = 0
            for candidate in summary["proposals"]:
                if candidate["signal"] == payload["signal"]:
                    occurrences = candidate["evidence"]["receipt_count"]
                    break
            payload["baseline"] = {
                "receipts": summary["receipts_read"],
                "occurrences": occurrences,
            }
        payload["status"] = decision
        payload["decision"] = {"decided_at": now(), "decision": decision}
        payload["revision"] += 1
        validate(payload)
        atomic_json(path, payload)
    return path


def evaluate(repo: str, identifier: str, expected_revision: int) -> Path:
    path = proposal_dir(repo, create=False) / f"{identifier}.json"
    with state_lock(path):
        payload = load(path)
        if payload["revision"] != expected_revision:
            raise ProposalError(
                f"revision conflict: expected {expected_revision}, current {payload['revision']}"
            )
        if payload["status"] != "accepted":
            raise ProposalError("only accepted improvements can be evaluated")
        summary = receipt_summary(repo)
        current_occurrences = 0
        for candidate in summary["proposals"]:
            if candidate["signal"] == payload["signal"]:
                current_occurrences = candidate["evidence"]["receipt_count"]
                break
        new_runs = summary["receipts_read"] - payload["baseline"]["receipts"]
        if new_runs < EVALUATION_WINDOW:
            outcome = "pending"
            withdraw_candidate = False
            post_occurrences = max(
                0, current_occurrences - payload["baseline"]["occurrences"]
            )
        else:
            post_occurrences = max(
                0, current_occurrences - payload["baseline"]["occurrences"]
            )
            baseline_receipts = max(1, payload["baseline"]["receipts"])
            baseline_rate = payload["baseline"]["occurrences"] / baseline_receipts
            post_rate = post_occurrences / new_runs
            outcome = "improved" if post_rate < baseline_rate else "no_improvement"
            withdraw_candidate = outcome == "no_improvement"
        payload["evaluation"] = {
            "evaluated_at": now(),
            "required_new_runs": EVALUATION_WINDOW,
            "observed_new_runs": max(0, new_runs),
            "post_occurrences": post_occurrences,
            "outcome": outcome,
            "withdraw_candidate": withdraw_candidate,
        }
        if outcome != "pending":
            payload["status"] = "evaluated"
        payload["revision"] += 1
        validate(payload)
        atomic_json(path, payload)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync")
    decide = commands.add_parser("decide")
    decide.add_argument("--proposal-id", required=True)
    decide.add_argument("--decision", choices=("accepted", "rejected"), required=True)
    decide.add_argument("--expect-revision", type=int, required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--proposal-id", required=True)
    evaluation.add_argument("--expect-revision", type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "sync":
            print(json.dumps([str(path) for path in sync(args.repo)], indent=2))
        elif args.command == "decide":
            print(update_decision(args.repo, args.proposal_id, args.decision, args.expect_revision))
        else:
            print(evaluate(args.repo, args.proposal_id, args.expect_revision))
    except (ProposalError, StorageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
