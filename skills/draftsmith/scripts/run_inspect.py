#!/usr/bin/env python3
"""Read-only doctor, status, and run-card views for draftsmith."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from delivery_state import StateError, load, resolve, resolve_routing
from git_storage import StorageError, metadata_dir, repository_root, run_git
from run_telemetry import TelemetryError, load_json, validate_receipt, validate_run


NEXT = {
    "implemented": "finish locally or request the next delivery goal",
    "commit_gate": "preview the exact commit and request authorization",
    "prepare_pr": "preview push and draft PR creation separately",
    "pr_open": "stop or observe required CI and reviews",
    "wait_ci_review": "wait for a new GitHub observation",
    "review_triage": "classify untrusted feedback against code and requirements",
    "review_fix": "apply and verify a scoped local correction",
    "final_verify": "verify the current full head against the rubric",
    "prepare_review_request": "preview reviewer and request text",
    "wait_human_review": "wait for human review",
    "review_complete": "stop or run the merge-ready verification",
    "merge_ready": "stop or request ready/merge gates separately",
    "merge_gate": "preview the exact merge operation",
    "done": "report the observed merged state",
    "blocked": "report the repeated blocker and request direction",
}


def doctor(repo: str) -> dict[str, object]:
    root = repository_root(repo)
    required = {
        "git": shutil.which("git") is not None,
        "python_3_10_or_newer": sys.version_info >= (3, 10),
    }
    optional = {
        "gh": shutil.which("gh") is not None,
        "jq": shutil.which("jq") is not None,
    }
    if optional["gh"]:
        auth = subprocess.run(
            ["gh", "auth", "status", "--hostname", "github.com"],
            check=False,
            capture_output=True,
            text=True,
        )
        optional["gh_authenticated"] = auth.returncode == 0
    else:
        optional["gh_authenticated"] = False
    skill_root = Path(__file__).resolve().parents[1]
    plugin_root = skill_root.parents[1]
    required_agents = ("designer", "auditor", "consultant", "implementer", "reviewer-light")
    required_references = ("full-lane", "light-lane", "artifacts", "delivery-loop")
    required_scripts = (
        "delivery_state.py",
        "run_telemetry.py",
        "run_inspect.py",
        "evidence_packet.py",
        "review_cockpit.py",
        "proposal_lifecycle.py",
    )
    required.update(
        {
            "draftsmith_skill": (skill_root / "SKILL.md").is_file(),
            "required_agents": all(
                (plugin_root / "agents" / f"{name}.md").is_file() for name in required_agents
            ),
            "required_references": all(
                (skill_root / "references" / f"{name}.md").is_file()
                for name in required_references
            ),
            "required_scripts": all(
                (skill_root / "scripts" / name).is_file() for name in required_scripts
            ),
            "templates": (skill_root / "templates" / "rubric.md").is_file(),
            "repository": bool(run_git(root, "rev-parse", "--is-inside-work-tree") == "true"),
        }
    )
    return {
        "read_only": True,
        "required": required,
        "optional": optional,
        "ready": all(required.values()),
    }


def status(repo: str) -> dict[str, object]:
    _root, _branch, _key, state_path = resolve(repo, None)
    if not state_path.is_file():
        runs_dir = metadata_dir(repo, "draftsmith-runs", create=False)
        active = sorted(runs_dir.glob("*.json")) if runs_dir.is_dir() else []
        if len(active) > 1:
            return {
                "read_only": True,
                "state": "ambiguous",
                "next": "resolve multiple active telemetry runs before continuing",
                "human_gate": "human_decision",
                "artifacts": [],
            }
        if active:
            run = load_json(active[0])
            validate_run(run)
            return {
                "read_only": True,
                "state": "inner_loop",
                "entry": run["entry"],
                "goal": run["goal"],
                "lane": run["lane"],
                "telemetry_revision": run["revision"],
                "next": "resume the selected lane from the last verified conversation checkpoint",
                "human_gate": "none",
                "artifacts": [],
            }
        receipts_dir = metadata_dir(repo, "draftsmith-delivery-receipts", create=False)
        receipts = sorted(
            receipts_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
        ) if receipts_dir.is_dir() else []
        for receipt_path in receipts:
            try:
                receipt = load_json(receipt_path)
                validate_receipt(receipt)
            except (OSError, TelemetryError):
                continue
            return {
                "read_only": True,
                "state": "completed",
                "entry": receipt["entry"],
                "goal": receipt["goal"],
                "lane": receipt["lane"],
                "final_phase": receipt["final_phase"],
                "next": "start a new run or inspect the immutable local receipt",
                "human_gate": "none",
                "artifacts": ["receipt"],
            }
        return {
            "read_only": True,
            "state": "not_started",
            "next": "resolve entry, goal, and lane; then initialize delivery_state explicitly",
            "human_gate": "none",
            "artifacts": [],
        }
    state = load(state_path)
    root = repository_root(repo)
    local_head = run_git(root, "rev-parse", "HEAD")
    saved_head = state["head_sha"]
    evidence_dir = metadata_dir(root, "draftsmith-artifacts/evidence", create=False)
    cockpit = metadata_dir(root, "draftsmith-artifacts/cockpits", create=False) / "review-cockpit.html"
    artifacts = [
        {"kind": "plan", "available": bool(state["plan_file"]), "path": state["plan_file"]},
        {"kind": "rubric", "available": "unknown"},
        {"kind": "diff-review", "available": "unknown"},
        {"kind": "verify-report", "available": "unknown"},
        {"kind": "evidence", "available": evidence_dir.is_dir() and any(evidence_dir.glob("*.json"))},
        {"kind": "review-cockpit", "available": cockpit.is_file()},
        {"kind": "delivery_state", "available": True},
    ]
    return {
        "read_only": True,
        "state": "active" if state["phase"] not in {"done", "blocked"} else state["phase"],
        "entry": state["entry"],
        "goal": state["goal"],
        "phase": state["phase"],
        "task": Path(state["plan_file"]).stem if state["plan_file"] else "unknown",
        "revision": state["revision"],
        "saved_head": saved_head,
        "local_head": local_head,
        "head_status": "unknown" if saved_head is None else ("current" if saved_head == local_head else "stale"),
        "github_observation": "not_checked",
        "next": NEXT[state["phase"]],
        "human_gate": state["pending_gate"],
        "artifacts": artifacts,
    }


def run_card(entry: str, goal: str | None, through_review: bool, lane: str) -> dict[str, object]:
    routing = resolve_routing(entry, goal, through_review)
    if lane == "unknown" and routing["entry"] != "delivery":
        raise StateError("unknown lane is reserved for delivery entry")
    references = [] if lane == "unknown" else [f"references/{lane}-lane.md"]
    if routing["entry"] == "delivery" or routing["goal"] != "implemented":
        references.append("references/delivery-loop.md")
    return {
        "read_only": True,
        **routing,
        "lane": lane,
        "references": references,
        "external_actions": [
            "commit requires current authorization",
            "push requires current authorization",
            "PR/review/ready/merge writes require separate current authorization",
        ],
        "artifacts": ["plan", "rubric", "receipt", "evidence", "review_cockpit"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("status")
    card = commands.add_parser("run-card")
    card.add_argument("--entry", choices=("requirements", "delivery"), default="requirements")
    card.add_argument("--goal", choices=("implemented", "pr_open", "review_requested", "review_complete", "merge_ready", "merged"))
    card.add_argument("--through-review", action="store_true")
    card.add_argument("--lane", choices=("full", "light", "unknown"), required=True)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            payload = doctor(args.repo)
        elif args.command == "status":
            payload = status(args.repo)
        else:
            payload = run_card(args.entry, args.goal, args.through_review, args.lane)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    except (StateError, StorageError, TelemetryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
