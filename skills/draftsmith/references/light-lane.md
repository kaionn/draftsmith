# Light lane

このreferenceはlight laneを選択したrunだけ読む。designer/auditorを省略してもhuman gate、中央検証、
独立review、telemetry contractは省略しない。

1. 目的、AC-n 2〜3件、反証可能な予測、対象repo規範を簡易要件にする。rubric pathはfull laneと
   同じ文字種・containment規則で検証する。`--gated`では要件確定gateを置く。
2. 対象ファイルを実際にReadしたmainが`templates/reply-contract.md`要素1と同じアンカー付きbriefを
   作る。mini-ADRは「なし（方針一意）」とし、`plans/<task>.md`を`Status: designed`で書く。同名は
   上書きしない。アンカー特定に調査が必要なら、この時点でfullへ昇格する。
3. brief全文をimplementerへ渡し、宣言したturn内で起動する。mainがrepo規約からformat/lint/testを
   検出して実行し、rubric、diff、予測を実測する。アンカー不一致を推測で補わせない。
4. reviewer-lightへ要件、rubric、diffを渡して1巡する。妥当な指摘はtargeted修正しmainが再検証する。
   再reviewはしない。指摘が設計判断へ踏み込むならfullへ昇格する。棄却理由はAI判断へ残す。
5. planを`Status: implemented`へ更新し、レーン理由とAI判断を転記する。audit proposal-checkを行う。
   goalが`implemented`ならtelemetryを`--final-phase implemented`でfinishし、変更・AI判断・検証・
   残課題の4項目で報告する。後段goalならfinishせず、delivery stateを`phase=implemented`で初期化して
   delivery loopへ引き継ぐ。

アンカー特定に調査が要る、implementerの不一致が構造的、review指摘が設計判断へ踏み込む、の
いずれかでfullへ昇格しStep 1からやり直す。fullからlightへ降格しない。
