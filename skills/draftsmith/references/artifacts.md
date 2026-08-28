# Artifacts

成果物が必要な時だけ読む。

- plan: `templates/plan-file.md`を使う一時設計文書。commit時は`draftsmith:plan-commit`だけを使う。
- rubric: `templates/rubric.md`を使い、全ACの検証方法と実測判定を持つ。
- diff review: 解説と承認UIは`draftsmith:diff-review`を正本として再利用する。
- E2E report: 画面証跡と独立判定は`draftsmith:verify-report`を正本として再利用する。
- evidence packet: `evidence_packet.py`へAC、結果、Not covered、verification summary、risksを渡す。
  clean worktreeと完全OIDが一致しなければ生成しない。PR転記用Markdownとfreshness metadataを
  同時生成するが、外部投稿はしない。
- review cockpit: `review_cockpit.py`は上記artifactのallowlisted pathとfreshnessだけを索引化する。
  `verified_head`とvalid digestがない既存成果物は`unknown`であり、推測でfreshにしない。

raw log、secret、絶対home pathをHTMLへ含めない。cockpit inputはallowlist root配下だけとし、symlinkと
`..`を拒否する。成果物の判定やdelivery phaseはcockpitへ再実装しない。
