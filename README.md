# draftsmith

Design-first task lifecycle for Claude Code — 設計ファーストのinner loopを、必要に応じてPR reviewまで延長するプラグイン。

One task in, reviewed change out by default; opt in to delivery through reviewed PR:
**requirements → design → audit → implementation → light review → PR → review → final verification**.

```mermaid
flowchart LR
    R[Requirements<br/>要件正規化] --> D[designer<br/>opus / read-only<br/>reads constitution.md]
    D --> AU[auditor<br/>独立監査 / read-only]
    D --> A{Audit<br/>形式 3 層 + 指摘統合}
    AU --> A
    A -- 差し戻し<br/>record to pain ledger --> D
    A --> G[gated: render brief<br/>as HTML, open & confirm]
    G --> I[implementer<br/>sonnet / verbatim]
    I --> V[Central verification<br/>format / lint / test]
    V --> L{reviewer-light<br/>checks rubric}
    L -- 指摘あり --> I
    L -- 指摘なし --> F{Goal}
    F -- implemented --> STOP[Report<br/>従来どおり停止]
    F -- later goal --> C[Commit gate<br/>plan-commit]
    C --> P[Draft PR]
    P --> R{CI / bot / human review}
    R -- implementation finding --> I
    R -- design finding --> D
    R -- review complete --> FV[Final verification]
    FV --> MR[Merge-ready<br/>no merge]
```

---

## English

### Why design-first

Letting one agent both design and implement invites two failure modes: design decisions
made implicitly mid-edit, and reviews that rubber-stamp whatever got written. draftsmith
splits the loop into three roles with **structurally enforced boundaries**:

- **designer** (opus, high effort) — investigates the codebase and returns a first design.
  It has **no Edit/Write tools**, so it cannot "just fix it real quick". Its output follows a
  5-part reply contract: verbatim brief / open questions with proposed defaults /
  broken-assumption report / traceability table / mini-ADRs for significant decisions only.
- **main session** — the orderer and auditor. Before dispatch it writes a 2–3 line
  *falsifiable prediction* of what the design should look like; the audit then checks
  (1) traceability against every acceptance criterion, (2) that ADRs actually cite the
  requirements, (3) divergence between prediction and result — a cheap tripwire against
  rubber-stamp auditing. Overruling the designer requires a written reason and alternative.
  Every rejection is recorded to a per-category **pain ledger**; once a category hits 3
  rejections it auto-promotes into `constitution.md`, which designer reads on every future
  run — recurring audit friction becomes a standing constraint instead of repeating itself.
- **auditor** (opus, read-only) — a fresh-context semantic audit of the designer's brief,
  run in the full lane by default (`--no-audit` to skip). The main session's 3-layer audit
  is formal; the auditor checks *meaning* across six lenses (seams, bug seeds, conventions,
  requirement coverage, vague instructions, ADR validity) — and, being independent of the
  ordering context, it counters the structural conflict of interest of an orderer grading
  its own order. High-confidence findings must be applied or explicitly overruled.
- **consultant** (opus, read-only, on-demand) — a second-opinion agent the main session
  must consult *before* overruling a designer proposal or rejecting a high-confidence
  auditor finding. Rejecting the consultant's advice too requires a second written
  justification citing primary sources — a double hurdle against self-serving dismissals.
- **implementer** (sonnet) — applies the brief verbatim. No design decisions. If an anchor
  in the brief doesn't match the file, it skips and reports instead of guessing.
- **reviewer-light** (sonnet, read-only) — loops until "no findings" across seven generic
  lenses (correctness, edge cases, semantic redundancy, readability, types, project
  conventions, tests), with an explicit out-of-scope list so it doesn't fight your linter.
  When a **rubric** was written up front (criterion / verification method / expected
  result per acceptance criterion), it checks that first — measured, not the implementer's
  self-report — before the seven lenses.

### Install

```
/plugin marketplace add kaionn/draftsmith
/plugin install draftsmith@draftsmith
```

