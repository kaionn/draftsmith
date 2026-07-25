# draftsmith

設計ファーストのインナーループを Claude Code に足すプラグイン。

## プロジェクト構成

- `skills/draftsmith/SKILL.md` — メインスキル（full / light 2 レーン）
- `skills/diff-review/SKILL.md` — 解説つき差分レビュー画面の生成（/diff-review）
- `skills/plan-commit/SKILL.md` — plan ファイルの畳み込みコミット（/plan-commit）
- `skills/verify-report/SKILL.md` — 証跡スクショ付き E2E 検証レポート（/verify-report）
- `agents/` — designer / auditor / consultant / implementer / reviewer-light / diff-analyzer / evidence-reviewer
- `skills/draftsmith/templates/` — 要件書・出力契約・mini-ADR・plan ファイルのテンプレート
- `skills/diff-review/scripts/` + `templates/` — diff 分割・HTML ビルド（Python stdlib のみ）とレビュー画面テンプレート
- `skills/verify-report/scripts/` + `templates/` — 証跡埋め込みレポートのビルド（Python stdlib のみ）とテンプレート
- `.claude-plugin/plugin.json` — プラグインメタデータ（バージョンの SSOT）
- `.claude-plugin/marketplace.json` — self-marketplace 定義
- `scripts/release.sh` — バージョン bump + CHANGELOG 昇格 + commit
- `scripts/changelog-section.sh` — CHANGELOG から指定セクションを抽出（リリースノート生成）
- `.github/workflows/release.yml` — tag + GitHub Release の自動作成

## バージョン管理

[Semantic Versioning](https://semver.org/) に従う。

### バージョンの一次ソース

`plugin.json` の `version` フィールドが SSOT。`marketplace.json` の 2 箇所（`metadata.version` と `plugins[0].version`）は常に同期する。手動で個別編集しない。

### リリース手順

機能変更のコミット + push を済ませたうえで、GHA 完結の 1 コマンドが基本形:

```bash
gh workflow run release.yml -f bump=<major|minor|patch>
```

bump ジョブが runner 上で `release.sh` を実行して main へ push し、同一 run 内で
tag + GitHub Release まで完結する（GITHUB_TOKEN の push は push トリガーを発火しない
ため、別 run に分けない）。CHANGELOG の `[Unreleased]` が空なら bump ジョブが落ち、
Release は作られない。

ローカル経路も従来どおり使える:

```bash
./scripts/release.sh <major|minor|patch>
git push origin main
```

`release.sh` がローカルで行うこと:

1. `CHANGELOG.md` の `[Unreleased]` が空でないことを検証（空なら abort）
2. `plugin.json` と `marketplace.json` のバージョンを更新
3. `CHANGELOG.md` の `[Unreleased]` を新バージョンに昇格
4. commit（**tag は作らない**）

`main` への push 後、`.github/workflows/release.yml` が残りを完結させる:

1. `plugin.json` / `marketplace.json` の 3 箇所のバージョン整合を検証（不一致なら fail）
2. `CHANGELOG.md` の該当セクションをリリースノートとして抽出（空なら fail）
3. annotated tag `vX.Y.Z` を作成して push
4. GitHub Release を作成して**即公開**

push が即公開のトリガーになる（不可逆）。tag / Release の作成はどちらも「既存ならスキップ」なので再実行は安全。

発火は `.claude-plugin/plugin.json` の変更を含む `main` への push。取りこぼした場合（bump commit は push 済みで tag / Release だけ無い等）は手動発火で救済する:

```bash
gh workflow run release.yml
```

対象バージョンは常に `plugin.json` の現在値で、入力は取らない。tag は HEAD ではなく `plugin.json` を最後に変更したコミット（= bump commit）に打たれるため、bump 後に別のコミットを積んでから救済発火しても tag 位置はずれない。

### バージョン更新の基準

- **patch**: バグ修正、テンプレートの文言修正、ドキュメント修正
- **minor**: 新機能追加（エージェント追加、新オプション、テンプレート追加）、既存機能の拡張
- **major**: 破壊的変更（SKILL.md のフロー変更、エージェントの入出力契約変更、既存オプションの削除）

### CHANGELOG 運用

- [Keep a Changelog](https://keepachangelog.com/) 形式を使う
- 機能追加・変更・修正は `[Unreleased]` セクションに都度追記する
- リリース時に `release.sh` が `[Unreleased]` を新バージョンに昇格する
- 昇格後のセクションが GitHub Release のノートとしてそのまま公開される（`scripts/changelog-section.sh` が抽出）。`[Unreleased]` への追記は「そのまま公開文になる」前提で書く
