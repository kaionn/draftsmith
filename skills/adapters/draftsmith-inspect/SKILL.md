---
name: draftsmith-inspect
description: draftsmithの開始前診断、現在phase・次の操作・human gate確認、run開始前カード表示を読み取り専用で行う。「draftsmith doctor」「draftsmith status」「draftsmithの実行内容を先に見せて」で使う。
user-invocable: true
---

# Draftsmith inspect

対象repoで次のhelperを実行し、JSONをそのまま読みやすく要約する。

```bash
python3 <draftsmith-root>/scripts/run_inspect.py --repo . doctor
python3 <draftsmith-root>/scripts/run_inspect.py --repo . status
python3 <draftsmith-root>/scripts/run_inspect.py --repo . run-card --lane full --entry requirements
python3 <draftsmith-root>/scripts/run_inspect.py --repo . run-card --lane unknown \
  --entry delivery --goal review_complete
```

このSkillは診断専用である。directory作成、lock取得、state初期化・更新、GitHub照会・外部投稿を
行わない。delivery stateが無くてもactive telemetryがあれば`inner_loop`、どちらも無ければ
`not_started`を正常な観測結果として返す。
