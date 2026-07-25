#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/changelog-section.sh <version|Unreleased>
# CHANGELOG.md から指定セクションの本文を stdout に出す。
# 本文が空（該当セクションが無い / 中身が無い）なら exit 1。
# リリースノートが空の Release を作らせないためのガードとして
# release.sh と .github/workflows/release.yml の双方から使う。

SECTION="${1:-}"

if [[ -z "$SECTION" ]]; then
  echo "Usage: $0 <version|Unreleased>" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
CHANGELOG="$REPO_ROOT/CHANGELOG.md"

# 見出し行（`## [1.3.0] - 2026-07-25` 等）の直後から次の `## ` までを取り出す。
# 先頭・末尾の空行は落とし、セクション内部の空行は保持する。
BODY=$(awk -v header="## [$SECTION]" '
  index($0, header) == 1 { inside = 1; next }
  inside && /^## / { exit }
  inside {
    if ($0 ~ /^[[:space:]]*$/) { if (started) blank++; next }
    while (blank > 0) { print ""; blank-- }
    started = 1
    print
  }
' "$CHANGELOG")

if [[ -z "$BODY" ]]; then
  echo "エラー: CHANGELOG.md に [$SECTION] の本文が見つからない" >&2
  exit 1
fi

printf '%s\n' "$BODY"