### Usage

```
/draftsmith <your requirement in natural language>
/draftsmith --gated <requirement>
/draftsmith --light <requirement>   # force the light lane
/draftsmith --full <requirement>    # force the full lane
/draftsmith --no-audit <requirement> # skip the independent design audit
/draftsmith --fable <requirement>    # run the designer on the Fable model
/draftsmith --through-review <requirement> # continue through human PR review
/draftsmith --from=delivery --goal=merge_ready <PR> # start at an existing branch/PR
```

The default goal remains `implemented`, preserving the existing behavior. Delivery is opt-in with
`--through-review`, a later `--goal`, or `--from=delivery`. Goals are `implemented`, `pr_open`,
`review_requested`, `review_complete`, and `merge_ready`; merge itself is never implied.

PR feedback is classified before action. Implementation findings return to a targeted implementer
and reviewer-light pass; design or requirement findings return to designer and auditor; questions,
replies, resolves, and ambiguous decisions stop at a human gate. Delivery state is stored under Git
metadata so CI and review waits can resume in a later run without dirtying the working tree. A
cross-process lock plus optimistic `revision` check rejects concurrent stale updates.

```
/diff-review                 # annotated review screen for uncommitted changes
/diff-review --staged        # staged changes only
/diff-review --base main     # whole-branch diff against a ref
```

`/diff-review` generates a self-contained HTML review screen from a diff: hunks are
split mechanically, a read-only **diff-analyzer** agent groups them into semantic
change groups (intent, tags, risk label, findings), and a deterministic build script
renders them with per-group approval checkboxes (persisted in localStorage) and a
progress bar. Hunk coverage (no missing / duplicated hunks) is machine-verified.
It never touches git state.

Analysis runs in **two passes** to counter sycophancy: pass 1 is blind (no plan or
background is given — the diff must stand on its own), pass 2 reconciles against the
plan, only annotating findings with plan context — never deleting or softening them.
Each finding carries adopt / reject buttons and comment fields; a **feedback builder**
section assembles the adopted findings plus your comments into a markdown block you
copy straight back into the working session.

```
/plan-commit                 # fold the plan file into a commit, then delete it
```

Once the design is confirmed, `/draftsmith` writes it to `plans/{task-slug}.md` — an
**ephemeral plan file** (skip with `--no-plan-file`). It is not a task ledger: it lives
for one task, feeds `/diff-review`'s pass-2 reconciliation automatically, and is finally
folded into the commit itself by `/plan-commit` — one-line subject plus the plan as the
commit body, previewed and human-approved — which then deletes the file. Design intent
ends up in git history instead of a stale document.

```
/verify-report               # E2E verification report with screenshot evidence
```

`/verify-report` closes the loop for UI-touching changes: the main session drives the
browser and captures screenshots per acceptance criterion (sourced from the plan file),
then an **evidence-reviewer** agent — which never sees the implementation diff — judges
each criterion from the screenshots alone: pass / fail / needs-human, with the burden of
proof on the evidence (no screenshot, no pass). The output is a single self-contained
HTML report: criteria × embedded screenshots × verdicts, plus a copy-paste summary for
the PR description. Full verdict coverage is machine-verified by the build script.

- **Autonomous mode (default)**: no human gates between requirement and "no findings".
  Open questions are settled with conservative assumptions (preserve behavior, minimize
  scope) and every such decision is listed in a "Decisions made by AI" section of the
  final report. One escape hatch: an open question that conservative assumptions
  genuinely cannot settle triggers a single targeted human question instead of a guess —
  and if that keeps happening, draftsmith suggests rerunning with `--gated`.
- **`--gated`**: adds two human checkpoints — requirement sign-off and design sign-off.
  For the design checkpoint, the designer's 5-part reply is rendered as a self-contained
  HTML page (`/tmp/draftsmith-brief-{task-slug}.html`) and opened in a browser before the
  confirmation prompt, so you review a formatted brief instead of raw markdown in chat.
