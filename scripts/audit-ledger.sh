#!/bin/bash
# audit-ledger.sh — structured audit pain ledger and proposal-only promotion.
# record <category> <cause-enum> <target-kind> <repo>
# promote-check

set -u

state_dir="$HOME/.local/state/draftsmith"
ledger="$state_dir/audit-pains.jsonl"
proposals="$state_dir/improvement-proposals"

VALID_CATEGORIES=(traceability-miss adr-unjustified prediction-divergence anchor-mismatch scope-creep requirement-misread)
VALID_CAUSES=(missing-coverage unsupported-assumption stale-anchor boundary-expansion ambiguous-requirement verification-gap)
VALID_TARGETS=(test rubric skill repo-instruction ci driver)

contains() {
  needle="$1"
  shift
  for value in "$@"; do
    [ "$value" = "$needle" ] && return 0
  done
  return 1
}

cmd="${1:-}"

case "$cmd" in
  record)
    category="${2:-}"
    cause="${3:-}"
    target="${4:-}"
    repo="${5:-}"

    contains "$category" "${VALID_CATEGORIES[@]}" || exit 0
    contains "$cause" "${VALID_CAUSES[@]}" || exit 0
    contains "$target" "${VALID_TARGETS[@]}" || exit 0
    [ -z "$repo" ] && exit 0

    [ -L "$state_dir" ] && exit 0
    [ -L "$ledger" ] && exit 0
    mkdir -p -m 700 "$state_dir" 2>/dev/null || exit 0
    chmod 700 "$state_dir" 2>/dev/null

    fp=$(printf '%s\0%s\0%s' "$category" "$cause" "$target" | shasum -a 256 | cut -c1-16)
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    jq -cn --arg ts "$ts" --arg repo "$repo" --arg category "$category" \
          --arg cause "$cause" --arg target "$target" --arg fp "$fp" \
          '{ts:$ts, repo:$repo, category:$category, cause:$cause, target_kind:$target, fp:$fp}' \
          >> "$ledger" 2>/dev/null
    chmod 600 "$ledger" 2>/dev/null
    ;;

  promote-check)
    [ -f "$ledger" ] || exit 0
    [ -L "$state_dir" ] && exit 0
    [ -L "$ledger" ] && exit 0
    [ -L "$proposals" ] && exit 0
    mkdir -p -m 700 "$proposals" 2>/dev/null || exit 0
    chmod 700 "$proposals" 2>/dev/null

    fps=$(jq -r '.fp' "$ledger" 2>/dev/null | sort -u)
    [ -z "$fps" ] && exit 0

    printf '%s\n' "$fps" | while IFS= read -r fp; do
      [ -z "$fp" ] && continue
      count=$(jq -r --arg fp "$fp" 'select(.fp == $fp) | .fp' "$ledger" 2>/dev/null | wc -l | tr -d ' ')
      [ "${count:-0}" -ge 2 ] || continue

      category=$(jq -r --arg fp "$fp" 'select(.fp == $fp) | .category' "$ledger" 2>/dev/null | head -1)
      cause=$(jq -r --arg fp "$fp" 'select(.fp == $fp) | .cause' "$ledger" 2>/dev/null | head -1)
      target=$(jq -r --arg fp "$fp" 'select(.fp == $fp) | .target_kind' "$ledger" 2>/dev/null | head -1)
      proposal="$proposals/$fp.json"
      [ -L "$proposal" ] && continue
      [ -e "$proposal" ] && continue
      temp="$proposals/.$fp.$$"
      jq -cn --arg id "$fp" --arg category "$category" --arg cause "$cause" \
        --arg target "$target" --argjson count "$count" \
        '{schema_version:1,proposal_id:$id,evidence:{category:$category,cause:$cause,occurrences:$count},target:$target,before:("repeated " + $category + " / " + $cause + " has no deterministic prevention gate"),after:("add a focused " + $target + " gate for this structured cause"),expected_effect:("reduce future occurrences of " + $category + " / " + $cause),falsification:("the next measured runs do not reduce this fingerprint"),status:"proposed"}' \
        > "$temp" 2>/dev/null || { rm -f "$temp" 2>/dev/null; continue; }
      chmod 600 "$temp" 2>/dev/null
      mv "$temp" "$proposal" 2>/dev/null
    done
    ;;

  *)
    exit 0
    ;;
esac

exit 0
