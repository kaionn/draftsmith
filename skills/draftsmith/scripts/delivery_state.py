#!/usr/bin/env python3
"""Manage re-entrant delivery state for draftsmith's optional PR lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 1
ENTRIES = ("requirements", "delivery")
GOALS = ("implemented", "pr_open", "review_requested", "review_complete", "merge_ready")
PHASES = (
    "implemented",
    "commit_gate",
    "prepare_pr",
    "pr_open",
    "wait_ci_review",
    "review_triage",
    "review_fix",
    "final_verify",
    "prepare_review_request",
    "wait_human_review",
    "review_complete",
    "merge_ready",
    "done",
    "blocked",
)
GATES = (
    "none",
    "commit",
    "push",
    "pr_create",
    "pr_update",
    "ready",
    "github_comment",
    "review_reply",
    "thread_resolve",
    "slack_post",
    "approve",
    "merge",
    "human_decision",
)
OBSERVATIONS = (
    "none",
    "no_pr",
    "pr_open",
    "ci_pending",
    "ci_failed",
    "ci_green",
    "bot_feedback",
    "human_feedback",
    "verification_failed",
    "verification_passed",
    "review_requested",
    "review_complete",
    "human_decision",
    "pr_closed",
    "pr_merged",
)
FORWARD = {
    "implemented": {"commit_gate"},
    "commit_gate": {"prepare_pr", "wait_ci_review"},
    "prepare_pr": {"pr_open"},
    "pr_open": {"wait_ci_review"},
    "wait_ci_review": {"review_triage", "final_verify"},
    "review_triage": {"review_fix", "wait_human_review", "final_verify"},
    "review_fix": {"commit_gate"},
    "final_verify": {"prepare_review_request", "review_complete", "merge_ready"},
    "prepare_review_request": {"wait_human_review"},
    "wait_human_review": {"review_triage", "review_complete"},
    "review_complete": {"final_verify"},
    "merge_ready": {"review_triage", "done"},
    "done": set(),
    "blocked": set(PHASES) - {"done"},
}
SHA_RE = re.compile(r"[0-9a-f]{7,64}")


class StateError(RuntimeError):
    pass


def run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
        raise StateError(message)
    return proc.stdout.strip()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_key(branch: str) -> str:
    label = re.sub(r"[^a-zA-Z0-9._-]+", "-", branch).strip("-._") or "detached"
    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:10]
    return f"{label[:64]}-{digest}"


def validate_plan_file(value: str | None) -> None:
    if value is None:
        return
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 2:
        raise StateError("plan_file must be a direct child of plans/")
    if path.parts[0] != "plans" or path.suffix != ".md" or path.name in {".", ".."}:
        raise StateError("plan_file must match plans/<name>.md")


def validate_sha(value: str | None, field: str) -> None:
    if value is not None and not SHA_RE.fullmatch(value):
        raise StateError(f"{field} must be null or a 7-64 character lowercase hex SHA")


def resolve(repo_arg: str, key_arg: str | None) -> tuple[Path, str, str, Path]:
    repo = Path(repo_arg).expanduser().resolve()
    root = Path(run_git(repo, "rev-parse", "--show-toplevel")).resolve()
    branch = run_git(root, "branch", "--show-current")
    if not branch:
        branch = f"detached-{run_git(root, 'rev-parse', '--short=12', 'HEAD')}"
    key = key_arg or safe_key(branch)
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,96}", key):
        raise StateError("key must contain only letters, digits, dot, underscore, or hyphen")
    raw_dir = Path(run_git(root, "rev-parse", "--git-path", "draftsmith-delivery"))
    state_dir = raw_dir if raw_dir.is_absolute() else root / raw_dir
    return root, branch, key, state_dir.resolve() / f"{key}.json"


def validate_state(state: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "key",
        "branch",
        "entry",
        "goal",
        "phase",
        "plan_file",
        "design_commit",
        "pr_number",
        "head_sha",
        "pending_gate",
        "last_observation",
        "review_cycles",
        "revision",
        "created_at",
        "updated_at",
    }
    if set(state) != required:
        missing = sorted(required - set(state))
        extra = sorted(set(state) - required)
        raise StateError(f"invalid state keys: missing={missing}, extra={extra}")
    if state["schema_version"] != SCHEMA_VERSION:
        raise StateError(f"unsupported schema_version: {state['schema_version']}")
    if state["entry"] not in ENTRIES or state["goal"] not in GOALS or state["phase"] not in PHASES:
        raise StateError("invalid entry, goal, or phase")
    if state["entry"] == "delivery" and state["goal"] == "implemented":
        raise StateError("delivery entry requires a goal after implemented")
    if state["pending_gate"] not in GATES or state["last_observation"] not in OBSERVATIONS:
        raise StateError("invalid pending_gate or last_observation")
    validate_plan_file(state["plan_file"])
    validate_sha(state["design_commit"], "design_commit")
    validate_sha(state["head_sha"], "head_sha")
    if state["pr_number"] is not None and (
        not isinstance(state["pr_number"], int) or state["pr_number"] <= 0
    ):
        raise StateError("pr_number must be null or a positive integer")
    if not isinstance(state["review_cycles"], int) or state["review_cycles"] < 0:
        raise StateError("review_cycles must be a non-negative integer")
    if not isinstance(state["revision"], int) or state["revision"] < 0:
        raise StateError("revision must be a non-negative integer")
    if not isinstance(state["key"], str) or not isinstance(state["branch"], str):
        raise StateError("key and branch must be strings")


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StateError(f"state not found: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state: {exc}") from exc
    if not isinstance(state, dict):
        raise StateError("state must be a JSON object")
    validate_state(state)
    return state


def write_atomic(path: Path, state: dict[str, Any]) -> None:
    validate_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


@contextmanager
def state_lock(path: Path):
    """Take a non-blocking cross-process lock next to the state file."""
    lock_path = path.with_suffix(f"{path.suffix}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        os.chmod(lock_path, 0o600)
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise StateError(f"delivery state is locked by another updater: {lock_path}") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise StateError(f"delivery state is locked by another updater: {lock_path}") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def output(state: dict[str, Any]) -> None:
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


def resolve_routing(entry: str, goal: str | None, through_review: bool) -> dict[str, str]:
    if through_review:
        if entry == "delivery":
            raise StateError("--through-review conflicts with delivery entry")
        if goal is not None and goal != "review_complete":
            raise StateError("--through-review conflicts with an explicit goal other than review_complete")
        entry = "requirements"
        goal = "review_complete"
    elif goal is None:
        goal = "review_complete" if entry == "delivery" else "implemented"
    if entry == "delivery" and goal == "implemented":
        raise StateError("delivery entry requires a goal after implemented")
    return {"entry": entry, "goal": goal}


def command_init(args: argparse.Namespace, path: Path, branch: str, key: str) -> None:
    with state_lock(path):
        if path.exists():
            output(load(path))
            return
        now = utc_now()
        state = {
            "schema_version": SCHEMA_VERSION,
            "key": key,
            "branch": branch,
            "entry": args.entry,
            "goal": args.goal,
            "phase": args.phase,
            "plan_file": args.plan_file,
            "design_commit": args.design_commit,
            "pr_number": args.pr_number,
            "head_sha": args.head_sha,
            "pending_gate": "none",
            "last_observation": "none",
            "review_cycles": 0,
            "revision": 0,
            "created_at": now,
            "updated_at": now,
        }
        write_atomic(path, state)
    output(state)


def command_update(args: argparse.Namespace, path: Path) -> None:
    with state_lock(path):
        state = load(path)
        if args.expect_revision != state["revision"]:
            raise StateError(
                f"revision conflict: expected {args.expect_revision}, current {state['revision']}"
            )
        changed = False
        if args.phase is not None:
            current = state["phase"]
            allowed = FORWARD[current] | {current, "blocked"}
            observed_merged = args.phase == "done" and args.observation == "pr_merged"
            if args.phase == "done" and not observed_merged:
                raise StateError("done requires --observation pr_merged")
            if args.phase not in allowed and not observed_merged:
                raise StateError(f"invalid transition: {current} -> {args.phase}")
            state["phase"] = args.phase
            changed = True
        for argument, field in (
            (args.goal, "goal"),
            (args.plan_file, "plan_file"),
            (args.design_commit, "design_commit"),
            (args.pr_number, "pr_number"),
            (args.head_sha, "head_sha"),
            (args.pending_gate, "pending_gate"),
            (args.observation, "last_observation"),
        ):
            if argument is not None:
                state[field] = argument
                changed = True
        if args.increment_review_cycles:
            if state["review_cycles"] >= 3:
                raise StateError("review cycle limit reached; move the delivery state to blocked")
            state["review_cycles"] += 1
            changed = True
        if not changed:
            raise StateError("update requires at least one changed field")
        state["revision"] += 1
        state["updated_at"] = utc_now()
        write_atomic(path, state)
    output(state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="path inside the target git repository")
    parser.add_argument("--key", help="optional stable state key; defaults to current branch")
    commands = parser.add_subparsers(dest="command", required=True)

    resolve_parser = commands.add_parser("resolve", help="resolve entry and goal without writing state")
    resolve_parser.add_argument("--entry", choices=ENTRIES, default="requirements")
    resolve_parser.add_argument("--goal", choices=GOALS)
    resolve_parser.add_argument("--through-review", action="store_true")

    init_parser = commands.add_parser("init", help="create state if missing; otherwise show it")
    init_parser.add_argument("--entry", choices=ENTRIES, default="requirements")
    init_parser.add_argument("--goal", choices=GOALS, default="implemented")
    init_parser.add_argument("--phase", choices=PHASES, default="implemented")
    init_parser.add_argument("--plan-file")
    init_parser.add_argument("--design-commit")
    init_parser.add_argument("--pr-number", type=int)
    init_parser.add_argument("--head-sha")

    commands.add_parser("show", help="show and validate current state")
    commands.add_parser("validate", help="validate current state")
    commands.add_parser("path", help="print the resolved state path")

    update_parser = commands.add_parser("update", help="apply a validated state transition")
    update_parser.add_argument("--expect-revision", type=int, required=True)
    update_parser.add_argument("--phase", choices=PHASES)
    update_parser.add_argument("--goal", choices=GOALS)
    update_parser.add_argument("--plan-file")
    update_parser.add_argument("--design-commit")
    update_parser.add_argument("--pr-number", type=int)
    update_parser.add_argument("--head-sha")
    update_parser.add_argument("--pending-gate", choices=GATES)
    update_parser.add_argument("--observation", choices=OBSERVATIONS)
    update_parser.add_argument("--increment-review-cycles", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        _root, branch, key, path = resolve(args.repo, args.key)
        if args.command == "resolve":
            print(json.dumps(resolve_routing(args.entry, args.goal, args.through_review), sort_keys=True))
        elif args.command == "path":
            print(path)
        elif args.command == "init":
            command_init(args, path, branch, key)
        elif args.command == "show":
            output(load(path))
        elif args.command == "validate":
            state = load(path)
            print(f"valid schema={state['schema_version']} phase={state['phase']} key={state['key']}")
        elif args.command == "update":
            command_update(args, path)
    except StateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
