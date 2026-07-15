# draftsmith

Design-first inner loop for Claude Code — 設計ファーストのインナーループを Claude Code に足すプラグイン。

> ⚠️ Work in progress. README will be completed before the first public release.

## What / これは何

One task in, reviewed change out: requirements → design → audit → implementation → light review.

1 タスク分の「要件 → 設計 → 監査 → 実装 → light レビュー」を回す。タスク台帳・PR 作成・push は持たない（そこは [claude-code-harness](https://github.com/Chachamaru127/claude-code-harness) などに任せる）。

## Install / インストール

```
/plugin marketplace add kaionn/draftsmith
/plugin install draftsmith@draftsmith
```

## Usage / 使い方

```
/draftsmith <要件を自然言語で>
/draftsmith --gated <要件>   # 要件確定・設計確定の 2 ゲートを人間確認にする
```

## Structure / 構成

- `agents/designer.md` — 一次設計（読み取り専用。実装権限なし）
- `agents/implementer.md` — 逐語 brief の適用（設計判断なし）
- `agents/reviewer-light.md` — 軽量レビュー（「指摘なし」までループ）
- `skills/draftsmith/SKILL.md` — メインフロー
- `skills/draftsmith/templates/` — 要件書・出力契約・mini-ADR テンプレート

## License

MIT
