# brief-visual: gated 理解確認用 HTML テンプレート

<!--
gated モードの full レーン Step 4（理解確認gate）で、main が確定要件全文とdesigner return
（出力契約5要素）を`/tmp/draftsmith-brief-{task-slug}.html`へ投影する。designer returnの
5要素は変更せず、原文根拠へ全文を残す。

「一言要約」「読む前提」「判断カード」は、gated designer returnの要素1にある
`gated-display-material`範囲から逐語転記する。mainは要約、前提、判断、理由、反実仮想、根拠を
生成・補完・順位付けしない。判断カードはdesignerが付けたD-01〜D-05をそのまま使う。
重要判断が0件の場合はカードを生成せず、`重要判断なし`を表示する。カードがある場合に必要素材が
欠けていればHTMLを生成せず、full lane Step 2へ差し戻す。

「読む前提」はMarkdown箇条書きとして解釈しない。表示素材にある箇条書き記号なしの複数行テキストを
1つのescape済み文字列として`pre`へ入れる。行ごとのwrapper生成や記号の追加は行わない。

全ソース値はHTML escapeしてから固定wrapperへ入れる。escapeは`&`、`<`、`>`、`"`、`'`の順に
`&amp;`、`&lt;`、`&gt;`、`&quot;`、`&#39;`へ置換する。ソース値をHTML断片として挿入しない。
標準ライブラリ以外のテンプレートエンジンは追加しない。

外部CDN・外部フォント・外部スクリプトへの依存は禁止（CSP-safe・自己完結）。CSSは`<style>`内へ
置く。対話はHTML内へ実装せず、人間がチャットでカードIDを指定する。理解度の採点、正解文の復唱、
カードの承認チェックは要求しない。

書き出し後は必ず`open /tmp/draftsmith-brief-{task-slug}.html`で開き、理解順序、0〜5件の判断カード、
確定要件原文、designer returnの5要素が崩れなく描画されているか目視確認する。
-->

## 入力と固定wrapper

すべての`{{ ... }}`の値を上記規則でescapeする。構造を生成するプレースホルダは
`decision_cards`だけとする。

- `decision_cards`: 要素1「判断素材 D-n」をID順に0〜5件、カードがある場合は次のwrapperで繰り返す。

```html
<article class="decision-card" id="{{ decision_id }}">
  <dl>
    <dt>判断 ID</dt><dd class="decision-id">{{ decision_id }}</dd>
    <dt>何を決めたか</dt><dd>{{ decision }}</dd>
    <dt>なぜか</dt><dd>{{ rationale }}</dd>
    <dt>別案を選ぶと何が壊れるか</dt><dd>{{ counterfactual }}</dd>
    <dt>原文根拠</dt><dd>{{ source_evidence }}</dd>
  </dl>
</article>
```

判断素材が`重要判断なし`の場合、`decision_cards`を次の固定wrapperへ置換する。

```html
<p class="empty">重要判断なし</p>
```

それ以外はすべてスケルトン内の固定wrapperへescape済みテキストを1回だけ入れる。

| プレースホルダ | 入力元 | 固定wrapper |
|---|---|---|
| `task_title` | タスク名 | `h1` |
| `repo` / `task_slug` | run情報 | `p.meta` |
| `one_sentence_summary` | 要素1「一言要約」の本文 | `section.lead` |
| `reading_prerequisites_body` | 要素1「読む前提」の箇条書き記号なし複数行本文 | `pre` |
| `structure_visual_body` | 要素1冒頭の構造ビジュアル | `pre` |
| `requirements_body` | 確定要件全文 | `pre` |
| `brief_body` | 要素1全文 | `pre` |
| `open_questions_body` | 要素2全文 | `pre` |
| `broken_assumptions_body` | 要素3全文 | `pre` |
| `traceability_body` | 要素4全文 | `pre` |
| `mini_adr_body` | 要素5全文 | `pre` |

要素5が存在しない場合だけ「要素5: mini-ADR」の`details`全体を省略する。それ以外のwrapperは
「なし」の場合も残し、escape済みの`なし`を入れる。

## 生成手順

1. 確定要件全文とdesigner returnの5要素を抽出する。
2. 要素1の`gated-display-material`範囲から一言要約、読む前提、0〜5件の判断素材を逐語抽出し、
   構造ビジュアルも要素1冒頭から抽出する。
