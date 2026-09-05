---
name: draftsmith-loop-improve
description: draftsmith delivery receiptを複数件読み、繰り返すCI失敗・設計指摘・実装指摘・人間判断からproposal-onlyの改善案を作る。「draftsmithの開発フローを改善」「delivery receiptを振り返り」で使用する。
user-invocable: true
---

# Draftsmith loop improve adapter

次のread-only helperでGit metadata配下のv1/v2 receiptを混在のまま読む。v1は移行・上書きせず、
識別fieldをproposalへ流さない。2件以上のreceiptで繰り返したmetricだけを改善候補にする。

```bash
python3 <draftsmith-root>/scripts/receipt_proposals.py --repo .
```

出力はproposal-only:

- evidence: receipt件数とcounter（key・本文なし）
- target: Skill、rubric、CI、driver、repo instructionのいずれか
- concrete change: before/after
- expected effectと反証方法
- `cost_hotspots`: `cost`ブロックを持つreceiptから、cache readの合計が大きいrole上位2件
  （receipt件数、合計cache read、平均turn、平均output）。どのagentが消費を支配しているかの材料で、
  これもproposal-only

自動でSkill、Rule、constitutionを変更しない。`design-flow:loop-improve`が利用可能なら、本文では
なくこの正規化summaryだけを入力として渡せる。未導入ならhelperのproposal形式をそのまま返す。

人間が候補を採用した場合だけ、対象がSkillなら利用可能な`skill-creator`、test/CI/rubricなら各正本の
変更workflowへ渡す。適用後にproposalのbaselineを固定し、5件の新しいreceipt後に効果を再評価する。

```bash
python3 <draftsmith-root>/scripts/proposal_lifecycle.py --repo . sync
python3 <draftsmith-root>/scripts/proposal_lifecycle.py --repo . decide \
  --proposal-id <id> --decision accepted --expect-revision <revision>
python3 <draftsmith-root>/scripts/proposal_lifecycle.py --repo . evaluate \
  --proposal-id <id> --expect-revision <revision>
```

発生率が下がらなければ`withdraw_candidate: true`になる。これは自動revertの許可ではなく、人間が
Rule/Skill変更を撤回するか判断する材料である。却下するproposalも`decision rejected`で記録する。