- **`--fable`**: runs the designer on Fable (the tier above Opus) for this task. Fable is
  never used without explicit user permission — the flag, a go-ahead in conversation, or
  a one-time upgrade proposal draftsmith may make on clearly heavyweight tasks. The chosen
  model is recorded in the final report. Designer only; other agents keep their defaults.
- **Invariant gates (all goals)**: destructive operations and every external mutation remain
  human-gated. In delivery mode, commit, push, PR writes, review replies/resolves, review requests,
  ready, and merge are separate gates; the default `implemented` goal never commits or pushes.

### Lanes: full vs light

At entry, draftsmith classifies the task and picks one of two lanes (overridable with
`--full` / `--light`):

- **full** — the 7-step flow above. Default whenever any design judgement is involved.
- **light** — for tasks where the approach is unambiguous, the anchors are obvious from
  the requirement (no investigation needed), and the change is small (~1–3 files, no
  structural change). Skips designer (and hence the independent audit): the main session
  writes the verbatim brief itself,
  implementer applies it under the same no-guessing discipline, and reviewer-light runs
  a **single pass** instead of looping. If mid-lane evidence shows the task was heavier
  than judged (anchors need investigation, structural mismatch, design-level review
  findings), it escalates one-way to full and restarts.

When in doubt the classifier falls back to full; the chosen lane and its reasoning are
always listed in the final report.

### Scope: what draftsmith deliberately does NOT own

- **No task ledger** — it processes exactly one task per invocation
- **No implicit delivery** — the default `implemented` goal stops at a verified working-tree change
- **No automatic merge or release** — later goals can prepare and review one PR, but every external
  mutation is gated and merge/release remain outside the goal
- **No multi-task orchestration** — task ledgers and batches belong elsewhere

### Using alongside claude-code-harness

