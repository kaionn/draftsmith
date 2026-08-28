---
name: verify-report
description: 実装後の E2E 検証を証跡スクリーンショット付きレポートにする。plan ファイル（または指定シナリオ）の受け入れ基準ごとに main がブラウザ操作でスクショを収集し、実装を知らない evidence-reviewer が fresh context でスクショだけを見て pass / fail / needs_human を判定、自己完結 HTML レポート（スクショ埋め込み + PR 転記用サマリー）を出力する。「E2E レポート」「検証レポート」「証跡スクショ付きで確認」「/verify-report」で発火。画面に触れない変更（CLI・ライブラリ等）は対象外。
user-invocable: true
---

# /verify-report — 証跡スクショ付き E2E 検証レポート

あなた（メインセッション）はシナリオ設計と証跡収集を担い、**判定はしない**。
判定は実装を知らない evidence-reviewer に委ね、あなたは入力の確定・レポートの
組み立て・提示だけを行う（実装した側が自分で動作確認して OK と言う自己追認を
壊すための分担）。

## スコープ

- 扱うのは「実装済みの変更に対する、画面ベースの受け入れ検証」だけ
- **git の状態を変えない**。アプリやデータへの書き込み操作がシナリオに必要な場合
  （フォーム送信・削除など）は、実行前にその操作をユーザーに確認する
- 画面に触れない変更（CLI・ライブラリ・純リファクタ）は対象外。その場合は
  「/verify-report の対象外（画面証跡が定義できない）」と報告して終了する
- レポートはローカルファイル。スクショに実データが写り得るため、**外部への共有・
  公開はユーザーの判断**（PR に貼るのは転記用サマリーのテキストに留める）

## パス・作業ファイル

スクリプトとテンプレートは `$SKILL_DIR`（プラグイン導入時
`${CLAUDE_PLUGIN_ROOT}/skills/verify-report/`、リポジトリ直用 `skills/verify-report/`）。
作業ファイル（スクショ・evidence.json・verdicts.json・report.html）はセッションの
スクラッチパッドに置く。**対象リポジトリ内に作らない**。

## Step 1: AC（受け入れ基準）の確定

優先順:

1. 引数のパス指定（plan ファイル or シナリオ記述ファイル）
2. repo ルート `plans/*.md`（/draftsmith の一時設計文書。`> ⚠ 一時設計文書` ヘッダ付き)
   から「受け入れ基準」節を抽出
3. どちらも無ければ、ユーザーに検証したい観点を聞く

AC のうち画面で検証できるものだけを対象にし、対象外の AC（内部実装・性能等）は
レポートの「対象外」欄に理由付きで残す（黙って落とさない）。

## Step 2: シナリオ具体化と環境確認

- AC ごとに「URL / 操作列 / 撮影ポイント / 期待して見えるはずのもの」を書き出す
- 対象アプリの稼働を確認する（HTTP 応答等）。起動していなければ、リポジトリ既定の
  起動手段（mise / Makefile / package.json scripts）を提示してユーザーに確認する。
  環境が整わない場合は**正直に「E2E 未実施」で終了**し、静的検証で代替しない

## Step 3: 証跡収集（main が実行）

利用可能なブラウザ自動化手段（Claude in Chrome / agent-browser / Playwright 等、
環境にあるもの）でシナリオを実行し、撮影ポイントごとにスクショを保存する:

- ファイル名は `s01.png`, `s02.png`, … の連番
- `evidence.json` を組み立てる:

```json
{
  "title": "レポートタイトル（タスク名）",
  "source": "AC の出所（plans/xxx.md 等）",
  "acs": [
    { "id": "AC-1", "text": "AC の本文" }
  ],
  "excluded_acs": [
    { "id": "AC-3", "text": "本文", "reason": "画面で検証できない（内部実装）" }
  ],
  "screenshots": [
    { "id": "s01", "file": "s01.png", "caption": "何をした直後のどの画面か" }
  ]
}
```

- caption は「撮影時の操作文脈」を事実だけで書く。**「正しく表示されている」等の
  評価を書かない**（評価は evidence-reviewer の仕事。caption に評価を混ぜると
  判定を誘導してしまう）
- 「従来から変わらない」「壊れていない」系の AC（レイアウト不変・回帰なし等）には、
  可能なら**実装前の同一画面のスクショ**も証跡に含める。対象worktreeのindex、working tree、
  stash一覧は変更しない。`pr-verify-report`が利用可能なら、その専用worktreeでbeforeを取得する
  規範を再利用する。未導入なら別の専用worktreeを作る許可と安全な配置を確認する。
  before が用意できない場合はその AC が needs_human に
  なるのを正しい出力として受け入れる（証跡なしで pass にさせない）
- 破壊的・不可逆な操作が必要になったら、その場でユーザーに確認する（不変ゲート）

## Step 4: evidence-reviewer 起動（判定の独立）

evidence-reviewer agent を**同期**で起動する。渡すもの:

- `evidence.json` の絶対パス
- 「スクショは file を Read で開いて実際に目視せよ」の明記

**渡してはいけないもの**: 実装 diff・brief・設計文書・「ここは動いているはず」の類の
あなたの見解。AC とスクショだけで判定させる。

return の JSON を `<workdir>/verdicts.json` に保存する（コードフェンスは剥がす）。

## Step 5: レポート生成と検証

```bash
python3 "$SKILL_DIR/scripts/build_report.py" build \
  --evidence <workdir>/evidence.json --verdicts <workdir>/verdicts.json \
  --shots-dir <workdir> --template "$SKILL_DIR/templates/report.html" \
  --out <workdir>/report.html
```

スクリプトは被覆を機械検証する（全 AC に判定が 1 つずつ・未知の AC / スクショ id は
エラー・スクショ実ファイルの存在確認）。エラー時は verdicts.json を手で直さず、
エラー内容を添えて evidence-reviewer に SendMessage で差し戻す（2 回連続で通らなければ
ユーザーに報告）。スクショは data URI でレポートに埋め込まれ、単一 HTML で完結する。

## Step 6: 提示と報告

1. `report.html` を SendUserFile（display: render）で送る。ローカルパスも併記
2. テキストでも要約する: pass / fail / needs_human の数、fail と needs_human は
   本文転記、extra_findings（あれば）、対象外 AC、E2E を省略・断念した範囲
3. レポート内の「PR 転記用サマリー」（判定表のテキスト）は人間がコピーして使う。
   **fail があってもあなたは修正に着手しない**。修正するかは人間の判断
   （修正指示を受けたら通常フロー（/draftsmith 等）で回す）

## トラブル時の原則

- ブラウザ操作が 2〜3 回失敗する・ページが応答しない等の環境不調は、粘らずに
  「ここまでの証跡 + 未実施の範囲」でレポートを出すか中止するかをユーザーに確認する
- 撮影できなかった AC を pass 扱いにしない（証跡が無ければ evidence-reviewer が
  needs_human にする。それが正しい出力）
