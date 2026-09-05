# Full lane

このreferenceはfull laneを選択したrunだけ読む。

## Step 1: 要件とrubric

`templates/requirements.md`へ8項目を埋め、空欄は「特になし」または「不明」と明記する。全受け入れ
基準へAC-nを付け、反証可能な予測を2〜3行書く。対象scopeの`AI_CONTEXT.md`、CLAUDE.md、テスト規約
等の規範ファイルは全文Readせず、`rg -n`で見出し行と拘束語（必ず / 禁止 / しない / MUST / NEVER /
規約 等）を含む行だけを抽出し、該当節だけを範囲指定でReadして、implementerが参照先を開かなくても
守れる粒度で非機能要件へ転記する。転記した節は要件書5節の先頭に「転記元: path（節名）」として
明記し、designer / auditor / reviewer-lightが同じファイルを再読しない根拠にする。

```bash
rg -n '^#|必ず|禁止|しない|MUST|NEVER|規約' AI_CONTEXT.md CLAUDE.md
```

要件書は`~/.local/state/draftsmith/runs/{repo}/{task-slug}/requirements.md`へ書き、
`shasum -a 256`のdigestを控える。run directoryのrepo名とtask slugはrubricと同じ文字種・containment
規則で検証する。

現在の環境で`plan` Skillが作ったPlanをユーザーが指定した場合は、それを一次入力として再利用し、
同じ調査やAC導出を最初から繰り返さない。現コードと矛盾する箇所だけ再調査する。draftsmith固有の
要件正規化、rubric、designer/auditorの独立監査は省略しない。

`templates/rubric.md`へ全AC、検証方法、期待結果を書く。repo名とtask slugは英数字、`. _ -`だけを
許し、空、`.`、`..`、path separator、absolute pathを拒否する。rubricのresolved pathが
`~/.local/state/draftsmith/rubrics/`配下に収まることを確認する。

自律モードでは既存挙動維持・scope最小・可逆性でも埋められない本質的な穴だけを1点確認する。
`--gated`では要件書全体の一括sign-offを先に求めず、重要な未決事項を優先順に並べて一度に一論点だけ確認する。
各質問には推奨デフォルトと理由1行、結果を実質的に変える代替案を添え、人間は推奨の採用、別案の指定、
または追加説明の依頼を選べるようにする。回答を要件書とrubricへ反映してから次の論点へ進む。
重要な未決事項が残る間は要件確定を宣言せずStep 2へ進まない。すべて解消した後に要件全文を提示し、
要件確定gateを通す。

## Step 2: designer

起動前に`runs/{repo}/{task-slug}/designer-return.md`の有無を確認する。存在し、先頭行の
`requirements-sha256`が現在の要件書digestと一致すれば、designerを再起動せずそのファイルを
再利用してStep 3へ進む（resume後の同一prompt二重起動を防ぐ）。不一致なら再起動する。

```bash
python3 <skill-root>/scripts/check_reply_contract.py \
  ~/.local/state/draftsmith/runs/<repo>/<task-slug>/designer-return.md \
  --requirements ~/.local/state/draftsmith/runs/<repo>/<task-slug>/requirements.md
```

起動時は要件書のpath（要約せず全文をdesignerがReadする）、要件書digest、書き込み先
`designer-return.md`のpath、`templates/reply-contract.md`の出力契約をdesignerへ渡す。agent起動を
宣言したturn内で実際に起動する。returnは「path + 見出しごとの行数 + 要素2・3の全文 + 要素4の表」
だけで、要素1と要素5はファイルにだけある。mainはreturn後に上の`check_reply_contract.py`を実行し、
exit 1なら出力の箇条書きだけを添えて形式違反として差し戻す。ファイル本文を読んで補わない。
形式が通ったら要素2・3・4（return要約にある）だけを読んで判断し、要素1全文はStep 3〜5の
auditor / implementerに読ませる。

`--gated`では5要素を増やさず、要素1の必須の構造ビジュアル直後へ次の形式で参照専用の表示素材を
含めるようdesignerへ追加指示する。

