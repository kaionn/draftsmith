#!/usr/bin/env python3
"""Create a privacy-minimal delivery receipt from validated draftsmith state."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from delivery_state import load, parse_timestamp, resolve, run_git


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--key")
    args = parser.parse_args()
    root, _branch, key, state_path = resolve(args.repo, args.key)
    state = load(state_path)
    if state["phase"] not in {"review_complete", "merge_ready", "done"}:
        parser.error("receipt requires review_complete, merge_ready, or done state")
    elapsed = max(
        0,
        int((parse_timestamp(state["updated_at"]) - parse_timestamp(state["created_at"])).total_seconds()),
    )
    receipt = {
        "schema_version": 1,
        "key": key,
        "goal": state["goal"],
        "final_phase": state["phase"],
        "pr_number": state["pr_number"],
        "review_cycles": state["review_cycles"],
        "handled_review_count": len(state["handled_reviews"]),
        "metrics": state["metrics"],
        "elapsed_seconds": elapsed,
        "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    raw_dir = Path(run_git(root, "rev-parse", "--git-path", "draftsmith-delivery-receipts"))
    receipt_dir = raw_dir if raw_dir.is_absolute() else root / raw_dir
    output = receipt_dir.resolve() / f"{key}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    os.chmod(temp, 0o600)
    os.replace(temp, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
