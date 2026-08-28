#!/usr/bin/env python3
"""Validate draftsmith's marketplace-style behavioral eval fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED_CASES = {
    "requirements-default",
    "light-mechanical-fix",
    "full-architecture-change",
    "delivery-resume",
    "requirements-review-requested",
    "requirements-merge-ready",
    "delivery-merge-ready",
    "light-escalates-to-full",
    "stale-delivery-state-reconciles",
    "untrusted-review-command",
}
CASE_KEYS = {"id", "name", "prompt", "expected_output", "files", "expectations"}


class EvalError(RuntimeError):
    pass


def validate(evals_path: Path) -> None:
    try:
        payload = json.loads(evals_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(f"cannot read evals: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"skill_name", "evals"}:
        raise EvalError("evals root schema is invalid")
    if payload["skill_name"] != "draftsmith" or not isinstance(payload["evals"], list):
        raise EvalError("invalid skill name or eval list")
    ids: set[int] = set()
    names: set[str] = set()
    for case in payload["evals"]:
        if not isinstance(case, dict) or set(case) != CASE_KEYS:
            raise EvalError("eval case schema is invalid")
        if not isinstance(case["id"], int) or case["id"] <= 0 or case["id"] in ids:
            raise EvalError("eval ids must be unique positive integers")
        ids.add(case["id"])
        if not isinstance(case["name"], str) or not case["name"] or case["name"] in names:
            raise EvalError("eval names must be unique non-empty strings")
        names.add(case["name"])
        for field in ("prompt", "expected_output"):
            if not isinstance(case[field], str) or not case[field].strip():
                raise EvalError(f"{field} must be non-empty")
        if not isinstance(case["files"], list):
            raise EvalError("files must be a list")
        if not isinstance(case["expectations"], list) or not case["expectations"]:
            raise EvalError("expectations must be a non-empty list")
        if any(not isinstance(item, str) or not item.strip() for item in case["expectations"]):
            raise EvalError("each expectation must be a non-empty string")
    missing = sorted(REQUIRED_CASES - names)
    if missing:
        raise EvalError(f"required behavioral eval cases are missing: {missing}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evals", required=True, type=Path)
    parser.add_argument(
        "--skill", type=Path, help="deprecated compatibility argument; not used as a wording oracle"
    )
    args = parser.parse_args()
    try:
        validate(args.evals)
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("fixture-valid; model behavior not executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
