# draftsmith

設計ファーストのインナーループを Claude Code に足すプラグイン。

## プロジェクト構成

- `skills/draftsmith/SKILL.md` — routing・human gate・untrusted input・lane昇格の共通contract
- `skills/draftsmith/references/full-lane.md` / `light-lane.md` / `artifacts.md` — 選択時だけ読む詳細
- `skills/draftsmith/agents/openai.yaml` — Codexでの自然言語による暗黙Skill選択を明示的に許可
- `skills/draftsmith/references/delivery-loop.md` — commit gate からPR review・merge-readyまでのre-entrant lifecycle
- `skills/draftsmith/scripts/delivery_state.py` — Git metadata配下のdelivery state helper
- `skills/draftsmith/scripts/delivery_hook.py` — hooks から呼ばれる park / resume の唯一のPython entry（state無しでは delivery_state をimportしない）
- `skills/draftsmith/scripts/run_telemetry.py` — opaque IDのv2 run telemetryとimmutable receipt
- `skills/draftsmith/scripts/receipt_proposals.py` — v1/v2 receipt混在のproposal-only分析
- `skills/draftsmith/scripts/proposal_lifecycle.py` — human decisionと5-run効果測定
- `skills/draftsmith/scripts/run_inspect.py` — 読み取り専用doctor / status / run-card
- `skills/draftsmith/scripts/evidence_packet.py` — clean full-head・AC被覆付きlocal evidence
- `skills/draftsmith/scripts/review_cockpit.py` — 既存artifactのlocal index
- `skills/adapters/draftsmith-delivery-driver/SKILL.md` — single-driver lease付き再開adapter
- `skills/adapters/draftsmith-loop-improve/SKILL.md` — receiptからproposal-only改善案を作るadapter
- `skills/adapters/draftsmith-inspect/SKILL.md` — doctor / status / run-card入口
- `skills/adapters/draftsmith-review-cockpit/SKILL.md` — review cockpit入口
- `skills/diff-review/SKILL.md` — 解説つき差分レビュー画面の生成（/diff-review）
- `skills/plan-commit/SKILL.md` — plan ファイルの畳み込みコミット（/plan-commit）
- `skills/verify-report/SKILL.md` — 証跡スクショ付き E2E 検証レポート（/verify-report）
- `skills/adapters/draftsmith-next/SKILL.md` — harness の Plans.md から 1 タスクを draftsmith へ橋渡し（/draftsmith-next）
- `skills/adapters/` — draftsmith 本体（1 タスクを受け取るインナーループ）に対する、タスク供給元ごとの橋渡し層。供給元固有の依存はここに閉じ込める。discovery は `skills/` 直下 1 階層のみが既定スキャン対象なので、`.claude-plugin/plugin.json` の `skills` 配列に `./skills/adapters/` を明示登録して発見させている
- `agents/` — designer / auditor / consultant / implementer / reviewer-light / diff-analyzer / evidence-reviewer
- `tests/test_delivery_state.py` — delivery phase遷移・linked worktree・schemaの回帰テスト
- `tests/test_plugin_manifest.py` — plugin / marketplace / Skill discovery metadataの整合テスト
- `tests/test_hooks.py` — SessionStart / Stop hookのsubprocess回帰テスト
- `.github/workflows/validate.yml` — PRごとのPython 3.10/3.13回帰テストとwhitespace検査
- `hooks/draftsmith-hooks.json` — plugin hooks宣言（SessionStart=resume brief注入 / Stop=未parkのblock）。既定の `hooks/hooks.json` は二重登録を避けるため使わない
- `hooks/session-start-resume-brief.sh` / `hooks/stop-park-reminder.sh` — hook wrapper（失敗しても exit 0 で黙る）
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

## スクリプト検証で subshell の `set -e` を当てにしない

`( set -e; cmd1; cmd2 ) && echo ok` の形で検証すると、subshell が AND-OR list の左辺にあるため **subshell 内の `set -e` が無効化される**。cmd1 が `exit 1` でも cmd2 が実行され、subshell の終了ステータスは cmd2 のものになるので、失敗が success として通る。

実測（bash / zsh 共通）:

| 形 | 挙動 |
|---|---|
| `( set -e; ./fail.sh ) && echo ok` | 短絡する（単一コマンドなら問題は起きない） |
| `( set -e; ./fail.sh; echo x ) && echo ok` | `set -e` が効かず `x` と `ok` が両方出る |
| `( set -e; ./fail.sh; echo x )` | `set -e` が効く（exit=1、`x` は出ない） |

検証は GHA の `run:` と同じくファイル経由で実行し、終了ステータスを明示的に読む。

```bash
cat > /tmp/verify.sh <<'SH'
set -e
./scripts/changelog-section.sh v1.0.0
SH
bash /tmp/verify.sh; echo "exit=$?"
```
