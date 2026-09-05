# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.0.0] - 2026-09-05

### Changed

- designer / auditor / implementerの成果物を「ファイル本体 + return要約」の二層にした。designerは`~/.local/state/draftsmith/runs/{repo}/{task-slug}/designer-return.md`へ5要素の全文を書き（先頭行に要件書のsha256）、returnはpath・行数・要素2〜4だけを返す。auditorは`audit.md`、implementerは`implementer-report.md`へ全文を書く。mainはbrief全文を書き直さず、監査後の差し替え分だけを`brief-addendum.md`に書き、implementerへはpathを渡す。新しい`scripts/check_reply_contract.py`が5要素の見出し、要素4のAC網羅、調査済みファイル小節、requirements digestを機械検査し、digestが一致する既存returnがあればdesignerを再起動しない
- 5 agent定義（designer / auditor / consultant / implementer / reviewer-light）に調査の一括発行規律を追加した。依存のないRead / Grep / Glob / Bashは同一メッセージで発行し、現物はBashの`cat`ではなくReadで開き、要件書へ転記済みの規範ファイルは再読せず、調査turnの目安（designer 12 / auditor 10 / reviewer-light 8 / implementer 8 / consultant 6）を超えたら現時点の結論で返す
- designerの要素1末尾に必須小節「調査済みファイル」（`path — 確認した事実（file:line）`）を追加し、auditorはその一覧から読み始めて一覧外は接合面検査に必要な呼び出し元・テストだけを開くようにした。独立性は結論の検証で担保し、探索の重複を省く
- full lane Step 1とlight lane手順1で、`AI_CONTEXT.md`・CLAUDE.md等の規範ファイルを全文Readしなくした。`rg -n`で見出しと拘束語の行を抽出して該当節だけ範囲Readし、要件書の非機能要件に「転記元: path（節名）」を明記してsubagentが再読しない根拠にする
- 帳簿のBash呼び出しを束ねた。`run_telemetry.py start --run-card`がrun cardとstartを1つのJSONで返し、`finish --promote-check`がaudit-ledgerのpromote-checkを同じprocessで実行（script不在・失敗はwarning）、`finish --plan-file <path> --plan-status implemented`がplanの`- Status:`行を書き換える
- SKILL.mdに「Agent起動時に`model` / `effort`を渡さない（例外は`--fable`指定時のdesignerだけ）」を追加した。上書きが必要な場合はAI判断へ理由を記録し、run cardへ表示する

### Added

- `scripts/run_cost.py`: session transcript（mainと`subagents/*.jsonl`）からrole別のturn数、平均・最大context、output、cache read / creation、durationを集計する。本文・path・promptは出力しない。`run_telemetry.py finish --cost-from <main.jsonl>`がこの集計をreceiptの`cost`ブロックへ投影し（schema additive）、`receipt_proposals.py`が`cost_hotspots`としてcache read上位2 roleをproposal材料に載せる。finishはcountersが全0なら`--force-empty`が無い限りwarningを出す

## [2.1.0] - 2026-09-05

### Added

- delivery runをsession単位でpark / resumeできるようにした。`delivery_state.py park`が散文のpark noteをGit metadata配下へ0600で書き、`parked_head_sha`と`park_round`、`parked_revision`を記録する（phaseは変えない）。`resume-brief`が次のsessionへphase、PR、HEAD差分、park後のstate差分、note、reconcile checklistを返す
- plugin hooksを追加した。SessionStart（`startup|resume|clear|fork`）がpark中のworktreeでresume briefを注入し、Stopが未parkのまま終わろうとしたときだけpark手順を示してblockする。未parkの判定はrevisionとHEADの両方で行うので、HEADを動かさないreview往復も検出する

## [2.0.0] - 2026-09-04

### Changed

