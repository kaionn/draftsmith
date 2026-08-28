---
name: draftsmith-review-cockpit
description: draftsmithのplan・rubric・diff-review・verify-report・evidenceを再判定せず一画面のローカル索引へまとめる。「draftsmithのreview cockpit」「成果物を一覧で確認」で使う。
user-invocable: true
---

# Draftsmith review cockpit

`artifacts`だけを持つJSONをscratch領域またはrepo内へ作り、既存成果物のpathを列挙する。

```json
{"artifacts":[{"kind":"plan","path":"plans/example.md"},{"kind":"evidence","path":"<local evidence path>"}]}
```

```bash
python3 <draftsmith-root>/scripts/review_cockpit.py --repo . --index <index.json> \
  [--allow-root <root>] [--pr-head <current-full-oid>]
```

cockpitは索引だけを生成する。差分解説は`draftsmith:diff-review`、E2E判定は
`draftsmith:verify-report`、commitは`draftsmith:plan-commit`を正本として再利用し、判定やstateを
複製しない。`fresh`は完全OID、metadata digest、packet本文hash、callerが直前に実測したPR headが
すべて一致する場合だけに使い、情報が無ければ`unknown`とする。
外部投稿は行わない。