```md
<!-- gated-display-material:start; reference-only -->
### 一言要約
{目的と変更結果を意味追加なしの一文で書く}

### 読む前提
{前提を1行に1件ずつ、Markdownの箇条書き記号や連番を付けずに書く}

### 判断素材
{重要判断が無い場合は「重要判断なし」と書く。ある場合は次の形式をD-01から最大D-05まで繰り返す}

#### 判断素材 D-01
- 何を決めたか: {...}
- なぜか: {...}
- 別案を選ぶと何が壊れるか: {...}
- 原文根拠: {確定要件またはreturn内の要素番号・節名と逐語引用}
<!-- gated-display-material:end -->
```

判断素材は重要度順に0〜5件とする。重要判断が0件であることは正当な出力であり、
`重要判断なし`を表示素材として残す。判断素材がある場合は、確定要件と5要素に明記された事実だけで
作り、反実仮想や根拠を推測で補わない。必要フィールドを根拠付きで書けない場合は要素2または要素3へ
未解決として報告する。mainは欠けた素材を創作せずdesignerへ差し戻す。

開始・終了コメントで囲まれた範囲は参照専用であり、implementerへの編集指示ではない。
これは要素1内部のgated表示素材であり、`templates/reply-contract.md`の5要素構成と非gatedの
designer returnは変更しない。

`--fable`はユーザーが明示指定した場合、会話で許可した場合、またはmini-ADR 3件規模等の重量級で
1回だけ提案して承認された場合に限る。失敗時は既定modelへ戻し、選択経緯をAI判断へ記録する。
designer以外へこの選択を広げない。

## Step 3: 独立監査

`designer-return.md`のpathと、確定要件の項目1〜7（背景・目的・スコープ・スコープ外・非機能要件・
受け入れ基準・未決事項）、書き込み先`audit.md`のpathを独立auditorへ渡す（`--no-audit`時だけ
省略）。項目8「参照情報」と反証可能な予測は渡さない。前者はdesignerの調査起点であり監査の判断に
使われず、後者は下の3.でmainだけが使う検査軸で、渡すと独立監査が予測へアンカーする。auditorの
returnは「指摘あり N 件 / 指摘なし」の1行とhigh指摘の見出し行だけで、全文は`audit.md`にある。
mainはhighの対象行を読んで採否を決め、medium/lowは`audit.md`の該当節だけを範囲指定で読む。
同時にmainが次を行う。

1. 全ACがtraceability表に一度ずつ存在するか（`check_reply_contract.py`の結果で足りる）。
2. mini-ADRの文脈が要件の具体箇所を根拠にしているか。
3. Step 1の予測との乖離に説明が付くか。

auditor highは反映する。棄却はrootのconsultant protocolを必須とする。medium/lowの採否も理由を
AI判断へ残す。auditorの予測だけを根拠に確定設計を書き換えず、実装時の注意として扱う。
typo等だけmainが直接直し、設計判断に触れる差し戻しは違反箇所だけをdesignerへ返す
（designerは`designer-return.md`を上書きし、digest行を保つ）。

監査painはrootの`category + cause enum + target kind`だけで記録する。review本文、顧客情報、自由記述
理由をfingerprintへ入れない。

## Step 4: 設計確定とplan

確認事項を既存挙動維持・scope最小・可逆性で確定し、designerの推奨を黙って置換しない。mainは
brief全文を書き直さず、auditor指摘の反映分と確認事項の確定値だけを`brief-addendum.md`へ書く。
addendumは「対象ファイル・対象アンカー・差し替え後の指示」の単位で書き、取り消す指示は
「取り消し」と明記する。変更が無ければ「変更なし」1行のファイルにする。自律モードでは従来どおり
HTMLを作らず、`designer-return.md` + `brief-addendum.md`を確定briefとしてStep 5へ進む。

