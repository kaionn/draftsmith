---
name: diff-review
description: 未コミット差分（またはブランチ差分）から「解説つきレビュー画面」を生成する。差分を hunk 単位に機械分割し、diff-analyzer が 2 パス（blind 分析 → plan 照合）で意味単位の変更グループ（意図・タグ・リスク・指摘）に分類、自己完結 HTML として承認チェックとフィードバック組み立て（指摘の採用/却下 + コメント → markdown 生成・コピー）付きのレビュー画面を出力する。「差分レビュー画面」「diff review 画面を作って」「レビュー画面で確認したい」「/diff-review」で発火。--staged でステージ済みのみ、--base <ref> で指定 ref との差分を対象にする。
user-invocable: true
---

# /diff-review — 解説つき差分レビュー画面の生成

あなた（メインセッション）はオーケストレーター。差分の分割と HTML 生成は決定的な
スクリプトに、意味の分析は diff-analyzer agent に委ね、あなたは入力の確定・
出力の検証・提示だけを行う。

## スコープ

- 生成するのは**閲覧 + 承認チェック + フィードバック組み立て**のレビュー画面。
  承認・採用/却下・コメントの状態はブラウザの localStorage に残るだけで、
  git には一切影響しない。レビュー結果を作業側に戻す手段は「人間が markdown を
  コピーして貼る」のみ（画面から直接セッションへ送る機構は持たない）
- **git の状態を変えない**（add / commit / push / stash 禁止。読み取り系のみ）。
  これは /draftsmith の不変ゲートと同じ思想
- レビューの網羅性は保証しない。findings は「読んでいて気づいたこと」であり、
  体系的レビューが要るなら /draftsmith の reviewer-light の領分

## パス

スクリプトとテンプレートはこのスキルのディレクトリ配下にある。プラグイン導入時は
`${CLAUDE_PLUGIN_ROOT}/skills/diff-review/` を、リポジトリ直用なら
`skills/diff-review/` を基点にする（以下 `$SKILL_DIR` と表記）。

作業ファイル（hunks.json / groups.json）はセッションのスクラッチパッド
ディレクトリに置く。無ければ `mktemp -d` を使う。**対象リポジトリ内に
作業ファイルを作らない**。

## Step 1: 差分の取得

引数から対象を決める:

- 指定なし（既定）: `git diff HEAD` — ステージ済み + 未ステージの全変更
- `--staged`: `git diff --cached`
- `--base <ref>`: `git diff <ref>` — ブランチ全体のレビューに使う

```bash
git diff HEAD | python3 "$SKILL_DIR/scripts/build_review.py" split \
  --source "git diff HEAD" --out <workdir>/hunks.json
```

- hunk が 0 件なら「差分がない」と報告して終了する
- `git status --porcelain` で untracked ファイルを確認し、あれば「diff に含まれない
  未追跡ファイル」として最終報告に一覧する（`git add -N` はしない。git を変えないため）

## Step 2: diff-analyzer 起動（2 パス・忖度対策）

レビューは 2 パスに分ける。plan を先に渡すと「plan に則っている」ことが
微妙な実装を通す理由になってしまう（忖度）ため、**1 パス目は背景情報を
一切渡さない**。

### Pass 1: blind 分析

diff-analyzer agent を**同期**（`run_in_background: false`）で起動する。渡すもの:

- `hunks.json` の絶対パス
- 「Pass 1（blind 分析）である」ことの明示
- 出力契約は agent 定義に記載済み。「hunks.json を Read してから分類せよ」とだけ明記する

**渡してはいけないもの**: plan・要件書・タスク行・「何のための変更か」の説明。
あなたが背景を知っていても Pass 1 には書かない。

return の JSON を `<workdir>/groups.json` に保存する（コードフェンスは剥がす）。

### Pass 2: plan 照合（背景情報があるときのみ）

背景情報の探索は次の順で行う:

1. **repo ルートの `plans/*.md` を確認する**（/draftsmith が書き出す一時設計文書。
   冒頭に `> ⚠ 一時設計文書` の警告引用ブロックを持つ）。今回の差分に対応するものが
   あればそれが第一の背景情報
2. それ以外にあなたが知っている背景（要件書・/draftsmith の brief・Plans.md の
   タスク行・ユーザーの説明など）

見つかった背景を、同じ diff-analyzer に SendMessage で渡して照合させる:

- 背景情報の本文（またはファイルパス）
- 「Pass 2（plan 照合）である。指摘の削除・弱体化は禁止。`plan_note` の追記と
  新規指摘の追加のみ」と明示する

return の JSON で `<workdir>/groups.json` を**上書き**する。背景情報が本当に
何もなければ Pass 2 は省略してよい（省略した事実を最終報告に一行書く）。

## Step 3: HTML 生成と検証

```bash
python3 "$SKILL_DIR/scripts/build_review.py" build \
  --hunks <workdir>/hunks.json --groups <workdir>/groups.json \
  --template "$SKILL_DIR/templates/review.html" --out <workdir>/review.html
```

スクリプトは全 hunk の被覆（漏れ・重複・未知 id）を機械検証する:

- **未割り当て hunk がある**: 自動で「未分類」グループに収容され警告が出る。
  そのまま進めてよいが、警告内容は最終報告に含める
- **重複割り当て・未知 id**: エラーで停止する。groups.json を直さず、
  エラー内容を添えて diff-analyzer に SendMessage で差し戻し、再出力させる
  （あなたが分類 JSON を手で書き換えるのは、分析を独立させた意味を消すので禁止。
  ただし JSON 構文の機械的な破損の修復だけは直してよい）
- 差し戻しても 2 回連続で検証を通らなければ、自走をやめて状況をユーザーに報告する

## Step 4: 提示と報告

1. `review.html` を SendUserFile（display: render）でユーザーに送る。
   ローカルパスも併記する（ブラウザで直接開けるように）
2. テキストでも要約を出す:
   - 全体: files / hunks / +add −del
   - グループ一覧表: タイトル / リスク / hunk 数 / 指摘数
   - findings（warn のみ本文転記。info は件数と場所だけ）
   - untracked ファイルの一覧（あれば）
   - ビルド時の警告（あれば）・Pass 2 を省略した場合はその旨
3. レビュー画面のフィードバック導線を一行案内する: 画面上で各指摘に
   採用 / 却下を付けてコメントを書き、「フィードバックを生成」→
   「クリップボードにコピー」した markdown をこのセッション（または元の
   作業セッション)にそのまま貼れば対応に入れる、と伝える
4. **ここで止まる**。承認チェックとフィードバック組み立ては人間の作業であり、
   チェック結果を読み取って何かを実行する機能はない（承認 = ステージ等の
   git 連携は意図的にスコープ外）

## フィードバック markdown を受け取ったら

ユーザーが「# レビューフィードバック」で始まる markdown を貼ってきたら、
それはこのレビュー画面からの返送である。冒頭の依頼文（忖度なしの精査・
実装前の方針確認）に従って対応する。指摘に安易に同意せず、妥当でないと
判断した指摘はその根拠を返す。

## トラブル時の原則

- diff が巨大（目安: hunks 500 超）なら、分析前に「--base や対象パスで絞るか、
  このまま進めるか」をユーザーに確認する（分析の質が落ちるため）
- diff-analyzer への差し戻しが同一論点で 2 往復を超えたら、自走をやめて
  ユーザーに状況と選択肢を提示する