- lane判定を「変更の広がり」「設計判断の有無」の2軸へ変更し、「迷えばfull」を廃止。小さいが判断を要する変更にはdesignerを起動せず、mainのbriefを独立auditorが1巡監査する`light + 独立audit`を追加した（laneは`light`として記録し、`auditor_round` eventで観測できる）
- `delivery × implemented`が拒否された依頼を黙って`requirements`へ落とさず、既存差分・既存PRの継続とnew実装を実体で分ける規範を明示。再マップしたrunのlaneをentry再マップ理由でfullへ倒さないようにした
- auditorとreviewer-lightへ渡す入力から、監査・レビューの判断に使われない項目を除いた。auditorには要件の項目8「参照情報」とmainの反証可能な予測を渡さず、reviewer-lightへはrubricを受け入れ基準の正本として渡して要件とrubricの二重渡しをやめた
- designerとreviewer-lightの役割境界を構造的な制約として明文化。成果物をBashで書き出さない、Bashは読み取り専用調査に限る、調査範囲を対象repoと要件書の参照先に限る、returnを出力契約だけで構成する、を追加した
- root Skillとdelivery-loop referenceで重複していたentry/goal正規化とreceipt制約の記述を、rootを正本とする参照へ置き換えた

### Changed

- full laneの`--gated`を理解確認フローへ強化。要件の重要な未決事項を一論点ずつ確認し、設計briefを一言要約・前提・構造・最大5件の根拠付き判断カード・確定要件を含む原文根拠の順に表示して、カードIDによる深掘り後に実装開始を承認できるようにした

## [1.14.0] - 2026-08-28

### Added

- 自然言語routing、lane、human gate、再開、untrusted inputを固定するbehavioral evalとcontract validatorを追加
- `implemented`を含む全run向けに、opaque ID・enum・counter・duration・timestampだけを保存するv2 telemetry、読み取り専用doctor/status/run-card、clean full-head evidence packet、既存成果物だけを束ねるreview cockpitを追加
- v1/v2 receiptを混在のまま読み、2件以上で反復したsignalだけをproposalにするread-only改善helperを追加
- 人間が採用・却下したproposalを記録し、採用後5 runの発生率から撤回候補を判定するlifecycle helperを追加

### Changed

- root Skillをroutingと不変条件へ縮め、full/light/artifact/delivery詳細を条件付きreferenceへ分割
- audit painのfingerprintをcategory・structured cause・target kindへ変更し、constitution自動追記を廃止してproposal-onlyに変更
- before画面証跡はstashを使わず、`pr-verify-report`または専用worktreeで取得する規範へ変更
- diff review、E2E判定、commitは既存の`diff-review`、`verify-report`、`plan-commit`を正本として再利用し、別のlifecycle stateを持つSkillはdraftsmith deliveryと併用しない

## [1.13.1] - 2026-08-27

### Fixed

- Codexが自然言語からdraftsmithを選択した直後、本文を読む前に非canonicalなentry/goal名を推測しないよう、共通descriptionへ`requirements` / `delivery` entryと全goalの決定的な写像を追加

## [1.13.0] - 2026-08-27

### Added

- Claude/Codexの暗黙Skill選択を明示的に有効化し、「設計から実装して」「このPRのCI・レビュー対応を続けて」「マージまで進めて」等の自然言語をrequirements/delivery entryと到達goalへ正規化するrouting contractを追加。slash commandでの言い直しを求めず、従来の個別human gateは維持する

## [1.12.0] - 2026-08-27

### Added

- delivery state schema v2: review thread IDとhead SHAから作る非可逆fingerprint、disposition、CI/設計/実装/人間判断counter、single-driver leaseを追加。v1 stateは読み込み時にv2へ正規化し、次回updateで移行する
- privacy-minimal delivery receiptとproposal-only改善adapterを追加。receiptはcounter、cycle、elapsed timeだけを持ち、review本文・fingerprint一覧・authorizationを含めない
- manual/runtime monitor/GitHub eventを同じbounded advanceへ接続するdriver adapterを追加
- opt-in `merged` goalと`merge_gate`を追加。ready化とmergeは別々のhuman gateで、GitHubのmerged stateを実測した場合だけdoneへ進む

### Changed

- validate/release workflowの`actions/checkout`をv5、`actions/setup-python`をv7へ更新し、Node.js 20廃止warningを解消

## [1.11.0] - 2026-08-27

