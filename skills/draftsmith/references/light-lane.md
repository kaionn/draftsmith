# Light lane

このreferenceはlight laneを選択したrunだけ読む。designer/auditorを省略してもhuman gate、中央検証、
独立review、telemetry contractは省略しない。軸B=要判断で選んだ`light + 独立audit`では手順3の
独立auditを必ず行い、軸B=一意のlightだけが手順3を飛ばす。

1. 目的、AC-n 2〜3件、反証可能な予測、対象repo規範を簡易要件にする。簡易要件は`~/.local/state/draftsmith/runs/{repo}/{task-slug}/requirements.md`へ
   書く。rubricとrun directoryのpathはfull laneと同じ文字種・containment規則で検証する。
   `--gated`では要件確定gateを置く。
2. 対象ファイルを実際にReadしたmainが`templates/reply-contract.md`要素1と同じアンカー付きbriefを
   `runs/{repo}/{task-slug}/designer-return.md`へ書く（構造ビジュアルと調査済みファイル小節は
   省略してよい）。mini-ADRは軸B=一意なら「なし（方針一意）」とし、`light + 独立audit`では
   採用案・却下案・根拠を1件だけ書く。`plans/<task>.md`を`Status: designed`で書く。同名は
   上書きしない。アンカー特定に調査が必要ならこの時点でfullへ昇格する。mini-ADR相当の判断が
   2件以上になる、または判断が公開契約・データモデル・他タスクへ波及する場合もfullへ昇格する。
3. （`light + 独立audit`だけ。`--no-audit`時は省略）briefのpathと簡易要件、書き込み先`audit.md`の
   pathを独立auditorへ渡し、1巡監査させる。returnは件数とhigh見出しだけで、全文は`audit.md`に
   ある。auditor highは反映し、棄却はrootのconsultant protocolに従う。high指摘が設計の作り直しを
   要求するならfullへ昇格する。反映分はbrief全文を書き直さず`brief-addendum.md`へ書く。
   medium/lowの採否理由はAI判断へ残す。監査painはrootの`category + cause enum + target kind`
   だけで記録し、`auditor_round` eventを1回記録する。
4. `designer-return.md`と（あれば）`brief-addendum.md`のpath、書き込み先`implementer-report.md`の
   pathをimplementerへ渡し、宣言したturn内で起動する。brief本文をpromptへ転記しない。mainが
   repo規約からformat/lint/testを検出して実行し、rubric、diff、予測を実測する。アンカー不一致を
   推測で補わせない。
5. reviewer-lightへrubric、簡易要件の目的・スコープ外・非機能要件、diffを渡して1巡する。ACは
   rubricを正本とし、要件とrubricで二重に渡さない。妥当な指摘はtargeted修正しmainが再検証する。
   再reviewはしない。指摘が設計判断へ踏み込むならfullへ昇格する。棄却理由はAI判断へ残す。
6. planを`Status: implemented`へ更新し、レーン理由（軸A・軸Bの判定と独立auditの有無）とAI判断を
   転記する。audit proposal-checkを行う。goalが`implemented`ならtelemetryを
   `--final-phase implemented`でfinishし、変更・AI判断・検証・残課題の4項目で報告する。後段goalなら
   finishせず、delivery stateを`phase=implemented`で初期化してdelivery loopへ引き継ぐ。

アンカー特定に調査が要る、implementerの不一致が構造的、review指摘が設計判断へ踏み込む、
auditor highが設計の作り直しを要求する、のいずれかでfullへ昇格し手順1からやり直す。
fullからlightへ降格しない。
