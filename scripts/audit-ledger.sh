#!/bin/bash
# audit-ledger.sh — draftsmith の監査却下 pain 台帳。fail-open・常に exit 0。
#
# サブコマンド:
#   record <category> <reason-summary> <repo>
#     却下 1 件を ~/.local/state/draftsmith/audit-pains.jsonl へ追記する。
#     category は enum 必須（SKILL.md 監査 3 層に定義）。
#   promote-check
#     category（=fp）ごとの出現回数を数え、3 回以上かつ未昇格のものを
#     ~/.local/state/draftsmith/constitution.md の自動昇格セクションへ追記する。
#     昇格済みは promoted.txt に記録し、再実行しても重複追記しない（冪等）。

set -u

state_dir="$HOME/.local/state/draftsmith"
ledger="$state_dir/audit-pains.jsonl"
promoted="$state_dir/promoted.txt"
constitution="$state_dir/constitution.md"

SENTINEL='<!-- draftsmith-auto-promoted -->'

VALID_CATEGORIES=(traceability-miss adr-unjustified prediction-divergence anchor-mismatch scope-creep requirement-misread)

cmd="${1:-}"

case "$cmd" in
  record)
    category="${2:-}"
    reason="${3:-}"
    repo="${4:-}"

    valid=0
    for c in "${VALID_CATEGORIES[@]}"; do
      [ "$c" = "$category" ] && valid=1 && break
    done
    [ "$valid" -eq 1 ] || exit 0
    [ -z "$reason" ] && exit 0
    [ -z "$repo" ] && exit 0

    mkdir -p "$state_dir" 2>/dev/null || exit 0

    fp=$(printf '%s' "$category" | shasum -a 256 | cut -c1-16)
    ts=$(date +%Y-%m-%dT%H:%M:%S)

    jq -cn --arg ts "$ts" --arg repo "$repo" --arg category "$category" \
          --arg reason "$reason" --arg fp "$fp" \
          '{ts:$ts, repo:$repo, category:$category, reason:$reason, fp:$fp}' \
          >> "$ledger" 2>/dev/null
    ;;

  promote-check)
    [ -f "$ledger" ] || exit 0
    mkdir -p "$state_dir" 2>/dev/null || exit 0
    touch "$promoted" 2>/dev/null

    fps=$(jq -r '.fp' "$ledger" 2>/dev/null | sort -u)
    [ -z "$fps" ] && exit 0

    printf '%s\n' "$fps" | while IFS= read -r fp; do
      [ -z "$fp" ] && continue
      grep -qx "$fp" "$promoted" 2>/dev/null && continue

      count=$(jq -r --arg fp "$fp" 'select(.fp == $fp) | .fp' "$ledger" 2>/dev/null | wc -l | tr -d ' ')
      [ "${count:-0}" -ge 3 ] || continue

      category=$(jq -r --arg fp "$fp" 'select(.fp == $fp) | .category' "$ledger" 2>/dev/null | head -1)
      repos=$(jq -r --arg fp "$fp" 'select(.fp == $fp) | .repo' "$ledger" 2>/dev/null | sort -u | paste -sd, -)
      now=$(date +%Y-%m-%d)

      if [ ! -f "$constitution" ]; then
        {
          echo "# constitution"
          echo ""
          echo "$SENTINEL"
          echo ""
          echo "> このセクションは draftsmith が自動管理します。"
          echo "> 監査却下が同一カテゴリで 3 回以上発生した項目が自動追記されます。"
        } > "$constitution" 2>/dev/null
      elif ! grep -qF "$SENTINEL" "$constitution" 2>/dev/null; then
        {
          echo ""
          echo "$SENTINEL"
          echo ""
          echo "> このセクションは draftsmith が自動管理します。"
          echo "> 監査却下が同一カテゴリで 3 回以上発生した項目が自動追記されます。"
        } >> "$constitution" 2>/dev/null
      fi

      {
        echo ""
        echo "## 自動検出: 「${category}」による却下が ${count} 件発生 (${now} 昇格)"
        echo ""
        echo "- 対象 repo: ${repos}"
        echo "- fingerprint: ${fp}"
        echo "- TODO: 詳細を確認して具体的な設計制約へ書き換える（このスタブは自動生成）"
      } >> "$constitution" 2>/dev/null

      echo "$fp" >> "$promoted" 2>/dev/null
    done
    ;;

  *)
    exit 0
    ;;
esac

exit 0
