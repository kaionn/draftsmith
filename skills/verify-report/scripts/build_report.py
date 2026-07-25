#!/usr/bin/env python3
"""verify-report の機械処理部分。evidence.json（AC + スクショ台帳）と
evidence-reviewer の verdicts.json を検証し、スクショを data URI で埋め込んだ
自己完結 HTML レポートを組み立てる。stdlib のみで完結する。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from typing import Any

ALLOWED_VERDICTS = {"pass", "fail", "needs_human"}
MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _load_json(path: str, label: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"{label} の読み込みに失敗した: {e}", file=sys.stderr)
        sys.exit(2)


def _data_uri(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime = MIME_BY_EXT.get(ext)
    if mime is None:
        print(f"未対応の画像形式: {path}", file=sys.stderr)
        sys.exit(2)
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def cmd_build(args: argparse.Namespace) -> int:
    evidence = _load_json(args.evidence, "evidence.json")
    verdicts_data = _load_json(args.verdicts, "verdicts.json")

    acs = evidence.get("acs")
    shots = evidence.get("screenshots")
    if not isinstance(acs, list) or not acs:
        print("evidence.json の 'acs' が空またはリストでない", file=sys.stderr)
        return 2
    if not isinstance(shots, list):
        print("evidence.json の 'screenshots' がリストでない", file=sys.stderr)
        return 2

    ac_ids = [a.get("id") for a in acs]
    shot_ids = {s.get("id") for s in shots}

    raw_verdicts = verdicts_data.get("verdicts")
    if not isinstance(raw_verdicts, list):
        print("verdicts.json の 'verdicts' がリストでない", file=sys.stderr)
        return 2

    # 被覆検証: 全 AC に判定が 1 つずつ / 未知 AC / 未知スクショ id
    errors: list[str] = []
    seen: dict[str, int] = {}
    for v in raw_verdicts:
        ac = v.get("ac")
        if ac not in ac_ids:
            errors.append(f"未知の AC id: {ac!r}")
            continue
        seen[ac] = seen.get(ac, 0) + 1
        if v.get("verdict") not in ALLOWED_VERDICTS:
            errors.append(f"verdict が不正: {v.get('verdict')!r} ({ac})")
        for sid in v.get("evidence", []) or []:
            if sid not in shot_ids:
                errors.append(f"未知のスクショ id: {sid!r} ({ac})")
    for ac_id in ac_ids:
        n = seen.get(ac_id, 0)
        if n == 0:
            errors.append(f"判定が無い AC: {ac_id}")
        elif n > 1:
            errors.append(f"判定が重複した AC: {ac_id} ({n} 件)")

    extra = verdicts_data.get("extra_findings")
    extra_findings: list[dict[str, Any]] = []
    if isinstance(extra, list):
        for e in extra:
            if not isinstance(e, dict):
                continue
            for sid in e.get("evidence", []) or []:
                if sid not in shot_ids:
                    errors.append(f"extra_findings に未知のスクショ id: {sid!r}")
            extra_findings.append(
                {"text": e.get("text", ""), "evidence": list(e.get("evidence", []) or [])}
            )

    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 2

    # スクショの data URI 埋め込み
    embedded_shots: dict[str, dict[str, str]] = {}
    for s in shots:
        sid = s.get("id")
        fname = s.get("file", "")
        path = fname if os.path.isabs(fname) else os.path.join(args.shots_dir, fname)
        if not os.path.isfile(path):
            print(f"スクショファイルが見つからない: {path}", file=sys.stderr)
            return 2
        embedded_shots[sid] = {
            "caption": s.get("caption", ""),
            "src": _data_uri(path),
        }

    verdict_by_ac = {v["ac"]: v for v in raw_verdicts}
    combined = {
        "title": evidence.get("title", "E2E verification report"),
        "source": evidence.get("source", ""),
        "acs": [
            {
                "id": a.get("id"),
                "text": a.get("text", ""),
                "verdict": verdict_by_ac[a.get("id")].get("verdict"),
                "observation": verdict_by_ac[a.get("id")].get("observation", ""),
                "evidence": list(verdict_by_ac[a.get("id")].get("evidence", []) or []),
            }
            for a in acs
        ],
        "excluded_acs": [
            {"id": e.get("id", ""), "text": e.get("text", ""), "reason": e.get("reason", "")}
            for e in (evidence.get("excluded_acs") or [])
            if isinstance(e, dict)
        ],
        "extra_findings": extra_findings,
        "screenshots": embedded_shots,
    }

    json_str = json.dumps(combined, ensure_ascii=False)
    json_str = json_str.replace("</", "<\\/")

    with open(args.template, "r", encoding="utf-8") as f:
        template = f.read()
    if "__REPORT_DATA_JSON__" not in template:
        print("テンプレートに __REPORT_DATA_JSON__ が見つからない", file=sys.stderr)
        return 2

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(template.replace("__REPORT_DATA_JSON__", json_str))

    counts = {k: 0 for k in ALLOWED_VERDICTS}
    for a in combined["acs"]:
        counts[a["verdict"]] += 1
    print(
        f"{os.path.abspath(args.out)} に AC {len(combined['acs'])} 件 "
        f"(pass={counts['pass']} fail={counts['fail']} needs_human={counts['needs_human']}) / "
        f"スクショ {len(embedded_shots)} 枚を書き込んだ",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="verify-report 用の HTML レポート生成")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_p = subparsers.add_parser("build", help="evidence + verdicts から report.html を生成する")
    build_p.add_argument("--evidence", required=True)
    build_p.add_argument("--verdicts", required=True)
    build_p.add_argument("--shots-dir", required=True)
    build_p.add_argument("--template", required=True)
    build_p.add_argument("--out", required=True)

    args = parser.parse_args()
    if args.command == "build":
        return cmd_build(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
