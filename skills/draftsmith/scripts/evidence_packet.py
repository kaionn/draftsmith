#!/usr/bin/env python3
"""Build a fresh-head, AC-complete local evidence packet without posting it."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import secrets
import sys
from pathlib import Path
from typing import Any

from git_storage import StorageError, atomic_json, atomic_text, metadata_dir, repository_root, run_git


OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
AC_ID_RE = re.compile(r"AC-[1-9][0-9]*")
STATUSES = {"pass", "fail", "needs_human"}


class EvidenceError(RuntimeError):
    pass


def validate_summary(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{field} must be a non-empty string")
    if len(value) > 500 or "\n" in value or "\r" in value:
        raise EvidenceError(f"{field} must be a concise single-line summary, not a raw log")
    if str(Path.home()) in value:
        raise EvidenceError(f"{field} must not contain an absolute home path")


def canonical_digest(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "digest"}
    raw = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_input(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise EvidenceError("symlinked evidence input is not allowed")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read evidence input: {exc}") from exc
    if not isinstance(payload, dict):
        raise EvidenceError("evidence input must be an object")
    required = {"acceptance_criteria", "results", "not_covered", "verification", "risks"}
    if set(payload) != required:
        raise EvidenceError("evidence input has unexpected or missing keys")
    return payload


def validate_input(payload: dict[str, Any]) -> None:
    for field in ("acceptance_criteria", "results", "not_covered", "verification", "risks"):
        if not isinstance(payload[field], list):
            raise EvidenceError(f"{field} must be a list")
    declared: set[str] = set()
    for item in payload["acceptance_criteria"]:
        if not isinstance(item, dict) or set(item) != {"id", "criterion"}:
            raise EvidenceError("acceptance criteria require id and criterion")
        if not AC_ID_RE.fullmatch(item["id"]):
            raise EvidenceError("invalid acceptance criterion")
        validate_summary(item["criterion"], "criterion")
        if item["id"] in declared:
            raise EvidenceError("duplicate acceptance criterion id")
        declared.add(item["id"])
    covered: set[str] = set()
    for item in payload["results"]:
        if not isinstance(item, dict) or set(item) != {"id", "status", "summary"}:
            raise EvidenceError("results require id, status, and summary")
        if item["status"] not in STATUSES:
            raise EvidenceError("invalid result")
        validate_summary(item["summary"], "result summary")
        if item["id"] in covered:
            raise EvidenceError("duplicate AC result")
        covered.add(item["id"])
    for item in payload["not_covered"]:
        if not isinstance(item, dict) or set(item) != {"id", "reason"}:
            raise EvidenceError("not_covered entries require id and reason")
        validate_summary(item["reason"], "not_covered reason")
        if item["id"] in covered:
            raise EvidenceError("an AC must appear exactly once across results and not_covered")
        covered.add(item["id"])
    if covered != declared:
        raise EvidenceError(f"AC coverage mismatch: missing={sorted(declared - covered)}, unknown={sorted(covered - declared)}")
    for item in payload["verification"]:
        if not isinstance(item, dict) or set(item) != {"kind", "status", "summary"}:
            raise EvidenceError("verification entries require kind, status, and summary")
        if item["status"] not in {"pass", "fail", "not_run"}:
            raise EvidenceError("invalid verification status")
        validate_summary(item["kind"], "verification kind")
        validate_summary(item["summary"], "verification summary")
    for index, item in enumerate(payload["risks"]):
        validate_summary(item, f"risk {index + 1}")


def markdown_cell(value: str) -> str:
    return html.escape(value, quote=False).replace("\\", "\\\\").replace("|", "\\|")


def markdown_text(value: str) -> str:
    return html.escape(value, quote=False)


def render_markdown(packet: dict[str, Any]) -> str:
    lines = [
        "# draftsmith verification evidence",
        "",
        f"- Target head: `{packet['verified_head']}`",
        "",
        "## Acceptance criteria",
        "",
        "| AC | Result | Evidence |",
        "|---|---|---|",
    ]
    results = {item["id"]: item for item in packet["results"]}
    not_covered = {item["id"]: item for item in packet["not_covered"]}
    for criterion in packet["acceptance_criteria"]:
        ac_id = criterion["id"]
        if ac_id in results:
            result = results[ac_id]
            status = result["status"].upper()
            summary = result["summary"]
        else:
            status = "NOT COVERED"
            summary = not_covered[ac_id]["reason"]
        lines.append(
            f"| {markdown_cell(ac_id)} | {markdown_cell(status)} | {markdown_cell(summary)} |"
        )
    lines.extend(["", "## Verification", ""])
    for item in packet["verification"]:
        lines.append(
            f"- **{markdown_text(item['kind'])} — {item['status'].upper()}**: "
            f"{markdown_text(item['summary'])}"
        )
    lines.extend(["", "## Not covered", ""])
    if packet["not_covered"]:
        for item in packet["not_covered"]:
            lines.append(f"- **{item['id']}**: {markdown_text(item['reason'])}")
    else:
        lines.append("- None")
    lines.extend(["", "## Risks / follow-ups", ""])
    if packet["risks"]:
        lines.extend(f"- {markdown_text(item)}" for item in packet["risks"])
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def build(repo: str, input_path: Path, pr_head: str) -> Path:
    root = repository_root(repo)
    head = run_git(root, "rev-parse", "HEAD")
    if not OID_RE.fullmatch(head):
        raise EvidenceError("local HEAD must be a full 40 or 64 character object id")
    if not OID_RE.fullmatch(pr_head) or pr_head != head:
        raise EvidenceError("caller-supplied PR head must be a full object id matching local HEAD")
    if run_git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise EvidenceError("fresh evidence requires a clean working tree")
    source = load_input(input_path)
    validate_input(source)
    evidence_id = secrets.token_hex(16)
    packet = {
        "schema_version": 1,
        "evidence_id": evidence_id,
        "verified_head": head,
        "pr_head": pr_head,
        "created_from_clean_matching_heads": True,
        "packet_file": f"{evidence_id}.md",
        **source,
    }
    markdown_content = render_markdown(packet)
    packet["packet_sha256"] = hashlib.sha256(markdown_content.encode("utf-8")).hexdigest()
    packet["digest"] = canonical_digest(packet)
    output_dir = metadata_dir(root, "draftsmith-artifacts/evidence", create=True)
    output = output_dir / f"{packet['evidence_id']}.json"
    markdown = output_dir / packet["packet_file"]
    atomic_text(markdown, markdown_content, immutable=True)
    atomic_json(output, packet, immutable=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--pr-head", required=True)
    args = parser.parse_args()
    try:
        print(build(args.repo, args.input, args.pr_head))
    except (EvidenceError, StorageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
