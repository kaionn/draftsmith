# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-07-24

### Added

- auditor エージェント（opus / read-only）: designer の brief をフレッシュコンテキストで意味的に監査する独立監査層。full レーンの Step 3 で既定実行し、`--no-audit` で省略できる。6 観点（接合面・バグの芽・規約準拠・要件充足・設計の甘さ・mini-ADR の妥当性）+ 信頼度付き指摘。high 指摘は反映か明示的棄却の二択
- consultant エージェント（opus / read-only / on-demand）: 覆し判断の独立第二意見。designer 提案の覆し・auditor high 指摘の棄却・軽微/重大の境界迷いの 3 トリガーで必須諮問。助言棄却には一次資料引用付きの二段目明文化を要求（非対称プロトコル二段目）
- 自律モードの例外エスカレーション: 保守的仮定で埋めきれない未決事項（Step 1 / Step 4）は、推測せず AskUserQuestion でその 1 点だけを人間に確定してもらう。頻発時は `--gated` での仕切り直しを提案

### Changed

- 差し戻し規律を明文化: designer への差し戻しは違反箇所の指摘に限定し、修正案の詳細を書かない（マイクロマネジメントによる責務分離の崩壊防止）
- 中央検証の成果物を designer にレビューさせない禁止を明記（自己弁護バイアス対策）
- auditor の「注意事項（予測）」は修正指示として扱わず、予測だけを根拠に確定済み設計を書き換えない規定を追加
- 完了報告の「AI が下した判断」に auditor 指摘の採否と consultant 諮問の記録を追加

## [1.0.0] - 2026-07-17

### Added

- 設計ファーストのインナーループ（full レーン 7 ステップ: 要件正規化 → designer 設計 → 監査 3 層 → implementer 実装 → reviewer-light ループ → 完了報告）
- light レーン: 軽量タスク向け 5 ステップ経路（designer 省略・reviewer 1 巡）
- レーン自動判定（方針一意・アンカー自明・変更が小さいの 3 条件）と `--full` / `--light` 強制指定
- 自律モード（既定）と `--gated` モード（要件確定・設計確定で人間ゲート）
- designer エージェント（opus / read-only・出力契約 5 要素）
- implementer エージェント（sonnet・逐語適用・アンカー不一致スキップ報告）
- reviewer-light エージェント（sonnet / read-only・7 観点・観点外リスト）
- テンプレート群（要件書 8 項目・出力契約・mini-ADR）
- 不変ゲート（commit / push 禁止・破壊的操作の人間確認）
- 監査 3 層（トレーサビリティ機械照合・ADR スポットチェック・予測乖離検査）
- 覆し明文化プロトコル（designer 提案・レビュー指摘の却下に理由と代替案を必須化）

[Unreleased]: https://github.com/kaionn/draftsmith/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/kaionn/draftsmith/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kaionn/draftsmith/releases/tag/v1.0.0
