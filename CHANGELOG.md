# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/kaionn/draftsmith/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/kaionn/draftsmith/releases/tag/v1.0.0
