#!/usr/bin/env python3
"""Check a designer-return.md against the reply contract without reading it into main."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ELEMENT_COUNT = 5
REQUIRED_ELEMENTS = (1, 2, 3, 4)
ELEMENT_HEADING_RE = re.compile(r"^##\s*要素\s*(\d)\b")
SURVEYED_FILES_HEADING_RE = re.compile(r"^###\s*調査済みファイル\s*$")
AC_RE = re.compile(r"\bAC-(\d+)\b")
REQUIREMENT_AC_RE = re.compile(r"^\s*[-*]\s*AC-(\d+)\s*[:：]")
DIGEST_RE = re.compile(r"^<!--\s*requirements-sha256:\s*([0-9a-f]{64})\s*-->\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_elements(lines: list[str]) -> dict[int, list[str]]:
    """Map element number to the lines of its section (heading excluded)."""
    sections: dict[int, list[str]] = {}
    current: int | None = None
    for line in lines:
        match = ELEMENT_HEADING_RE.match(line)
        if match:
            current = int(match.group(1))
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def requirement_acs(requirements: Path) -> list[str]:
    found: list[str] = []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT_AC_RE.match(line)
        if match:
            found.append(f"AC-{match.group(1)}")
    return found


def traceability_acs(section: list[str]) -> list[str]:
    """AC ids that appear in the first cell of a table row of element 4."""
    found: list[str] = []
    for line in section:
        if not TABLE_ROW_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells:
            continue
        found.extend(f"AC-{number}" for number in AC_RE.findall(cells[0]))
    return found


def surveyed_files_present(section: list[str]) -> bool:
    inside = False
    for line in section:
        if SURVEYED_FILES_HEADING_RE.match(line):
            inside = True
            continue
        if inside:
            if line.startswith("#"):
                return False
            if line.strip():
                return True
    return False


def check(designer_return: Path, requirements: Path | None, *, light: bool) -> list[str]:
    problems: list[str] = []
    text = designer_return.read_text(encoding="utf-8")
    lines = text.splitlines()

    if requirements is not None:
        digest_line = lines[0] if lines else ""
        match = DIGEST_RE.match(digest_line)
        if not match:
            problems.append("先頭行に <!-- requirements-sha256: … --> が無い")
        elif match.group(1) != sha256_of(requirements):
            problems.append("requirements-sha256 が要件書の digest と一致しない（要件が変わっている）")

    sections = split_elements(lines)
    for number in REQUIRED_ELEMENTS:
        if number not in sections:
            problems.append(f"要素 {number} の見出し（## 要素 {number}）が無い")
    extra = sorted(number for number in sections if number < 1 or number > ELEMENT_COUNT)
    if extra:
        problems.append(f"契約外の要素番号がある: {', '.join(str(n) for n in extra)}")

    if requirements is not None and 4 in sections:
        expected = requirement_acs(requirements)
        if not expected:
            problems.append("要件書に AC-n の箇条書きが無い")
        actual = traceability_acs(sections[4])
        missing = [ac for ac in expected if ac not in actual]
        duplicated = sorted({ac for ac in actual if actual.count(ac) > 1}, key=lambda s: int(s[3:]))
        unknown = sorted({ac for ac in actual if ac not in expected}, key=lambda s: int(s[3:]))
        if missing:
            problems.append(f"要素 4 に無い AC: {', '.join(missing)}")
        if duplicated:
            problems.append(f"要素 4 に重複する AC: {', '.join(duplicated)}")
        if unknown:
            problems.append(f"要件書に無い AC が要素 4 にある: {', '.join(unknown)}")

    if not light and 1 in sections and not surveyed_files_present(sections[1]):
        problems.append("要素 1 末尾の「### 調査済みファイル」小節が無いか空")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("designer_return", type=Path)
    parser.add_argument("--requirements", type=Path)
    parser.add_argument(
        "--light",
        action="store_true",
        help="light lane brief: skip the surveyed-files section check",
    )
    args = parser.parse_args()
    if not args.designer_return.is_file():
        print(f"error: {args.designer_return} is not a file", file=sys.stderr)
        return 2
    if args.requirements is not None and not args.requirements.is_file():
        print(f"error: {args.requirements} is not a file", file=sys.stderr)
        return 2
    problems = check(args.designer_return, args.requirements, light=args.light)
    if problems:
        print("reply contract violations:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("reply contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