### Added

- opt-in PR delivery lifecycle: `/draftsmith --through-review`で従来の要件・設計・監査・実装・reviewer-light完了後に、plan-commitのhuman gate、draft PR、required CI、bot/human review、review修正、最新headのfinal verificationまで続行できるようにした。既定goalは従来どおり`implemented`で、暗黙にcommit・push・PR作成へ進まない
- late entryと到達goal: `--from=delivery`でdesigner/auditor/初回implementerをskipして既存branch/PRから再開でき、`--goal=pr_open|review_requested|review_complete|merge_ready`で停止地点を選べる。`--through-review`は`review_complete`へのshortcut
- `draftsmith-next`は`--through-review`と後段`--goal`をrequirements entryへ伝搬し、delivery完了後にmanual commit案内を重複させない。Plans.mdの新規taskと矛盾する`--from=delivery`は拒否する
- re-entrant delivery state: phase、goal、plan相対path、commit/head SHA、PR番号、enum観測値だけをGit metadata配下へ600権限・atomic replaceで保存するhelperを追加。cross-process lockと`revision` CASで同時sessionのlast-write-winsを拒否し、通常/linked worktree・detached HEAD・不正遷移・schema・stale revision・lock競合を回帰テストする
- PR validation CI: Python 3.10/3.13で標準unit test discoveryを実行し、delivery goal/phaseの文書被覆、plugin/marketplace/frontmatter整合、PR差分のwhitespaceをmerge前に検査するworkflowを追加

### Changed

- PR feedbackを実装指摘・設計/要件指摘・質問/人間判断へ分類し、実装指摘はtargeted implementer + reviewer-light、設計指摘はdesigner + auditorへ戻すback edgeを定義した。reply、resolve、push等の外部変更はそれぞれhuman gateを維持する

## [1.10.0] - 2026-08-15

### Added

- 出力契約 要素 1 に「構造ビジュアル」小節を追加: designer は brief の冒頭に、変更後のコードの形を示すビジュアル 1 点（ファイルツリー / Mermaid / 疑似コード / diff スケッチから 1 形式）を置く。人間と auditor が編集指示を読む前に設計の形を検査するためのもので、implementer は参照情報として扱い適用対象にしない。light レーンでは省略可（HumanLayer の show-me スキルの形式選択の考え方を取り込んだもの）

## [1.9.0] - 2026-08-13

### Added

- rubric 検証: `templates/rubric.md` を新設（受け入れ条件ごとに criterion / 検証方法 / 期待結果 / 判定の 5 列テーブル）。reviewer-light に第 0 レンズとして事前 rubric の実測照合を追加し、SKILL.md の中央検証へ rubric コマンド実行を統合
- 監査 pain 台帳と constitution 自動昇格: `scripts/audit-ledger.sh` を新設（bash + jq、fail-open）。監査 3 層からの差し戻しをカテゴリ enum で記帳し、同一カテゴリ 3 回で `constitution.md` へ自動昇格。designer は起動時に constitution.md を読んで設計制約として反映する
- gated モードの設計 brief HTML 可視化: `templates/brief-visual.md` を新設。設計確定ゲートで designer 出力 5 要素を自己完結 HTML（外部 CDN 非依存）へ流し込んで生成・open し、整形された brief をブラウザでレビューできるようにした

## [1.8.1] - 2026-08-09

### Changed

- `draftsmith-next` を `skills/adapters/` 配下へ移設し、タスク供給元ごとのアダプタ層を分離した。`plugin.json` の `skills` に `./skills/adapters/` を追加して discovery を維持しており、スキルの呼び出し名 `draftsmith-next` は変わらない

## [1.8.0] - 2026-08-09

### Added

- draftsmith-next スキル: claude-code-harness の Plans.md から未着手タスクを 1 件選んで draftsmith へ橋渡しするグルースキルを追加。Plans.md は読み取りのみで、cc: マーカーの更新は harness-sync の領分として持たない

### Changed

