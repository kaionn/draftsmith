---
name: diff-review
description: 未コミット差分（またはブランチ差分）から「解説つきレビュー画面」を生成する。差分を hunk 単位に機械分割し、diff-analyzer が意味単位の変更グループ（意図・タグ・リスク・指摘）に分類、自己完結 HTML として承認チェックリスト付きのレビュー画面を出力する。「差分レビュー画面」「diff review 画面を作って」「レビュー画面で確認したい」「/diff-review」で発火。--staged でステージ済みのみ、--base <ref> で指定 ref との差分を対象にする。
user-invocable: true
---

# /diff-review — 解説つき差分レビュー画面の生成

あなた（メインセッション）はオーケストレーター。差分の分割と HTML 生成は決定的な
スクリプトに、意味の分析は diff-analyzer agent に委ね、あなたは入力の確定・
出力の検証・提示だけを行う。

## スコープ

- 生成するのは**閲覧 + 承認チェックのみ**のレビュー画面。承認チェックの状態は
  ブラウザの localStorage に残るだけで、git には一切影響しない
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

## Step 2: diff-analyzer 起動

diff-analyzer agent を**同期**（`run_in_background: false`）で起動する。渡すもの:

- `hunks.json` の絶対パス
- 背景情報: この差分が何のための変更か、あなたが知っていれば 1〜3 行で
  （plan ファイル・直前のタスク・ユーザーの説明など。知らなければ「不明」と書く）
- 出力契約は agent 定義に記載済み。「hunks.json を Read してから分類せよ」とだけ明記する

return の JSON を `<workdir>/groups.json` に保存する（コードフェンスは剥がす）。

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
   - ビルド時の警告（あれば）
3. **ここで止まる**。承認チェックは人間の作業であり、チェック結果を読み取って
   何かを実行する機能はない（承認 = ステージ等の git 連携は意図的にスコープ外）

## トラブル時の原則

- diff が巨大（目安: hunks 500 超）なら、分析前に「--base や対象パスで絞るか、
  このまま進めるか」をユーザーに確認する（分析の質が落ちるため）
- diff-analyzer への差し戻しが同一論点で 2 往復を超えたら、自走をやめて
  ユーザーに状況と選択肢を提示する