3. 一言要約または読む前提が欠けていれば生成を止める。判断素材が`重要判断なし`なら0件として続行する。
   カードがある場合だけ、IDの重複、5件超過、必須フィールドの空欄を検査して不正なら生成を止める。
4. 全値を規定順にHTML escapeし、固定wrapperへ入れる。
5. HTMLを書き出して`open`し、目視確認する。
6. 人間へ「実装開始を承認」または、カードがある場合は「カード ID を指定して深掘り」を案内する。

## HTML スケルトン

```html
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
<title>設計 brief: {{ task_slug }}</title>
<style>
  :root {
    --border: #d0d7de;
    --surface: #f6f8fa;
    --accent: #2459c4;
    --accent-soft: #eaf0ff;
    --text-muted: #57606a;
  }
  body {
    font-family: -apple-system, "Hiragino Sans", "Yu Gothic", sans-serif;
    line-height: 1.7;
    max-width: 960px;
    margin: 2rem auto;
    padding: 0 1.5rem 4rem;
    background: #ffffff;
    color: #1f2328;
  }
  h1 {
    font-size: 1.7rem;
    border-bottom: 2px solid var(--accent);
    padding-bottom: .45rem;
  }
  h2 {
    font-size: 1.3rem;
    margin-top: 2.5rem;
  }
  section,
  details {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-top: .75rem;
    background: var(--surface);
  }
  summary {
    cursor: pointer;
    font-weight: 700;
  }
  pre {
    white-space: pre-wrap;
    word-break: break-word;
    background: #ffffff;
    padding: .8rem;
    border-radius: 6px;
    border: 1px solid var(--border);
  }
  dl {
    display: grid;
    grid-template-columns: minmax(10rem, 14rem) 1fr;
    gap: .5rem 1rem;
    margin: 0;
  }
  dt {
    font-weight: 700;
  }
  dd {
    margin: 0;
  }
  .lead {
    border-left: 5px solid var(--accent);
    background: var(--accent-soft);
    font-size: 1.12rem;
  }
  .meta,
  .empty {
    color: var(--text-muted);
  }
  .empty {
    font-style: italic;
  }
  .decision-grid {
    display: grid;
    gap: 1rem;
  }
  .decision-card {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.25rem;
    background: #ffffff;
  }
  .decision-id {
    color: var(--accent);
    font-weight: 800;
  }
  .deep-dive {
    margin-top: 1rem;
    border-top: 1px solid var(--border);
    padding-top: .8rem;
  }
  @media (max-width: 680px) {
    body {
      margin-top: 1rem;
      padding-inline: 1rem;
    }
    dl {
      grid-template-columns: 1fr;
      gap: .2rem;
    }
    dd {
      margin-bottom: .7rem;
    }
  }
</style>
</head>
<body>

<h1>設計 brief: {{ task_title }}</h1>
<p class="meta">{{ repo }} / {{ task_slug }} — gated 理解確認用</p>

<h2>1. 一言要約</h2>
<section class="lead">
{{ one_sentence_summary }}
</section>

<h2>2. 読む前提</h2>
<section>
<pre>{{ reading_prerequisites_body }}</pre>
</section>

<h2>3. 構造</h2>
<section>
<pre>{{ structure_visual_body }}</pre>
</section>

<h2>4. 判断カード</h2>
<section>
<div class="decision-grid">
{{ decision_cards }}
</div>
<p class="deep-dive">
実装へ進めてよければ「実装開始を承認」と伝える。判断カードがあり不明点があれば
「D-02 を詳しく」のようにカード ID を指定する。未解消の疑問がある間は実装へ進まない。
</p>
</section>

<h2>5. 原文根拠</h2>

<details open>
<summary>確定要件（原文）</summary>
<pre>{{ requirements_body }}</pre>
</details>

<details open>
<summary>要素 1: 実装 brief（本体）</summary>
<pre>{{ brief_body }}</pre>
</details>

<details>
<summary>要素 2: 確認事項リスト（提案デフォルト付き）</summary>
<pre>{{ open_questions_body }}</pre>
</details>

<details>
<summary>要素 3: 前提崩れ・要件矛盾の報告</summary>
<pre>{{ broken_assumptions_body }}</pre>
</details>

<details>
<summary>要素 4: トレーサビリティ表</summary>
<pre>{{ traceability_body }}</pre>
</details>

<details>
<summary>要素 5: mini-ADR</summary>
<pre>{{ mini_adr_body }}</pre>
</details>

</body>
</html>
```
