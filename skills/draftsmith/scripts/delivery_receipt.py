#!/usr/bin/env python3
"""Compatibility entrypoint for legacy delivery receipt calls and v2 run telemetry."""

from __future__ import annotations

import argparse
import sys

from delivery_state import StateError, load, resolve
from git_storage import StorageError
from run_telemetry import (
    TelemetryError,
    finish,
    load_json,
    main,
    paths,
    start,
    validate_run,
)


def legacy_main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    try:
        _root, _branch, key, state_path = resolve(args.repo, None)
        state = load(state_path)
        runs, _receipts = paths(args.repo, create=False)
        active = sorted(runs.glob("*.json")) if runs.is_dir() else []
        if len(active) > 1:
            raise TelemetryError("multiple active telemetry runs exist in this worktree")
        if active:
            run_path = active[0]
            run = load_json(run_path)
            validate_run(run)
            if (run["entry"], run["goal"]) != (state["entry"], state["goal"]):
                raise TelemetryError("active telemetry run does not match delivery state")
        else:
            run_path = start(args.repo, "unknown", state["entry"], state["goal"])
            run = load_json(run_path)
        receipt, warnings = finish(
            args.repo, run["run_id"], state["phase"], key, run["revision"]
        )
        print(receipt)
        for warning in warnings:
            print(warning, file=sys.stderr)
    except (StateError, StorageError, TelemetryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    commands = {"start", "event", "finish"}
    raise SystemExit(main() if any(item in commands for item in sys.argv[1:]) else legacy_main())
