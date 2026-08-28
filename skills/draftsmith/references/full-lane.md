# Full lane

このreferenceはfull laneを選択したrunだけ読む。

## Step 1: 要件とrubric

`templates/requirements.md`へ8項目を埋め、空欄は「特になし」または「不明」と明記する。全受け入れ
基準へAC-nを付け、反証可能な予測を2〜3行書く。対象scopeの`AI_CONTEXT.md`、CLAUDE.md、テスト規約
等を読み、implementerが参照先を開かなくても守れる粒度で非機能要件へ転記する。

現在の環境で`plan` Skillが作ったPlanをユーザーが指定した場合は、それを一次入力として再利用し、
同じ調査やAC導出を最初から繰り返さない。現コードと矛盾する箇所だけ再調査する。draftsmith固有の
要件正規化、rubric、designer/auditorの独立監査は省略しない。

`templates/rubric.md`へ全AC、検証方法、期待結果を書く。repo名とtask slugは英数字、`. _ -`だけを
許し、空、`.`、`..`、path separator、absolute pathを拒否する。rubricのresolved pathが
`~/.local/state/draftsmith/rubrics/`配下に収まることを確認する。

自律モードでは既存挙動維持・scope最小・可逆性でも埋められない本質的な穴だけを1点確認する。
`--gated`では要件確定gateを置く。

## Step 2: designer

要件全文を要約せず、`templates/reply-contract.md`の出力契約5要素とともにdesignerへ渡す。agent起動を
宣言したturn内で実際に起動する。5要素が欠けたreturnは内容を読んで補わず、形式違反として差し戻す。

`--fable`はユーザーが明示指定した場合、会話で許可した場合、またはmini-ADR 3件規模等の重量級で
1回だけ提案して承認された場合に限る。失敗時は既定modelへ戻し、選択経緯をAI判断へ記録する。
designer以外へこの選択を広げない。

## Step 3: 独立監査

要件全文とdesigner return全文を独立auditorへ渡す（`--no-audit`時だけ省略）。同時にmainが次を行う。

1. 全ACがtraceability表に一度ずつ存在するか。
2. mini-ADRの文脈が要件の具体箇所を根拠にしているか。
3. Step 1の予測との乖離に説明が付くか。

auditor highは反映する。棄却はrootのconsultant protocolを必須とする。medium/lowの採否も理由を
AI判断へ残す。auditorの予測だけを根拠に確定設計を書き換えず、実装時の注意として扱う。
typo等だけmainが直接直し、設計判断に触れる差し戻しは違反箇所だけをdesignerへ返す。

監査painはrootの`category + cause enum + target kind`だけで記録する。review本文、顧客情報、自由記述
理由をfingerprintへ入れない。

## Step 4: 設計確定とplan

確認事項を既存挙動維持・scope最小・可逆性で確定し、designerの推奨を黙って置換しない。`--gated`
では`templates/brief-visual.md`を自己完結HTMLとして描画・目視し、崩れを直してから人間へ提示する。
自律モードではこのHTMLを作らない。

`templates/plan-file.md`で`plans/<task>.md`を`Status: designed`として書く。同名は上書きせず連番にする。
一時planを置くべきでないrepoでは省略理由を報告する。

## Step 5: implementerと中央検証

確定brief全文をimplementerへ渡し、宣言したturn内で起動する。アンカー不一致は推測で補わせず、
skipとして報告させる。mainがrepoのMakefile、mise.toml、package scripts、CI、規約からformat/lint/testを
検出して実行し、rubricの判定列を実測結果で更新し、`git diff`全体を読む。成果物をdesignerへ戻して
自己reviewさせない。

## Step 6: reviewer-light

要件全文、rubric、diffを渡す。妥当な指摘はtargeted briefでimplementerへ戻す。2巡目以降は前回指摘の
解消と修正差分の新規問題だけを見る。同一論点が3回続く、または3巡で収束しなければblockedにし、
残件を人間へ提示する。棄却した指摘も理由をAI判断へ残す。

## Step 7: 完了

planを`Status: implemented`へ更新し、レーン判断、要件補完、確認事項、auditor採否、consultant諮問、
保守的仮定を転記する。audit proposal-checkを一度行う。goalが`implemented`ならtelemetryを
`--final-phase implemented`でfinishし、変更・AI判断・検証・残課題の4項目で報告する。後段goalなら
ここではfinishせず、delivery stateを`phase=implemented`で初期化してdelivery loopへ引き継ぐ。

監査painのcauseとtargetは自由記述にせずrootのstructured record interfaceを使う。inner loopの
findingだけをrun telemetry eventへ記録する。PR deliveryへ入った後のfindingはreview fingerprintを
持つdelivery stateへだけ記録し、finish時の一回投影に任せる。

designer/implementerへの同一論点の差し戻しが2往復を超えたら停止する。mini-ADRが3件を超える等、
1タスクとして大きすぎる場合は分割案を提示し、勝手にscopeを変えない。
