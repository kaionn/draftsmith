#!/usr/bin/env python3
"""diff-review の機械処理部分。unified diff の hunk 分割（split）と、
diff-analyzer が出した分類 JSON を検証して自己完結 HTML を組み立てる（build）。
stdlib のみで完結する。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any

HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
DIFF_GIT_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")
BINARY_LINE_RE = re.compile(r"^Binary files (.+) and (.+) differ$")

ALLOWED_RISKS = {"low", "caution", "danger"}
ALLOWED_SEVERITIES = {"warn", "info"}


def _strip_ab_prefix(raw: str | None) -> str | None:
    if raw is None:
        return None
    if raw == "/dev/null":
        return None
    if raw.startswith("a/") or raw.startswith("b/"):
        return raw[2:]
    return raw


def _split_diff_git_header(line: str) -> tuple[str | None, str | None]:
    m = DIFF_GIT_HEADER_RE.match(line)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _find_file_blocks(lines: list[str]) -> list[list[str]]:
    indices = [i for i, l in enumerate(lines) if l.startswith("diff --git ")]
    blocks = []
    for k, start in enumerate(indices):
        end = indices[k + 1] if k + 1 < len(indices) else len(lines)
        blocks.append(lines[start:end])
    return blocks


def _parse_header(block: list[str]) -> dict[str, Any]:
    """diff --git 行から最初の hunk ヘッダーまでの行を解析し、
    ファイル種別と旧/新パスを決定する。"""
    diff_git_line = block[0]
    fallback_a, fallback_b = _split_diff_git_header(diff_git_line)

    new_file = False
    deleted_file = False
    rename_from: str | None = None
    rename_to: str | None = None
    is_binary = False
    a_path_raw: str | None = None
    b_path_raw: str | None = None
    binary_a_raw: str | None = None
    binary_b_raw: str | None = None

    for line in block[1:]:
        if line.startswith("new file mode"):
            new_file = True
        elif line.startswith("deleted file mode"):
            deleted_file = True
        elif line.startswith("rename from "):
            rename_from = line[len("rename from "):]
        elif line.startswith("rename to "):
            rename_to = line[len("rename to "):]
        elif line.startswith("Binary files "):
            is_binary = True
            m = BINARY_LINE_RE.match(line)
            if m:
                binary_a_raw, binary_b_raw = m.group(1), m.group(2)
        elif line.startswith("--- "):
            a_path_raw = line[4:]
        elif line.startswith("+++ "):
            b_path_raw = line[4:]
        # old mode / new mode / similarity index / index ... は無視してよい

    a_path = _strip_ab_prefix(a_path_raw) or _strip_ab_prefix(binary_a_raw)
    b_path = _strip_ab_prefix(b_path_raw) or _strip_ab_prefix(binary_b_raw)

    if is_binary:
        status = "binary"
    elif rename_from is not None or rename_to is not None:
        status = "renamed"
    elif new_file:
        status = "added"
    elif deleted_file:
        status = "deleted"
    else:
        status = "modified"

    if status == "renamed":
        path = rename_to or b_path or fallback_b
        old_path = rename_from or a_path or fallback_a
    elif status == "added":
        path = b_path or fallback_b
        old_path = None
    elif status == "deleted":
        path = a_path or fallback_a
        old_path = None
    elif status == "binary":
        path = b_path or a_path or fallback_b or fallback_a
        old_path = rename_from
    else:  # modified
        path = b_path or fallback_b
        old_path = None

    return {"status": status, "path": path, "old_path": old_path}


def _parse_hunks(block: list[str], file_path: str, next_id: "list[int]") -> list[dict[str, Any]]:
    hunk_start_idx = None
    for idx, line in enumerate(block):
        if line.startswith("@@ "):
            hunk_start_idx = idx
            break
    if hunk_start_idx is None:
        return []

    hunk_lines = block[hunk_start_idx:]
    hunks: list[dict[str, Any]] = []
    i = 0
    n = len(hunk_lines)
    while i < n:
        line = hunk_lines[i]
        m = HUNK_HEADER_RE.match(line)
        if not m:
            i += 1
            continue
        old_ln = int(m.group(1))
        new_ln = int(m.group(3))
        header_text = line
        i += 1

        parsed_lines: list[dict[str, Any]] = []
        additions = 0
        deletions = 0
        while i < n and not hunk_lines[i].startswith("@@ "):
            cl = hunk_lines[i]
            if cl.startswith("\\"):
                parsed_lines.append({"t": "\\", "old": None, "new": None, "s": cl[1:].strip()})
            elif cl.startswith("+"):
                parsed_lines.append({"t": "+", "old": None, "new": new_ln, "s": cl[1:]})
                new_ln += 1
                additions += 1
            elif cl.startswith("-"):
                parsed_lines.append({"t": "-", "old": old_ln, "new": None, "s": cl[1:]})
                old_ln += 1
                deletions += 1
            elif cl.startswith(" "):
                parsed_lines.append({"t": " ", "old": old_ln, "new": new_ln, "s": cl[1:]})
                old_ln += 1
                new_ln += 1
            else:
                # 空行（trailing whitespace が失われた context 行）など想定外のものは
                # context として扱う（安全側のフォールバック）
                parsed_lines.append({"t": " ", "old": old_ln, "new": new_ln, "s": cl})
                old_ln += 1
                new_ln += 1
            i += 1

        hid = f"h{next_id[0]:03d}"
        next_id[0] += 1
        hunks.append(
            {
                "id": hid,
                "file": file_path,
                "header": header_text,
                "additions": additions,
                "deletions": deletions,
                "lines": parsed_lines,
            }
        )
    return hunks


def parse_diff(text: str, source: str) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    all_hunks: list[dict[str, Any]] = []
    next_id = [1]

    if text.strip() == "":
        lines: list[str] = []
    else:
        lines = text.splitlines()

    for block in _find_file_blocks(lines):
        header_info = _parse_header(block)
        files.append(
            {
                "path": header_info["path"],
                "status": header_info["status"],
                "old_path": header_info["old_path"] if header_info["status"] == "renamed" else None,
            }
        )
        if header_info["status"] == "binary":
            continue
        hunks = _parse_hunks(block, header_info["path"], next_id)
        all_hunks.extend(hunks)

    additions = sum(h["additions"] for h in all_hunks)
    deletions = sum(h["deletions"] for h in all_hunks)

    return {
        "source": source,
        "stats": {
            "files": len(files),
            "hunks": len(all_hunks),
            "additions": additions,
            "deletions": deletions,
        },
        "files": files,
        "hunks": all_hunks,
    }


def cmd_split(args: argparse.Namespace) -> int:
    diff_text = sys.stdin.read()
    result = parse_diff(diff_text, args.source)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    hunk_count = result["stats"]["hunks"]
    if hunk_count == 0:
        print(f"hunk が見つからなかった（差分なし）: {args.out}", file=sys.stderr)
    else:
        print(
            f"{args.out} に {result['stats']['files']} files / {hunk_count} hunks を書き出した",
            file=sys.stderr,
        )
    return 0


def _require_str_field(obj: dict[str, Any], field: str, label: str, warnings: list[str]) -> str:
    value = obj.get(field)
    if not isinstance(value, str) or value == "":
        warnings.append(f"{label} の {field} が欠落している。空文字で補った")
        return ""
    return value


def _normalize_risk(group: dict[str, Any], gid: str, warnings: list[str]) -> str:
    risk = group.get("risk")
    if risk not in ALLOWED_RISKS:
        warnings.append(f"risk が不正: {risk!r} (id={gid}) → caution に丸めた")
        return "caution"
    return risk


def _opt_str(f: dict[str, Any], field: str) -> str:
    value = f.get(field)
    return value if isinstance(value, str) else ""


def _normalize_findings(group: dict[str, Any], gid: str, warnings: list[str]) -> list[dict[str, Any]]:
    findings = group.get("findings")
    if not isinstance(findings, list):
        return []
    normalized = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        severity = f.get("severity")
        if severity not in ALLOWED_SEVERITIES:
            warnings.append(f"severity が不正: {severity!r} (id={gid}) → info に丸めた")
            severity = "info"
        text = _opt_str(f, "text")
        # title 欠落は旧形式（text のみ）との後方互換: text 先頭から補う
        title = _opt_str(f, "title") or (text[:30] + ("…" if len(text) > 30 else ""))
        normalized.append(
            {
                # フィードバック組み立て（採用/却下/コメント）の localStorage キーと
                # markdown 参照に使う安定 id
                "id": f"{gid}-f{len(normalized) + 1}",
                "severity": severity,
                "title": title,
                "text": text,
                "location": _opt_str(f, "location"),
                "suggestion": _opt_str(f, "suggestion"),
                "plan_note": _opt_str(f, "plan_note"),
            }
        )
    return normalized


def cmd_build(args: argparse.Namespace) -> int:
    try:
        with open(args.hunks, "r", encoding="utf-8") as f:
            hunks_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"hunks.json の読み込みに失敗した: {e}", file=sys.stderr)
        return 2

    try:
        with open(args.groups, "r", encoding="utf-8") as f:
            groups_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"groups.json のパースに失敗した: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"groups.json の読み込みに失敗した: {e}", file=sys.stderr)
        return 2

    if not isinstance(groups_data, dict) or "groups" not in groups_data:
        print("groups.json の形式が不正（'groups' キーがない）", file=sys.stderr)
        return 2

    hunk_by_id: dict[str, Any] = {h["id"]: h for h in hunks_data.get("hunks", [])}
    warnings: list[str] = []

    raw_groups = groups_data.get("groups")
    if not isinstance(raw_groups, list):
        print("groups.json の 'groups' がリストでない", file=sys.stderr)
        return 2

    # 未知 hunk id の検出
    unknown_ids: list[str] = []
    for g in raw_groups:
        for hid in g.get("hunks", []) or []:
            if hid not in hunk_by_id and hid not in unknown_ids:
                unknown_ids.append(hid)
    if unknown_ids:
        print("未知の hunk id: " + ", ".join(unknown_ids), file=sys.stderr)
        return 2

    # 重複割り当ての検出
    owner: dict[str, list[str]] = {}
    for g in raw_groups:
        gid = g.get("id", "")
        for hid in g.get("hunks", []) or []:
            owner.setdefault(hid, []).append(gid)
    duplicates = {hid: gids for hid, gids in owner.items() if len(gids) > 1}
    if duplicates:
        for hid, gids in duplicates.items():
            print(f"重複割り当て: {hid} ({', '.join(gids)})", file=sys.stderr)
        return 2

    # グループの正規化（risk / findings / title 等の語彙外・欠落補正）
    normalized_groups: list[dict[str, Any]] = []
    for g in raw_groups:
        gid = g.get("id", "")
        normalized_groups.append(
            {
                "id": gid,
                "title": _require_str_field(g, "title", f"group {gid}", warnings),
                "summary": _require_str_field(g, "summary", f"group {gid}", warnings),
                "intent": _require_str_field(g, "intent", f"group {gid}", warnings),
                "tags": g.get("tags") if isinstance(g.get("tags"), list) else [],
                "risk": _normalize_risk(g, gid, warnings),
                "plan_note": _opt_str(g, "plan_note"),
                "findings": _normalize_findings(g, gid, warnings),
                "hunks": list(g.get("hunks", []) or []),
            }
        )

    # 未割り当て hunk の検出 → g-rest への自動収容
    assigned_ids = set(owner.keys())
    all_ids = [h["id"] for h in hunks_data.get("hunks", [])]
    unassigned = [hid for hid in all_ids if hid not in assigned_ids]
    if unassigned:
        print("未分類の hunk id: " + ", ".join(unassigned), file=sys.stderr)
        normalized_groups.append(
            {
                "id": "g-rest",
                "title": "未分類",
                "summary": "diff-analyzer が分類しなかった hunk",
                "intent": "自動収容。内容を個別に確認すること。",
                "tags": ["chore"],
                "risk": "caution",
                "plan_note": "",
                "findings": [],
                "hunks": unassigned,
            }
        )

    review_title = _require_str_field(groups_data, "review_title", "review_title", warnings)

    for w in warnings:
        print(w, file=sys.stderr)

    hunks_dict = {h["id"]: h for h in hunks_data.get("hunks", [])}
    concat = "".join(h["id"] + h["header"] for h in hunks_data.get("hunks", []))
    state_key = hashlib.sha1(concat.encode("utf-8")).hexdigest()[:12]

    combined = {
        "review_title": review_title,
        "meta": {
            "source": hunks_data.get("source"),
            "stats": hunks_data.get("stats"),
            "files": hunks_data.get("files"),
            "state_key": state_key,
        },
        "groups": normalized_groups,
        "hunks": hunks_dict,
    }

    json_str = json.dumps(combined, ensure_ascii=False)
    json_str = json_str.replace("</", "<\\/")

    with open(args.template, "r", encoding="utf-8") as f:
        template = f.read()

    if "__REVIEW_DATA_JSON__" not in template:
        print("テンプレートに __REVIEW_DATA_JSON__ が見つからない", file=sys.stderr)
        return 2

    out_html = template.replace("__REVIEW_DATA_JSON__", json_str)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out_html)

    print(
        f"{os.path.abspath(args.out)} に groups={len(normalized_groups)} hunks={len(hunks_dict)} を書き込んだ",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="diff-review 用の hunk 分割 / HTML 生成")
    subparsers = parser.add_subparsers(dest="command", required=True)

    split_p = subparsers.add_parser("split", help="unified diff を hunk 単位に分割する")
    split_p.add_argument("--source", required=True)
    split_p.add_argument("--out", required=True)

    build_p = subparsers.add_parser("build", help="groups.json を検証して review.html を生成する")
    build_p.add_argument("--hunks", required=True)
    build_p.add_argument("--groups", required=True)
    build_p.add_argument("--template", required=True)
    build_p.add_argument("--out", required=True)

    args = parser.parse_args()

    if args.command == "split":
        return cmd_split(args)
    if args.command == "build":
        return cmd_build(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