- Step 1 / Step L2: 対象リポジトリの実装規範ドキュメント（AI_CONTEXT.md、CLAUDE.md の実装ルール等）を確認し、拘束となる規範を要件書の「5. 非機能要件」（light は brief）へ転記する手順を追加。designer / implementer が要件書と brief しか読まない前提を規範面でも成立させる
- Step 6: reviewer-light ループに「発見と検証の分離」を導入。2 巡目以降の再レビューは「前回指摘の解消確認 + 修正差分の新規問題」に範囲を限定し、停止条件に「3 巡しても収束しない場合は人間へ」を追加（全差分の発見レビューを繰り返すと原理的に収束しない実測知見の吸収）

## [1.7.0] - 2026-07-25

### Added

- /verify-report のレポートで証跡スクショをクリックすると、オーバーレイで拡大表示できるようになった（クリックまたは Esc で閉じる）。原寸がグリッド幅より小さい画像も `object-fit: contain` でビューポートに収まる最大サイズへ拡大する
- 拡大表示のアクセシビリティ: 明示的な × 閉じるボタンを追加し、スクショをキーボード操作（Tab でフォーカス + Enter / Space）でも開けるようにした。開くと × ボタンへ、閉じると元のスクショへフォーカスが移る
- /diff-review: グループレベルの `plan_note`（Pass 2 でのグループ全体照合サマリー）を出力契約に正式追加し、レビュー画面に「plan 照合」として描画するようにした。個別指摘に紐づく備考は従来どおり finding 側の `plan_note` に書く
- /verify-report: 「従来から変わらない」系 AC には実装前の同一画面スクショ（before）も証跡に含める運用を Step 3 に明記。before が無い場合に needs_human になるのは正しい出力として受け入れる

## [1.6.0] - 2026-07-25

### Added

- /verify-report スキル: 実装後の E2E 検証を証跡スクリーンショット付きの自己完結 HTML レポートにする。plan ファイル（または指定シナリオ）の受け入れ基準ごとに main がブラウザ操作でスクショを収集し、実装 diff を知らない evidence-reviewer が fresh context でスクショだけを目視して pass / fail / needs_human を判定する（自己追認の排除）。レポートはスクショを data URI で埋め込んだ単一 HTML で、AC × 証跡 × 判定の対応表と PR 転記用サマリー（markdown 生成 + クリップボードコピー）を含む。全 AC の判定被覆はビルドスクリプトが機械検証する
- evidence-reviewer エージェント（sonnet / read-only / vision）: AC 一覧と証跡スクショだけを受け取り、写っている事実を根拠に判定する。証跡が無い・読み取れない AC は needs_human に倒し、雰囲気 pass を許さない。AC 外で気づいた異常は extra_findings として報告する

### Changed

- release.yml の `workflow_dispatch` に `bump` 入力（none / patch / minor / major）を追加し、`gh workflow run release.yml -f bump=minor` の一発でリリース全体（bump → main push → tag → Release）が GHA 内で完結するようになった。GITHUB_TOKEN の push は push トリガーを発火しないため、bump 後の tag / Release も同一 run 内で続けて実行する。`bump=none`（既定）は従来どおりの救済起動（現在値で tag / Release のみ）。ローカルの `release.sh` + push 経路も従来どおり使える

### Fixed

