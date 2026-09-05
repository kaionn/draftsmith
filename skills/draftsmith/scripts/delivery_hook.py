#!/usr/bin/env python3
"""Claude Code hook entry for draftsmith's delivery park/resume loop.

Hooks must never block ordinary work, so every failure path here exits 0 with no stdout. Stop runs
at the end of every turn, so both hooks decide whether they have anything to do by reading the
state files directly, and import delivery_state only once they are going to produce output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_DIR_NAME = "draftsmith-delivery"
# Claude Code caps hook output strings at 10000 characters. delivery_state caps the note at 8000,
# which leaves room for the brief header and the reconcile checklist.
MAX_OUTPUT_CHARS = 10000
# Phases whose next input is external and may arrive after the prompt cache expires.
REMINDER_PHASES = ("wait_human_review", "review_complete", "merge_ready")
# Duplicated from delivery_state.PARK_PHASES so the no-work path stays import-free.
# tests/test_hooks.py asserts the two stay in step.
PARKABLE_PHASES = (
    "wait_ci_review",
    "wait_human_review",
    "review_complete",
    "merge_ready",
    "blocked",
)
# The paths are filled in from SCRIPT_DIR: as an installed plugin the hook's cwd is the user's
# project, where a repo-relative path to draftsmith's own files does not exist.
PARK_REASON = (
    "This worktree has an unparked draftsmith delivery run in phase {phase}. "
    "The next input is external, so park before ending the session:\n"
    "1. Write the handoff note from {template}: decisions and "
    "rejected options, the checks you actually ran with their output, known gaps, the event you "
    "are waiting for, and the round number. No secrets, no customer data, no pasted PR text.\n"
    "2. Run: python3 {script} --repo . park "
    "--expect-revision {revision} --note-file <path>   (use - to read the note from stdin).\n"
    "3. After park succeeds you may close this session. The next session gets the note back "
    "automatically from the SessionStart hook."
)


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def state_dir(cwd: str) -> Path | None:
    """Locate the state directory with one git call and one stat, without importing anything."""
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--absolute-git-dir"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    candidate = Path(out) / STATE_DIR_NAME
    try:
        return candidate if candidate.is_dir() else None
    except OSError:
        return None


def raw_states(cwd: str) -> list[dict]:
    """Read the state files as plain JSON.

    This is a hint, not a source of truth. It decides whether the hook has anything to do before
    paying for the delivery_state import plus resolve()'s git calls, and anything it lets through
    is re-checked against the loaded, validated state afterwards.
    """
    directory = state_dir(cwd)
    if directory is None:
        return []
    try:
        files = sorted(directory.glob("*.json"))
    except OSError:
        return []
    states = []
    for candidate in files:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            states.append(data)
    return states


def load_state_module():
    """Import delivery_state lazily: the common no-work path must not pay for it."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    import delivery_state

    return delivery_state


def park_reason(state: dict, revision: int) -> str:
    return PARK_REASON.format(
        phase=state["phase"],
        revision=revision,
        template=SCRIPT_DIR.parent / "templates" / "park-note.md",
        script=SCRIPT_DIR / "delivery_state.py",
    )


def session_start(payload: dict) -> None:
    cwd = payload.get("cwd") or "."
    resumable = [
        state
        for state in raw_states(cwd)
        if state.get("phase") in PARKABLE_PHASES and state.get("parked_head_sha")
    ]
    if not resumable:
        return
    delivery_state = load_state_module()
    root, _branch, _key, path = delivery_state.resolve(cwd, None)
    if not path.is_file():
        return
    state = delivery_state.load(path)
    if not delivery_state.is_resumable(state):
        return
    context = delivery_state.build_resume_brief(state, path, root)[:MAX_OUTPUT_CHARS]
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            },
            ensure_ascii=False,
        )
    )


def stop(payload: dict) -> None:
    if payload.get("stop_hook_active") is True:
        return
    cwd = payload.get("cwd") or "."
    if not any(state.get("phase") in REMINDER_PHASES for state in raw_states(cwd)):
        return
    delivery_state = load_state_module()
    root, _branch, _key, path = delivery_state.resolve(cwd, None)
    if not path.is_file():
        return
    state = delivery_state.load(path)
    if state["phase"] not in REMINDER_PHASES:
        return
    head_sha = delivery_state.run_git(root, "rev-parse", "HEAD")
    # Both halves are needed: review round trips move the state without moving HEAD, and commits
    # move HEAD without going through the state.
    parked = state["parked_revision"] == state["revision"] and delivery_state.sha_matches(
        state["parked_head_sha"], head_sha
    )
    if parked:
        return
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": park_reason(state, state["revision"])[:MAX_OUTPUT_CHARS],
            },
            ensure_ascii=False,
        )
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("session-start", "stop"):
        return 0
    payload = read_payload()
    try:
        if argv[1] == "session-start":
            session_start(payload)
        else:
            stop(payload)
    except Exception:  # noqa: BLE001 - a hook must never break the session it runs in
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
