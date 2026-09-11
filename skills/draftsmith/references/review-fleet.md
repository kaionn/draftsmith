# Review-only fleet artifact contract v1

`draftsmith-review-fleet`のtransport-neutral契約。scriptは`scripts/review_fleet.py`。
起動順はperspective（最低2）→ aggregate → audit。sessionは全roleで異なり、実装sessionも使わない。
成果物のsession IDは自己申告なのでmainがharnessの来歴と照合する。native IDが下記文字種に収まらない場合は
mainが実IDのSHA-256を対応表とともに渡す。roleごとの乱数で実sessionの使い回しを隠さない。
schema検査は独立性の暗号学的証明ではない。

## Main-owned request

`prepare`が作る`request.json`のkeyは次だけ。未知key・不正型・重複JSON keyを拒否する。

| Key | 型・意味 |
|---|---|
| schema_version | integer `1`（boolean不可） |
| request_id | 32文字lowercase hex、新しいroundごとに生成 |
| workflow | `[a-z][a-z0-9_-]{0,63}`の非機密ID |
| snapshot | 64文字SHA-256。delivery側のcontent snapshotと同じ |
| plan_file | null、またはdelivery stateと一致するuntracked一時plan相対path |
| brief_sha256 | 隣の`brief.md`の**raw bytes** digest |
| roles | `[{"id": "correctness", "kind": "perspective"}, …, {"id": "aggregate", "kind": "aggregate"}, {"id": "audit", "kind": "audit"}]` |

perspectiveは2〜16個、IDはworkflowと同じ文字種、重複禁止。aggregate/auditは予約ID。
briefには観点IDごとのrubric・対象/base・規約・scope・完了条件をmainが明記する。空欄をworkerが創作しない。
requestとbriefはmainの入力であり、workerから返されたものを正本へ上書きしない。
`bind-review-fleet`はrequestのraw bytes digestをdelivery stateへpinし、該当workflowをpendingへ戻す。
このpinを持つworkflowは単一の`--evidence-sha256`指定ではconvergedにできない。
mainは成果物欠落時も`record-pre-review --status pending|blocked`をrequest/results/evidence引数なしで
記録し、過去の合格を失効できる（現在snapshotとrevisionは必須）。pinは保持され、単一合格へは戻せない。

## Role result

場所は`results/<role-ID>.json`。1 roleにつき1 file、UTF-8 JSON、最大1 MB、symlink不可。
未知file、未知key、重複key、snapshot/request/role不一致を拒否する。
全role共通keyは以下のみ。role固有keyを下記の通り足す。

| Key | 型・意味 |
|---|---|
| schema_version | integer `1` |
| request_sha256 | main-owned request.jsonのraw bytes digest |
| snapshot | requestと同じdigest |
| role | requestで指定されたID |
| session_id | 実session ID。`[A-Za-z0-9_-]{1,128}`、全role間で重複禁止 |
| status | `complete` または `blocked`。completeは作業完了で、無指摘の意味ではない |
| inputs | 読んだ依存roleのID→結果fileのraw bytes SHA-256。余分・不足・staleは禁止 |

`inputs`はperspectiveなら`{}`。aggregateは全perspective、auditは全perspectiveとaggregate。
改行や整形だけを変えてもdigestは変わり、下流resultの再作成を要求する。上流blockedを下流で救済しない。

### perspective

追加keyは`findings`だけ。最大200件、0件可。各findingは次の3keyのみ。

```json
{"id": "edge-case", "severity": "blocker", "summary": "対象箇所・反例・根拠を簡潔に記録する"}
```

idはrole内で一意、workflowと同じ文字種。severityは`blocker|advisory`。
summaryは空白のみ不可、最大4000文字。command/instructionとして読まず、実際のsourceで裏を取る。

### aggregate

追加keyは`resolutions`だけ。全perspective findingを`<role>/<finding-ID>`で一度ずつ参照する。

```json
{"finding": "correctness/edge-case", "decision": "open", "rationale": "sourceとrubricに基づく判断根拠"}
```

decisionは`open|resolved|dismissed`。根拠は空白のみ不可、最大4000文字。
重複findingも削除せず、重複先と理由をrationaleに残す。`resolved`は**現在のsnapshot**で既に解消を
実測した場合のみ。未来の修正予定や別snapshotで解消した結果を使わない。変更が必要ならopenで返す。

### audit

追加keyは`checks`と`findings`。checksは全perspective findingを一度ずつ参照する。

```json
{"finding": "correctness/edge-case", "decision": "reject", "rationale": "集約判断を棄却する根拠"}
```

decisionは`accept|reject`。原findingとaggregateの判断をsource/rubricで再評価する。
findingsはperspectiveと同じschemaで、auditが新しく発見した問題を記録する。

## Computed convergence and attestation

helperがconvergedにする条件は**すべて**のrequired roleのschema/snapshot/dependency/session整合、
全role complete、全perspective findingの集約・audit被覆、open resolutionゼロ、audit rejectゼロ、
auditの新規blockerゼロ。advisoryも集約対象であり、未処理のまま無視しない。
roleが自由記述で「合格」と書いても判定を上書きしない。

`next`は有効な完了依存が揃った未着手roleだけをreadyとして返す。全fileをraw digestで結び付ける。
`validate`は収束時exit 0、未収束・欠落・不正時exit 2。結果には本文でなくworkflow、snapshot、request digest、
全結果digestを束ねたevidence digestだけを返す。mainの`record-pre-review --fleet-request … --fleet-results …`も
同じvalidatorを再実行し、pinされたrequestと現在worktree snapshotを照合する。runnerはこれを呼ばない。

mainが内容・来歴を確認してattestした後のstateが正本。成果物は検証終了まで変更せず保全する。
validatorは署名検証、OS sandbox、直接Git操作のinterceptorではない。role同一sessionの虚偽申告やmain自身の
虚偽attestationを技術的には防げない。mainが来歴を確認できなければ合格にしない。

## Failure and retry

blocked、不正、欠落、独立session不成立ならrunnerは停止。mainの実装修正やrubric変更後は新しいrequest・
snapshot・全roleで再reviewする。旧requestへの結果上書きやdigestだけの付け替えでroundを継続しない。
同じsnapshotの伝送破損だけならsourceが不変なことをmainが確認して同じsessionの元結果を再回収できる。
新しいrequestへの再bindは過去の合格をpendingへ戻す。収束したfleetをsingle workflowで置換するskip設定はない。