draftsmith is designed to slot into the gap left by
[claude-code-harness](https://github.com/Chachamaru127/claude-code-harness): harness owns
the outer loop (Plans.md ledger, work orchestration, review verdicts, memory), draftsmith
owns the inner loop of a single task. A working combination:

1. `harness-plan` — build the task ledger (Plans.md)
2. `/draftsmith <one task line from Plans.md>` — design-first execution of that task
3. Review the reported diff, commit it yourself
4. `harness-sync` — update the ledger markers

The two plugins stay loosely coupled: draftsmith reads a task *description*, never
harness's internal state.

With `/draftsmith-next --through-review`, the adapter propagates the later goal: draftsmith handles
the commit/PR/review lifecycle behind its human gates, and `harness-sync` runs only after a commit
actually exists. `--from=delivery` is intentionally rejected by draftsmith-next because a new
Plans.md task is a requirements entry; invoke draftsmith directly for an existing branch or PR.

### Example run

Real cycle against [signal-lab](https://github.com/kaionn/signal-lab) (a Next.js app),
task: *"make the weekly-digest loader survive missing / unparseable `meta.yaml` files"*:

- **designer** investigated the actual loader, returned a verbatim brief with a
  traceability table covering all 3 acceptance criteria, plus 2 open questions —
  each with a proposed default (e.g. "warn on null-parsing meta instead of silently
  skipping, because the requirement's goal is *noticing* breakage")
- **audit** passed: every AC mapped, decisions cited the requirement, result matched
  the pre-dispatch prediction (single-file change, no new files besides fixtures)
- **implementer** applied the brief; **reviewer-light** returned "no findings" in round 1
- the final report listed 2 decisions made autonomously, and surfaced a genuine
  out-of-scope discovery: a sibling loader (`lib/experiments.ts`) shares the same
  fragility — reported as a follow-up instead of silently fixed (scope guard working
  as intended). No commit, no push; the diff was left for the human.

### Related work

[BMAD-METHOD](https://github.com/bmadcode/BMAD-METHOD) ·
[GitHub Spec Kit](https://github.com/github/spec-kit) ·
[Superpowers](https://github.com/obra/superpowers) ·
Aider architect mode — draftsmith's niche is the tool-permission-enforced
designer/implementer split plus an auditable reply contract, at single-task granularity.

---

## 日本語

### なぜ設計ファーストか

1 つのエージェントに設計と実装を同時にやらせると、編集の手元で暗黙の設計判断が起き、
レビューは書かれたものの追認になりがち。draftsmith はループを 3 役に分割し、境界を
**ツール権限で構造的に**強制する。

- **designer**（opus / high）— コードベースを調査して一次設計を返す。**Edit/Write を
  持たない**ので「ちょっと直しておく」が物理的にできない。return は出力契約 5 要素
  （逐語 brief / 提案デフォルト付き確認事項 / 前提崩れ報告 / トレーサビリティ表 /
  重要判断のみの mini-ADR）に従う
- **main セッション** — 発注者兼監査者。dispatch 前に「反証可能な予測」を 2〜3 行書き、
  監査では (1) 全受け入れ基準とのトレーサビリティ照合 (2) ADR の要件引用チェック
  (3) 予測と成果物の乖離検査、の 3 層を回す。第 3 層は監査のゴム印化を検知する安価な
  仕掛け。designer の提案を覆すときは理由 + 代替案の明文化が必須。却下はカテゴリ別に
  **pain 台帳**へ記録され、同一カテゴリが 3 回溜まると `constitution.md` へ自動昇格する。
  designer は毎回の起動時にこれを読むので、繰り返す監査摩擦がその場限りで消えず
  恒常的な制約として定着する
- **auditor**（opus / read-only）— designer の brief をフレッシュコンテキストで意味的に
  監査する独立監査層。full レーンで既定実行（`--no-audit` で省略可）。main の 3 層は
  形式の検査なので、意味の検査（接合面・バグの芽・規約準拠・要件充足の中身・設計の
  甘さ・mini-ADR の妥当性の 6 観点）を発注の経緯から独立した立場で担う。発注者が
  自分の発注物を評価する構造的な利益相反への対策でもある。high 信頼度の指摘は
  反映か明示的な棄却かの二択で、黙殺できない
- **consultant**（opus / read-only / on-demand）— designer 提案の覆しと auditor の
  high 指摘の棄却の直前に、main が必ず諮問する独立第二意見。consultant の助言まで
  棄却するには一次資料の引用付きで二段目の明文化が要る。独断棄却への二重のハードル
- **implementer**（sonnet）— brief を逐語適用する。設計判断はしない。brief のアンカーが
  実ファイルと一致しなければ、推測で埋めずスキップ報告する
- **reviewer-light**（sonnet / read-only）— 7 つの汎用観点（正確性・エッジケース・
  意味的冗長性・可読性・型・プロジェクト規約・テスト）で「指摘なし」までループする。
  観点外リストを明示していて、linter の仕事は奪わない。事前に **rubric**（受け入れ基準
  ごとの criterion / 検証方法 / 期待結果）が書かれていれば、7 観点より先にそれを
  自分で実測して照合する（実装者の自己申告ではなく rubric が正）

### インストール

```
/plugin marketplace add kaionn/draftsmith
/plugin install draftsmith@draftsmith
```

### 使い方

```
/draftsmith <要件を自然言語で>
/draftsmith --gated <要件>
/draftsmith --light <要件>    # light レーンを強制
/draftsmith --full <要件>     # full レーンを強制
/draftsmith --no-audit <要件> # auditor 独立監査を省略
/draftsmith --fable <要件>    # designer を Fable モデルで起動
/draftsmith --through-review <要件> # human PR review完了まで続行
/draftsmith --from=delivery --goal=merge_ready <PR> # 既存branch/PRから開始
```

既定goalは従来どおり`implemented`。deliveryは`--through-review`、後段`--goal`、または
`--from=delivery`で明示した場合だけ有効になる。goalは`implemented` / `pr_open` /
`review_requested` / `review_complete` / `merge_ready`。merge自体はどのgoalにも含まれない。

PR feedbackは実行前に分類する。実装指摘はtargeted implementer + reviewer-lightへ、
設計・要件指摘はdesigner + auditorへ戻す。質問、reply、resolve、曖昧な判断はhuman gateで
停止する。delivery stateはGit metadata配下に保存され、working treeを汚さずCI/review待ちを
別runから再開できる。cross-process lockとoptimistic `revision`照合により、Claude/Codexの
古いstate更新を拒否する。

```
/diff-review                 # 未コミット差分の解説つきレビュー画面
/diff-review --staged        # ステージ済みのみ
/diff-review --base main     # 指定 ref とのブランチ差分
```

`/diff-review` は差分から自己完結 HTML のレビュー画面を生成する。hunk 分割は機械的に、
意味づけは読み取り専用の **diff-analyzer** agent が変更グループ（意図・タグ・リスク・
指摘）として行い、決定的なビルドスクリプトが承認チェックボックス（localStorage 永続）と
進捗バー付きで描画する。hunk の被覆（漏れ・重複）は機械検証される。
git の状態には一切触れない。

分析は忖度対策の **2 パス制**: Pass 1 は plan・背景を渡さない blind 分析（差分単体で
妥当かだけを見る）、Pass 2 で plan と照合して備考を追記する — 指摘の削除・弱体化は
禁止。各指摘には採用 / 却下ボタンとコメント欄が付き、**フィードバック組み立て**
セクションが採用された指摘 + コメントを markdown に整形、クリップボードにコピーして
元の作業セッションへそのまま貼り戻せる。

```
/plan-commit                 # plan ファイルをコミットに畳み込んで削除
```

`/draftsmith` は設計確定後に `plans/{task-slug}.md` へ**一時 plan ファイル**を書き出す
（`--no-plan-file` で省略可）。これはタスク台帳ではない: 1 タスク分だけ生きて、
`/diff-review` の Pass 2 照合に自動で使われ、最後は `/plan-commit` がコミットへ
畳み込む — subject 一行 + body に plan 本文、プレビューを人間が承認してからコミットし、
plan ファイルを削除する。設計意図は陳腐化するドキュメントではなく git 履歴に残る。

```
/verify-report               # 証跡スクショ付き E2E 検証レポート
```

`/verify-report` は画面に触れる変更のループを閉じる: main がブラウザを操作して
受け入れ基準（plan ファイル由来）ごとに証跡スクショを収集し、**実装 diff を一切
見ていない evidence-reviewer** agent がスクショだけを目視して pass / fail /
要人間確認を判定する — 立証責任は証跡側にあり、スクショが無い AC は pass に
ならない。出力は AC × 埋め込みスクショ × 判定の自己完結 HTML レポートで、
PR description への転記用サマリー（コピーボタン付き）を含む。全 AC の判定被覆は
ビルドスクリプトが機械検証する。

- **自律モード（既定）**: 要件入力から「指摘なし」まで人間ゲートなしで自走する。
  未決事項は保守的仮定（既存挙動維持・スコープ最小）で確定し、下した判断はすべて
  完了報告の「AI が下した判断」節に一覧で出る。逃げ道を一つだけ持つ:
  保守的仮定で埋めきれない未決事項に限り、推測せずその 1 点だけを人間に確認する。
  これが頻発するタスクには `--gated` での仕切り直しを提案する
- **`--gated`**: 要件確定・設計確定の 2 ゲートが人間確認になる。設計確定ゲートでは
  designer の出力契約 5 要素を自己完結 HTML（`/tmp/draftsmith-brief-{task-slug}.html`）
  として描画し、確認プロンプトの前にブラウザで開く。チャット上の生 markdown ではなく
  整形された brief をレビューできる
- **`--fable`**: designer を Fable（Opus 上位ティア）で起動する。Fable の使用には必ず
  ユーザー許可が要る — フラグ指定・会話での明示許可・重量級タスクでの 1 回だけの
  昇格提案への承認のいずれか。選択モデルは完了報告に記録される。対象は designer のみ
- **不変ゲート（全goal共通）**: 破壊的操作と外部変更は常に人間確認。delivery modeでも
  commit、push、PR書き込み、review reply/resolve、review依頼、ready、mergeは別々のgate。
  既定の`implemented` goalはcommit / pushを行わない

### レーン: full と light

入口でタスクの軽重を判定し、2 レーンのどちらかを自動選択する（`--full` / `--light` で
強制指定も可能）:

- **full** — 上記の 7 ステップフロー。設計判断が少しでも絡むならこちら
- **light** — 方針が一意・アンカーが要件から自明（調査不要）・変更が小さい
  （目安 1〜3 ファイル・構造変更なし）タスク向け。designer（と、それを見る auditor 独立監査）を
  省略して main が逐語 brief を直接書き、implementer は同じ「推測しない」規律で適用、reviewer-light はループせず
  **1 巡のみ**。実行中に判定より重いと分かったら（アンカーに調査が必要・構造的な
  食い違い・設計に踏み込むレビュー指摘）、full へ一方向に昇格してやり直す

迷ったら full に倒す保守的判定で、選んだレーンと理由は完了報告に必ず記録される。

### draftsmith が意図的に持たないもの

- **タスク台帳を持たない** — 1 回の起動で 1 タスクだけ処理する
- **暗黙にdeliveryへ進まない** — 既定の`implemented` goalは検証済みのワーキングツリー変更で止まる
- **自動merge・releaseをしない** — 後段goalは単一PRのreviewまで。外部変更は個別gate
- **複数タスクを一括処理しない** — 台帳・batch orchestrationは他に任せる

### 構成

```
.claude-plugin/plugin.json      # プラグイン manifest
.claude-plugin/marketplace.json # self-marketplace（単一リポで配布）
agents/designer.md              # 一次設計（読み取り専用・constitution.md 読込）
agents/auditor.md               # 独立設計監査（読み取り専用・full レーン既定）
agents/consultant.md            # 覆し判断の独立第二意見（読み取り専用・on-demand）
agents/implementer.md           # 逐語適用（設計判断なし）
agents/reviewer-light.md        # 軽量レビュー（定型出力・rubric 照合）
scripts/audit-ledger.sh         # 監査 pain 台帳（record / promote-check）
agents/diff-analyzer.md         # 差分の意味グルーピング（読み取り専用）
agents/evidence-reviewer.md     # 証跡スクショの独立判定（読み取り専用・vision）
skills/draftsmith/SKILL.md      # メインフロー（7 ステップ）
skills/draftsmith/templates/    # 要件書・出力契約・mini-ADR・plan ファイル・rubric・brief-visual
skills/draftsmith/references/   # opt-in delivery / PR review lifecycle
skills/draftsmith/scripts/      # delivery state helper
skills/diff-review/SKILL.md     # 解説つき差分レビュー画面（/diff-review）
skills/diff-review/scripts/     # diff 分割・HTML ビルド（Python stdlib のみ）
skills/diff-review/templates/   # レビュー画面テンプレート
skills/plan-commit/SKILL.md     # plan ファイルの畳み込みコミット（/plan-commit）
skills/verify-report/SKILL.md   # 証跡スクショ付き E2E 検証レポート（/verify-report）
skills/verify-report/scripts/   # レポートビルド（Python stdlib のみ）
skills/verify-report/templates/ # レポートテンプレート
skills/adapters/                # タスク供給元ごとの橋渡し層
skills/adapters/draftsmith-next/SKILL.md # harness の Plans.md から 1 タスクを draftsmith へ橋渡し（/draftsmith-next）
tests/test_delivery_state.py    # delivery stateのphase・worktree・schema回帰テスト
```

## License

MIT