- `scripts/release.sh` の CHANGELOG 編集を `sed` から `perl -i -pe` に置き換え、BSD/GNU 非互換（`sed -i` の引数の有無・`i\` 行挿入構文）を解消した。macOS ローカルと Linux runner の双方で同じ結果になる
- 比較リンク生成の repo URL ハードコードを除去し、既存の `[Unreleased]:` 行からキャプチャして使うようにした（リンク更新と新バージョン行の挿入も 1 パスに統合）

## [1.5.0] - 2026-07-25

### Added

- plan ファイル（一時設計文書）: /draftsmith が設計確定後に `plans/{task-slug}.md` を書き出す（`--no-plan-file` で省略可）。1 タスク分の設計意図（目的・受け入れ基準・設計要旨・mini-ADR・AI が下した判断）を保持する一時文書で、タスク台帳（Plans.md）の代替ではない。テンプレート `templates/plan-file.md` を追加
- /plan-commit スキル: plan ファイルを「subject 一行 + body に設計文書」のコミットメッセージへ畳み込み、プレビューを人間が承認してからコミットして plan ファイルを削除する。設計意図の永続化先をファイルから git 履歴に移す唯一の経路（push・PR 作成はしない）
- /diff-review Pass 2 の背景情報探索: repo ルートの `plans/*.md`（一時設計文書）を自動発見して plan 照合に使う

## [1.4.0] - 2026-07-25

### Added

- リリース自動化: `.github/workflows/release.yml` を追加し、`main` への push（`.claude-plugin/plugin.json` の変更を含むもの）で annotated tag 作成と GitHub Release の公開までを完結させた。手動の `git push --tags` / `gh release create` は不要になり、リリース手順は `./scripts/release.sh <bump>` + `git push origin main` の 2 コマンドになる。tag / Release はいずれも「既存ならスキップ」で冪等。取りこぼし時は `gh workflow run release.yml` で救済発火する（対象バージョンは常に `plugin.json` の現在値）
- `scripts/changelog-section.sh`: CHANGELOG から指定セクション（バージョン or `Unreleased`）の本文を抽出する。GitHub Release のノート生成に使い、本文が空なら exit 1 でリリースを止める

### Changed

- `scripts/release.sh` は tag を作らず commit までを担うようになった（tag は workflow が作成するため）。あわせて `[Unreleased]` が空のまま昇格しようとした場合に abort するガードを追加（ノートが空の Release を push 前に防ぐ）
- GitHub Release のノートが `--notes-from-tag`（tag メッセージ = バージョン文字列のみ）から CHANGELOG の該当セクション本文に変わり、実質空だったリリースノートが埋まるようになった

## [1.3.0] - 2026-07-25

### Added

- /diff-review フィードバック組み立て: レビュー画面に指摘ごとの採用 / 却下（未判定含む 3 状態）と指摘・グループ単位のコメント欄を追加。「フィードバックを生成」で採用された指摘 + 追加コメントを元の作業エージェントに渡す markdown に整形し、「クリップボードにコピー」でそのままセッションへ貼れる導線を用意（状態は localStorage 永続）。markdown 冒頭には忖度なしの精査を求める定型依頼文を含む
- /diff-review 2 パスレビュー（忖度対策）: Pass 1 は plan・背景情報を渡さない blind 分析、Pass 2 で背景と照合して `plan_note` を追記する。Pass 1 指摘の削除・弱体化は禁止（「plan に則っている」を微妙な実装を通す理由にさせない）
- diff-analyzer の findings を構造化: `title` / `location`（hunk id 含む）/ `suggestion` / `plan_note` を追加（旧 `text` のみの形式とも後方互換）。周辺コードを読んでも意図がつかめない変更は「意図不明・要改善」の warn として明示的に立てるルールを追加

## [1.2.0] - 2026-07-24

### Added

- /diff-review スキル: 未コミット差分（`--staged` / `--base <ref>` も可）から「解説つきレビュー画面」を自己完結 HTML として生成する。差分を hunk 単位に機械分割し、diff-analyzer が意味単位の変更グループ（意図・タグ・リスク・指摘）に分類、承認チェックリスト（localStorage 永続・進捗バー付き）として表示する。閲覧 + 承認チェックのみで git の状態は変えない
- diff-analyzer エージェント（sonnet / read-only）: 分割済み diff の全 hunk を重複なく変更グループへ分類した JSON を返す。被覆（漏れ・重複・未知 id）はビルドスクリプトが機械検証し、LLM は分類だけ・HTML 生成は決定的スクリプトが担う分担
- `--fable` オプション: ユーザー許可（フラグ・会話での明示許可・重量級タスクでの 1 回だけの昇格提案への承認）がある場合に designer を Fable モデルで起動する。無許可の Fable 使用は禁止、選択モデルと経緯は完了報告の「AI が下した判断」に記録。対象は designer のみ、起動失敗時は既定モデルへフォールバック

## [1.1.0] - 2026-07-24

### Added

- auditor エージェント（opus / read-only）: designer の brief をフレッシュコンテキストで意味的に監査する独立監査層。full レーンの Step 3 で既定実行し、`--no-audit` で省略できる。6 観点（接合面・バグの芽・規約準拠・要件充足・設計の甘さ・mini-ADR の妥当性）+ 信頼度付き指摘。high 指摘は反映か明示的棄却の二択
- consultant エージェント（opus / read-only / on-demand）: 覆し判断の独立第二意見。designer 提案の覆し・auditor high 指摘の棄却・軽微/重大の境界迷いの 3 トリガーで必須諮問。助言棄却には一次資料引用付きの二段目明文化を要求（非対称プロトコル二段目）
- 自律モードの例外エスカレーション: 保守的仮定で埋めきれない未決事項（Step 1 / Step 4）は、推測せず AskUserQuestion でその 1 点だけを人間に確定してもらう。頻発時は `--gated` での仕切り直しを提案

### Changed

- 差し戻し規律を明文化: designer への差し戻しは違反箇所の指摘に限定し、修正案の詳細を書かない（マイクロマネジメントによる責務分離の崩壊防止）
- 中央検証の成果物を designer にレビューさせない禁止を明記（自己弁護バイアス対策）
- auditor の「注意事項（予測）」は修正指示として扱わず、予測だけを根拠に確定済み設計を書き換えない規定を追加
- 完了報告の「AI が下した判断」に auditor 指摘の採否と consultant 諮問の記録を追加

## [1.0.0] - 2026-07-17

### Added

- 設計ファーストのインナーループ（full レーン 7 ステップ: 要件正規化 → designer 設計 → 監査 3 層 → implementer 実装 → reviewer-light ループ → 完了報告）
- light レーン: 軽量タスク向け 5 ステップ経路（designer 省略・reviewer 1 巡）
- レーン自動判定（方針一意・アンカー自明・変更が小さいの 3 条件）と `--full` / `--light` 強制指定
- 自律モード（既定）と `--gated` モード（要件確定・設計確定で人間ゲート）
- designer エージェント（opus / read-only・出力契約 5 要素）
- implementer エージェント（sonnet・逐語適用・アンカー不一致スキップ報告）
- reviewer-light エージェント（sonnet / read-only・7 観点・観点外リスト）
- テンプレート群（要件書 8 項目・出力契約・mini-ADR）
- 不変ゲート（commit / push 禁止・破壊的操作の人間確認）
- 監査 3 層（トレーサビリティ機械照合・ADR スポットチェック・予測乖離検査）
- 覆し明文化プロトコル（designer 提案・レビュー指摘の却下に理由と代替案を必須化）

[Unreleased]: https://github.com/kaionn/draftsmith/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/kaionn/draftsmith/compare/v2.1.0...v3.0.0
[2.1.0]: https://github.com/kaionn/draftsmith/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/kaionn/draftsmith/compare/v1.15.0...v2.0.0
[1.15.0]: https://github.com/kaionn/draftsmith/compare/v1.14.0...v1.15.0
[1.14.0]: https://github.com/kaionn/draftsmith/compare/v1.13.1...v1.14.0
[1.13.1]: https://github.com/kaionn/draftsmith/compare/v1.13.0...v1.13.1
[1.13.0]: https://github.com/kaionn/draftsmith/compare/v1.12.0...v1.13.0
[1.12.0]: https://github.com/kaionn/draftsmith/compare/v1.11.0...v1.12.0
[1.11.0]: https://github.com/kaionn/draftsmith/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/kaionn/draftsmith/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/kaionn/draftsmith/compare/v1.8.1...v1.9.0
[1.8.1]: https://github.com/kaionn/draftsmith/compare/v1.8.0...v1.8.1
[1.8.0]: https://github.com/kaionn/draftsmith/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/kaionn/draftsmith/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/kaionn/draftsmith/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/kaionn/draftsmith/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/kaionn/draftsmith/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/kaionn/draftsmith/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/kaionn/draftsmith/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/kaionn/draftsmith/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kaionn/draftsmith/releases/tag/v1.0.0
