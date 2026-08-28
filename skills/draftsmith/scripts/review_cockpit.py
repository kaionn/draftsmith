#!/usr/bin/env python3
"""Generate an escaped local index of existing draftsmith review artifacts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from evidence_packet import canonical_digest
from git_storage import StorageError, metadata_dir, repository_root, run_git


KINDS = {"plan", "rubric", "diff-review", "verify-report", "evidence"}
OID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class CockpitError(RuntimeError):
    pass


def safe_path(raw: str, repo_root: Path, roots: list[Path]) -> tuple[Path, str]:
    source = Path(raw).expanduser()
    if ".." in source.parts:
        raise CockpitError("artifact path traversal is not allowed")
    candidate = source if source.is_absolute() else repo_root / source
    absolute = candidate.absolute()
    for part in [absolute, *absolute.parents]:
        if part.exists() and part.is_symlink():
            raise CockpitError("symlinked artifact paths are not allowed")
    resolved = candidate.resolve(strict=True)
    for index, root in enumerate(roots):
        try:
            relative = resolved.relative_to(root)
            label = f"repo/{relative.as_posix()}" if index == 0 else f"allowed-{index}/{relative.as_posix()}"
            return resolved, label
        except ValueError:
            continue
    raise CockpitError("artifact path is outside the allowlisted roots")


def freshness(path: Path, head: str, pr_head: str | None) -> tuple[str, Path]:
    if path.suffix != ".json":
        return "unknown", path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown", path
    if not isinstance(payload, dict) or "verified_head" not in payload or "digest" not in payload:
        return "unknown", path
    if payload["digest"] != canonical_digest(payload):
        return "stale", path
    display = path
    packet_file = payload.get("packet_file")
    if isinstance(packet_file, str) and Path(packet_file).name == packet_file:
        candidate = path.parent / packet_file
        if candidate.is_file() and not candidate.is_symlink():
            packet_hash = payload.get("packet_sha256")
            actual_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if not isinstance(packet_hash, str) or packet_hash != actual_hash:
                return "stale", candidate
            display = candidate
    if pr_head is None:
        return "unknown", display
    return (
        "fresh" if payload["verified_head"] == head == pr_head else "stale"
    ), display


def build(
    repo: str, index_path: Path, allow_roots: list[Path], pr_head: str | None
) -> Path:
    root = repository_root(repo)
    metadata = metadata_dir(root, "draftsmith-artifacts", create=True)
    roots = [root.resolve(), metadata.resolve()]
    for item in allow_roots:
        if item.is_symlink():
            raise CockpitError("symlinked allowlist roots are not allowed")
        roots.append(item.expanduser().resolve(strict=True))
    safe_index, _label = safe_path(str(index_path), root, roots)
    try:
        manifest = json.loads(safe_index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CockpitError(f"cannot read cockpit index: {exc}") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"artifacts"} or not isinstance(manifest["artifacts"], list):
        raise CockpitError("cockpit index must contain only an artifacts list")
    head = run_git(root, "rev-parse", "HEAD")
    if pr_head is not None and not OID_RE.fullmatch(pr_head):
        raise CockpitError("PR head must be a full 40 or 64 character object id")
    output_dir = metadata_dir(root, "draftsmith-artifacts/cockpits", create=True)
    output = output_dir / "review-cockpit.html"
    rows = []
    for item in manifest["artifacts"]:
        if not isinstance(item, dict) or set(item) != {"kind", "path"} or item["kind"] not in KINDS:
            raise CockpitError("invalid cockpit artifact entry")
        path, _label = safe_path(item["path"], root, roots)
        state, display = freshness(path, head, pr_head)
        display, label = safe_path(str(display), root, roots)
        href = os.path.relpath(display, output.parent)
        rows.append((item["kind"], label, href, state))
    row_html = "\n".join(
        f"<tr><td>{html.escape(kind)}</td><td><a href=\"{html.escape(href, quote=True)}\"><code>{html.escape(label)}</code></a></td>"
        f"<td class=\"{html.escape(state)}\">{html.escape(state)}</td></tr>"
        for kind, label, href, state in rows
    )
    document = f"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><title>draftsmith review cockpit</title>
<style>body{{font:16px system-ui;max-width:960px;margin:2rem auto;padding:0 1rem}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #bbb;padding:.6rem;text-align:left}}.fresh{{color:#176b2c}}.stale{{color:#a11}}.unknown{{color:#765b00}}</style>
<h1>draftsmith review cockpit</h1>
<p>既存成果物への索引。判定は各成果物の正本を参照する。</p>
<table><thead><tr><th>kind</th><th>local path</th><th>freshness</th></tr></thead><tbody>{row_html}</tbody></table>
</html>"""
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(document, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
        os.chmod(output, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--allow-root", action="append", default=[], type=Path)
    parser.add_argument("--pr-head")
    args = parser.parse_args()
    try:
        print(build(args.repo, args.index, args.allow_root, args.pr_head))
    except (CockpitError, StorageError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
