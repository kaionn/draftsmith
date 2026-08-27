---
name: draftsmith-loop-improve
description: draftsmith delivery receiptを複数件読み、繰り返すCI失敗・設計指摘・実装指摘・人間判断からproposal-onlyの改善案を作る。「draftsmithの開発フローを改善」「delivery receiptを振り返り」で使用する。
user-invocable: true
---

# Draftsmith loop improve adapter

Git metadata配下の`draftsmith-delivery-receipts/*.json`を読み、2件以上のreceiptで繰り返した
metricだけを改善候補にする。PR/review本文や顧客情報を収集しない。

出力はproposal-only:

- evidence: receipt keyとcounter（本文なし）
- target: Skill、rubric、CI、driver、repo instructionのいずれか
- concrete change: before/after
- expected effectと反証方法

自動でSkillやruleを変更しない。`design-flow:loop-improve`が利用可能なら、本文ではなくこの正規化
summaryだけを入力として渡せる。未導入ならdraftsmith内で同じproposal形式を返す。
