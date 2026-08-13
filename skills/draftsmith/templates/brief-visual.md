# brief-visual: designer 出力の HTML 可視化テンプレート

<!--
gated モードの full レーン Step 4（設計確定ゲート）で、main が designer の return（出力契約
5 要素）をこの HTML スケルトンへ流し込み、`/tmp/draftsmith-brief-{task-slug}.html` として
書き出す。`{{ ... }}` はプレースホルダで、main が実データに置換してから書き出す
（テンプレートエンジンは使わない。文字列置換で足りる分量）。

外部 CDN・外部フォント・外部スクリプトへの依存は禁止（CSP-safe・自己完結）。CSS はすべて
`<style>` 内にインラインで書く。要素 5（mini-ADR）は designer の return に無ければ
そのセクションごと省略する（出力契約と同じ扱い）。

書き出し後は必ず `open /tmp/draftsmith-brief-{task-slug}.html` で実際に開き、5 部構成
（mini-ADR がある場合は該当セクションも含む）が崩れなく描画されているか目視確認する
（fablize grounding。静的な HTML 生成だけで完成とみなさない）。
-->

## 使い方

1. designer の return から 5 要素を抽出する（要素 5 は該当時のみ）
2. 下記 HTML スケルトンの `{{ ... }}` を実データで置換する。プレースホルダ間の構造
   （見出し・table・code block）は変更しない。セクションが「なし」の場合も見出しごと
   残し、本文に「なし」とだけ書く（要素の欠落を隠さない）
3. `/tmp/draftsmith-brief-{task-slug}.html` に書き出し、`open` する
4. 描画を目視確認する。崩れがあれば HTML を直して再描画する

## HTML スケルトン

```html
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>設計 brief: {{ task_slug }}</title>
<style>
  :root {
    --border: #d0d0d0;
    --bg-alt: #f6f6f6;
    --accent: #2f6fed;
  }
  body {
    font-family: -apple-system, "Hiragino Sans", "Yu Gothic", sans-serif;
    line-height: 1.7;
    max-width: 960px;
    margin: 2rem auto;
    padding: 0 1.5rem;
    background: #ffffff;
    color: #1a1a1a;
  }
  h1 { font-size: 1.6rem; border-bottom: 2px solid var(--accent); padding-bottom: .4rem; }
  h2 { font-size: 1.25rem; margin-top: 2.5rem; }
  section {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.5rem;
    margin-top: .75rem;
    background: var(--bg-alt);
  }
  table { border-collapse: collapse; width: 100%; margin-top: .5rem; }
  th, td { border: 1px solid var(--border); padding: .4rem .6rem; text-align: left; vertical-align: top; }
  th { background: rgba(47, 111, 237, 0.1); }
  pre { white-space: pre-wrap; word-break: break-word; background: #fff; padding: .75rem; border-radius: 6px; border: 1px solid var(--border); }
  .default { color: var(--accent); font-weight: 600; }
  .empty { color: #888; font-style: italic; }
</style>
</head>
<body>

<h1>設計 brief: {{ task_title }}</h1>
<p class="empty">{{ repo }} / {{ task_slug }} — designer 出力（gated モード確認用）</p>

<h2>1. 実装 brief（本体）</h2>
<section>
<pre>{{ brief_body }}</pre>
</section>

<h2>2. 確認事項リスト（提案デフォルト付き）</h2>
<section>
<!-- 確認事項が無い場合は、この table ごと <p class="empty">なし</p> に置き換える -->
<table>
<thead><tr><th>項目</th><th>designer の推奨デフォルト</th><th>理由</th></tr></thead>
<tbody>
{{ open_questions_rows }}
</tbody>
</table>
</section>

<h2>3. 前提崩れ・要件矛盾の報告</h2>
<section>
<!-- 該当なしの場合は broken_assumptions_body に <p class="empty">なし</p> を入れる -->
{{ broken_assumptions_body }}
</section>

<h2>4. トレーサビリティ表</h2>
<section>
<table>
<thead><tr><th>受け入れ基準</th><th>対応する brief 要素</th></tr></thead>
<tbody>
{{ traceability_rows }}
</tbody>
</table>
</section>

<h2>5. mini-ADR</h2>
<section>
<!-- designer の return に mini-ADR が無ければ、この <h2> と <section> ごと HTML から削除する -->
{{ mini_adr_body }}
</section>

</body>
</html>
```
