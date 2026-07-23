# draftsmith

設計ファーストのインナーループを Claude Code に足すプラグイン。

## プロジェクト構成

- `skills/draftsmith/SKILL.md` — メインスキル（full / light 2 レーン）
- `agents/` — designer / auditor / consultant / implementer / reviewer-light
- `skills/draftsmith/templates/` — 要件書・出力契約・mini-ADR テンプレート
- `.claude-plugin/plugin.json` — プラグインメタデータ（バージョンの SSOT）
- `.claude-plugin/marketplace.json` — self-marketplace 定義

## バージョン管理

[Semantic Versioning](https://semver.org/) に従う。

### バージョンの一次ソース

`plugin.json` の `version` フィールドが SSOT。`marketplace.json` の 2 箇所（`metadata.version` と `plugins[0].version`）は常に同期する。手動で個別編集しない。

### リリース手順

```bash
./scripts/release.sh <major|minor|patch>
```

スクリプトが以下を一括で行う:

1. `plugin.json` と `marketplace.json` のバージョンを更新
2. `CHANGELOG.md` の `[Unreleased]` を新バージョンに昇格
3. commit + annotated tag (`vX.Y.Z`)

push と GitHub Release は手動:

```bash
git push origin main --tags
gh release create vX.Y.Z --title 'vX.Y.Z' --notes-from-tag
```

### バージョン更新の基準

- **patch**: バグ修正、テンプレートの文言修正、ドキュメント修正
- **minor**: 新機能追加（エージェント追加、新オプション、テンプレート追加）、既存機能の拡張
- **major**: 破壊的変更（SKILL.md のフロー変更、エージェントの入出力契約変更、既存オプションの削除）

### CHANGELOG 運用

- [Keep a Changelog](https://keepachangelog.com/) 形式を使う
- 機能追加・変更・修正は `[Unreleased]` セクションに都度追記する
- リリース時に `release.sh` が `[Unreleased]` を新バージョンに昇格する
