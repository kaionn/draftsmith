---
name: draftsmith-next
description: claude-code-harness の Plans.md から未着手タスクを 1 件選び、draftsmith（設計ファーストのインナーループ）に渡すグルースキル。「次のタスクを draftsmith で」「draftsmith-next」「Plans の続きを設計ファーストで」で発火。Plans.md は読み取りのみで、マーカー更新は harness-sync に任せる。
user-invocable: true
---

# /draftsmith-next — harness 台帳 → draftsmith の橋渡し

harness（アウターループ: 台帳・進捗管理）と draftsmith（インナーループ: 1 タスクの
要件 → 設計 → 監査 → 実装 → light レビュー）を疎結合のまま繋ぐ薄いラッパー。
このスキル自身は判断も実装もしない。タスクの受け渡しだけを行う。

## 境界（先に確認）

- **Plans.md への書き込みは禁止**。cc: マーカーの更新は harness-sync の領分
- harness の内部状態（memory / sprint-contract 等）には触れない。読むのはタスクの**記述**だけ
- 1 回の起動で 1 タスクのみ。一括処理はしない
- 同じタスクを harness-work と二重実行しない（このスキルで渡したタスクは draftsmith が担当）

## フロー

### 1. Plans.md の特定

優先順: 引数のパス指定 → カレント repo ルートの `Plans.md` →
`~/.claude/plans/Plans-{repo名}.md`。どれも無ければユーザーに場所を聞く。

### 2. タスクの選定（人間の領分）

Plans.md から未着手タスク（`cc:TODO` マーカー、または未チェックの `- [ ]` 行。
`cc:WIP` / `cc:done` / `cc:完了` / `[x]` は除外）を上から列挙する。

- 引数にタスク番号・キーワードがあればそれで絞り込む
- 絞り込めなければ候補（最大 4 件）を AskUserQuestion で提示して選んでもらう。
  **勝手に選ばない** — どのタスクをやるかはスコープ判断で、人間が決める

### 3. 要件文への整形

選定したタスク行を**逐語で**含め、周辺コンテキスト（属する見出し・タスク行が参照する
spec ファイルがあればその該当節へのポインタ）を添えて要件文にする。
タスク行の意訳・要約はしない（draftsmith 側の Step 1 が正規化を担当する）。

### 4. draftsmith の発火

Skill ツールで `draftsmith:draftsmith` を起動し、整形した要件文を args で渡す。
ユーザーが `--gated` を付けていたらそのまま伝搬する。
発火したら、このスキルの仕事はいったん終わり（フローの主導権は draftsmith に移る）。

### 5. 完了後の案内（draftsmith の完了報告が出たら）

draftsmith は commit / push をしない設計なので、変更はワーキングツリーに残っている。
以下を 2〜3 行で案内する:

1. diff を確認して自分で commit する
2. commit 後に `harness-sync` を実行してマーカー（cc:）を台帳に反映する

このスキルが代行するのはここまで。commit もマーカー更新も実行しない。

## 前提

- このスキルは外部プラグイン `claude-code-harness`（Plans.md の台帳を作る側）の
  存在を前提にする。未導入なら台帳なしで `draftsmith:draftsmith` を直接使う旨を
  案内して終了する
- Plans.md が存在しない場合は「先に harness-plan で台帳を作るか、台帳なしで直接
  `draftsmith:draftsmith` を使うか」の 2 択を提示する
