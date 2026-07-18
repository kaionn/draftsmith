#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/release.sh <major|minor|patch>
# - plugin.json と marketplace.json のバージョンを一括更新
# - CHANGELOG.md の [Unreleased] を新バージョンに昇格
# - git commit + tag + GitHub Release を作成

BUMP_TYPE="${1:-}"

if [[ -z "$BUMP_TYPE" ]] || [[ ! "$BUMP_TYPE" =~ ^(major|minor|patch)$ ]]; then
  echo "Usage: $0 <major|minor|patch>"
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
PLUGIN_JSON="$REPO_ROOT/.claude-plugin/plugin.json"
MARKETPLACE_JSON="$REPO_ROOT/.claude-plugin/marketplace.json"
CHANGELOG="$REPO_ROOT/CHANGELOG.md"

CURRENT_VERSION=$(jq -r '.version' "$PLUGIN_JSON")
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$BUMP_TYPE" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"

echo "Bumping version: $CURRENT_VERSION → $NEW_VERSION"

# 1. plugin.json
jq --arg v "$NEW_VERSION" '.version = $v' "$PLUGIN_JSON" > "$PLUGIN_JSON.tmp" \
  && mv "$PLUGIN_JSON.tmp" "$PLUGIN_JSON"

# 2. marketplace.json (metadata.version + plugins[0].version)
jq --arg v "$NEW_VERSION" '
  .metadata.version = $v |
  .plugins[0].version = $v
' "$MARKETPLACE_JSON" > "$MARKETPLACE_JSON.tmp" \
  && mv "$MARKETPLACE_JSON.tmp" "$MARKETPLACE_JSON"

# 3. CHANGELOG.md — [Unreleased] の直後に新バージョンのヘッダーを挿入
TODAY=$(date +%Y-%m-%d)
sed -i '' "s/^## \[Unreleased\]$/## [Unreleased]\n\n## [$NEW_VERSION] - $TODAY/" "$CHANGELOG"

# 比較リンクを更新
sed -i '' "s|\[Unreleased\]: \(.*\)/compare/v.*\.\.\.HEAD|[Unreleased]: \1/compare/v${NEW_VERSION}...HEAD|" "$CHANGELOG"

# 新バージョンのリンクを追加（既存の最新バージョンリンクの直前）
PREV_TAG="v${CURRENT_VERSION}"
NEW_LINK="[${NEW_VERSION}]: https://github.com/kaionn/draftsmith/compare/${PREV_TAG}...v${NEW_VERSION}"
# 旧バージョンのリンク行の直前に挿入
sed -i '' "/^\[${CURRENT_VERSION}\]:/i\\
${NEW_LINK}
" "$CHANGELOG"

echo "Updated: plugin.json, marketplace.json, CHANGELOG.md"

# 4. Commit + Tag
git add "$PLUGIN_JSON" "$MARKETPLACE_JSON" "$CHANGELOG"
git commit -m "v${NEW_VERSION} リリース"
git tag -a "v${NEW_VERSION}" -m "v${NEW_VERSION}"

echo "Created commit and tag: v${NEW_VERSION}"

# 5. GitHub Release (push はユーザーに任せる)
echo ""
echo "次のステップ:"
echo "  git push origin main --tags"
echo "  gh release create v${NEW_VERSION} --title 'v${NEW_VERSION}' --notes-from-tag"