`--gated`では設計確定を理解確認gateとして扱う。`templates/brief-visual.md`に従い、確定要件全文
（`requirements.md`）とdesigner return（`designer-return.md`）の参照専用表示素材・5要素を
自己完結HTMLへ機械的に投影する。入力元がファイルになるだけで構造は変えない。表示順は
「一言要約 → 読む前提 → 構造 → 判断カード → 原文根拠」とし、描画・目視後に人間へ提示する。
mainは要約、前提、判断、理由、反実仮想、根拠を新しく生成しない。重要判断が0件の場合も
`重要判断なし`を表示して理解確認gateを継続する。

提示後は、実装開始を承認するか、存在するカード ID を指定して深掘りするかを人間に選んでもらう。
深掘りでは指定カードの判断、理由、反実仮想、原文根拠だけに論点を絞って説明する。新しい未決事項や
設計変更が見つかった場合は該当するStep 1またはStep 2〜3へ戻り、HTMLを再生成する。
未解消の疑問が残る間は Step 5 へ進まない。理解度の採点や正解文の復唱は要求せず、人間から明示的な
実装開始承認を得た時だけ設計を確定する。

設計確定後、`templates/plan-file.md`で`plans/<task>.md`を`Status: designed`として書く。同名は
上書きせず連番にする。一時planを置くべきでないrepoでは省略理由を報告する。

## Step 5: implementerと中央検証

`designer-return.md`と`brief-addendum.md`のpath（addendumが優先）、書き込み先
`implementer-report.md`のpathをimplementerへ渡し、宣言したturn内で起動する。brief本文を
promptへ転記しない。implementerのreturnは「編集ファイル数 / スキップ件数 / 検証の合否」の1行と
スキップ見出しだけで、詳細は`implementer-report.md`にある。`--gated`の要素1にある
`<!-- gated-display-material:start; reference-only -->`から
`<!-- gated-display-material:end -->`までと、従来の構造ビジュアルは参照専用であり、
編集・追加・削除の適用指示ではないと明示する。implementerはその範囲を実装対象として数えず、
要素1内の逐語編集指示だけを適用する。

アンカー不一致は推測で補わせず、skipとして報告させる。mainがrepoのMakefile、mise.toml、
package scripts、CI、規約からformat/lint/testを検出して実行し、rubricの判定列を実測結果で更新し、
`git diff`全体を読む。成果物をdesignerへ戻して自己reviewさせない。

## Step 6: reviewer-light

rubric、確定要件の目的・スコープ外・非機能要件、diffを渡す。ACはrubricを正本とし、要件とrubricで
二重に渡さない。妥当な指摘はtargeted briefでimplementerへ戻す。2巡目以降は前回指摘の
解消と修正差分の新規問題だけを見る。同一論点が3回続く、または3巡で収束しなければblockedにし、
残件を人間へ提示する。棄却した指摘も理由をAI判断へ残す。

## Step 7: 完了

planへレーン判断、要件補完、確認事項、auditor採否、consultant諮問、保守的仮定を転記する。goalが
`implemented`なら、plan status更新・audit proposal-check・telemetry finishを1コマンドで束ねる。

```bash
python3 <skill-root>/scripts/run_telemetry.py --repo . finish --run-id <id> \
  --expect-revision <revision> --final-phase implemented \
  --promote-check --plan-file plans/<task>.md --plan-status implemented \
  [--cost-from <main transcript .jsonl>]
```

変更・AI判断・検証・残課題の4項目で報告する。後段goalならここではfinishせず、planを
`Status: implemented`へ更新し、delivery stateを`phase=implemented`で初期化してdelivery loopへ
引き継ぐ。

監査painのcauseとtargetは自由記述にせずrootのstructured record interfaceを使う。inner loopの
findingだけをrun telemetry eventへ記録する。PR deliveryへ入った後のfindingはreview fingerprintを
持つdelivery stateへだけ記録し、finish時の一回投影に任せる。

designer/implementerへの同一論点の差し戻しが2往復を超えたら停止する。mini-ADRが3件を超える等、
1タスクとして大きすぎる場合は分割案を提示し、勝手にscopeを変えない。
