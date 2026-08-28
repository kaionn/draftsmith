from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "draftsmith" / "scripts"
INSPECT = SCRIPTS / "run_inspect.py"
EVIDENCE = SCRIPTS / "evidence_packet.py"
COCKPIT = SCRIPTS / "review_cockpit.py"
STATE = SCRIPTS / "delivery_state.py"
TELEMETRY = SCRIPTS / "run_telemetry.py"
EVALS = ROOT / "skills" / "draftsmith" / "evals" / "evals.json"
VALIDATE_EVALS = SCRIPTS / "validate_evals.py"
SKILL = ROOT / "skills" / "draftsmith" / "SKILL.md"
FULL_LANE = ROOT / "skills" / "draftsmith" / "references" / "full-lane.md"
LIGHT_LANE = ROOT / "skills" / "draftsmith" / "references" / "light-lane.md"
BRIEF_VISUAL = ROOT / "skills" / "draftsmith" / "templates" / "brief-visual.md"
REPLY_CONTRACT = ROOT / "skills" / "draftsmith" / "templates" / "reply-contract.md"
README_FILE = ROOT / "README.md"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"


class RunUxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-ux-test-")
        self.base = Path(self.tempdir.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        (self.repo / "tracked.txt").write_text("clean\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], check=True, capture_output=True, text=True)

    def invoke(self, script: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(script), *args], check=check, capture_output=True, text=True)

    def evidence_input(self, *, missing: bool = False) -> Path:
        path = self.base / ("missing.json" if missing else "evidence.json")
        results = [] if missing else [{"id": "AC-1", "status": "pass", "summary": "unit test passed"}]
        path.write_text(
            json.dumps(
                {
                    "acceptance_criteria": [{"id": "AC-1", "criterion": "observable behavior"}],
                    "results": results,
                    "not_covered": [],
                    "verification": [{"kind": "test", "status": "pass", "summary": "test suite passed"}],
                    "risks": ["browser E2E was not required"],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_doctor_and_missing_status_are_read_only(self) -> None:
        before = sorted(str(path.relative_to(self.repo / ".git")) for path in (self.repo / ".git").rglob("*"))
        doctor = json.loads(self.invoke(INSPECT, "--repo", str(self.repo), "doctor").stdout)
        status = json.loads(self.invoke(INSPECT, "--repo", str(self.repo), "status").stdout)
        after = sorted(str(path.relative_to(self.repo / ".git")) for path in (self.repo / ".git").rglob("*"))
        self.assertTrue(doctor["read_only"])
        self.assertTrue(doctor["required"]["required_agents"])
        self.assertTrue(doctor["required"]["required_references"])
        self.assertTrue(doctor["required"]["required_scripts"])
        self.assertEqual(status["state"], "not_started")
        self.assertEqual(before, after)

    def test_status_reads_state_without_updating_revision(self) -> None:
        self.invoke(STATE, "--repo", str(self.repo), "init", "--goal", "review_complete")
        before = json.loads(self.invoke(STATE, "--repo", str(self.repo), "show").stdout)
        status = json.loads(self.invoke(INSPECT, "--repo", str(self.repo), "status").stdout)
        after = json.loads(self.invoke(STATE, "--repo", str(self.repo), "show").stdout)
        self.assertEqual(status["phase"], "implemented")
        self.assertEqual(status["human_gate"], "none")
        self.assertEqual(before["revision"], after["revision"])

    def test_status_reports_active_default_run_without_delivery_state(self) -> None:
        started = json.loads(
            self.invoke(
                TELEMETRY,
                "--repo",
                str(self.repo),
                "start",
                "--lane",
                "light",
                "--entry",
                "requirements",
                "--goal",
                "implemented",
            ).stdout
        )
        status = json.loads(self.invoke(INSPECT, "--repo", str(self.repo), "status").stdout)
        self.assertEqual(status["state"], "inner_loop")
        self.assertEqual(status["lane"], "light")
        self.assertEqual(status["telemetry_revision"], started["revision"])
        self.assertFalse((self.repo / ".git" / "draftsmith-delivery").exists())

    def test_delivery_run_card_loads_only_delivery_reference(self) -> None:
        card = json.loads(
            self.invoke(
                INSPECT,
                "--repo",
                str(self.repo),
                "run-card",
                "--entry",
                "delivery",
                "--goal",
                "review_complete",
                "--lane",
                "unknown",
            ).stdout
        )
        self.assertEqual(card["references"], ["references/delivery-loop.md"])

    def test_evidence_rejects_stale_sha_dirty_tree_and_missing_ac(self) -> None:
        head = self.git("rev-parse", "HEAD").stdout.strip()
        source = self.evidence_input()
        stale = self.invoke(EVIDENCE, "--repo", str(self.repo), "--input", str(source), "--pr-head", "a" * 40, check=False)
        self.assertEqual(stale.returncode, 2)
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        dirty = self.invoke(EVIDENCE, "--repo", str(self.repo), "--input", str(source), "--pr-head", head, check=False)
        self.assertEqual(dirty.returncode, 2)
        self.git("restore", "tracked.txt")
        missing = self.invoke(EVIDENCE, "--repo", str(self.repo), "--input", str(self.evidence_input(missing=True)), "--pr-head", head, check=False)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("coverage mismatch", missing.stderr)
        duplicate_source = self.evidence_input()
        duplicate_payload = json.loads(duplicate_source.read_text(encoding="utf-8"))
        duplicate_payload["results"].append(
            {"id": "AC-1", "status": "fail", "summary": "contradictory duplicate"}
        )
        duplicate_source.write_text(json.dumps(duplicate_payload), encoding="utf-8")
        duplicate = self.invoke(
            EVIDENCE,
            "--repo",
            str(self.repo),
            "--input",
            str(duplicate_source),
            "--pr-head",
            head,
            check=False,
        )
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("duplicate AC result", duplicate.stderr)

    def test_evidence_supports_detached_head_and_full_oid(self) -> None:
        self.git("switch", "-q", "--detach", "HEAD")
        head = self.git("rev-parse", "HEAD").stdout.strip()
        result = self.invoke(EVIDENCE, "--repo", str(self.repo), "--input", str(self.evidence_input()), "--pr-head", head)
        packet = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
        self.assertEqual(packet["verified_head"], head)
        self.assertTrue(packet["created_from_clean_matching_heads"])
        self.assertEqual(len(head), 40)
        markdown = Path(result.stdout.strip()).with_name(packet["packet_file"])
        rendered = markdown.read_text(encoding="utf-8")
        self.assertIn("## Not covered", rendered)
        self.assertIn(f"Target head: `{head}`", rendered)

    def test_cockpit_reports_fresh_and_unknown_without_absolute_home_paths(self) -> None:
        head = self.git("rev-parse", "HEAD").stdout.strip()
        evidence_path = Path(
            self.invoke(EVIDENCE, "--repo", str(self.repo), "--input", str(self.evidence_input()), "--pr-head", head).stdout.strip()
        )
        unknown = evidence_path.parent / "<script>.json"
        unknown.write_text("{}\n", encoding="utf-8")
        os.chmod(unknown, 0o600)
        index = evidence_path.parents[1] / "index.json"
        index.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {"kind": "evidence", "path": str(evidence_path)},
                        {"kind": "verify-report", "path": str(unknown)},
                    ]
                }
            ),
            encoding="utf-8",
        )
        output = Path(
            self.invoke(
                COCKPIT,
                "--repo",
                str(self.repo),
                "--index",
                str(index),
                "--pr-head",
                head,
            ).stdout.strip()
        )
        rendered = output.read_text(encoding="utf-8")
        self.assertIn(">fresh<", rendered)
        self.assertIn(">unknown<", rendered)
        self.assertNotIn(str(Path.home()), rendered)
        self.assertNotIn("<script>.json", rendered)
        self.assertIn("&lt;script&gt;.json", rendered)
        remote_changed = Path(
            self.invoke(
                COCKPIT,
                "--repo",
                str(self.repo),
                "--index",
                str(index),
                "--pr-head",
                "a" * 40,
            ).stdout.strip()
        )
        self.assertIn(">stale<", remote_changed.read_text(encoding="utf-8"))
        packet_path = evidence_path.with_name(json.loads(evidence_path.read_text())["packet_file"])
        packet_path.write_text("tampered\n", encoding="utf-8")
        stale_output = Path(
            self.invoke(
                COCKPIT,
                "--repo",
                str(self.repo),
                "--index",
                str(index),
                "--pr-head",
                head,
            ).stdout.strip()
        )
        self.assertIn(">stale<", stale_output.read_text(encoding="utf-8"))

    def test_cockpit_rejects_traversal_and_symlink(self) -> None:
        index = self.repo / "index.json"
        index.write_text(json.dumps({"artifacts": [{"kind": "plan", "path": "../secret.md"}]}), encoding="utf-8")
        self.git("add", "index.json")
        self.git("commit", "-q", "-m", "index")
        traversal = self.invoke(COCKPIT, "--repo", str(self.repo), "--index", str(index), check=False)
        self.assertEqual(traversal.returncode, 2)
        target = self.repo / "target.md"
        target.write_text("target", encoding="utf-8")
        link = self.repo / "linked.md"
        link.symlink_to(target)
        index.write_text(json.dumps({"artifacts": [{"kind": "plan", "path": "linked.md"}]}), encoding="utf-8")
        symlink = self.invoke(COCKPIT, "--repo", str(self.repo), "--index", str(index), check=False)
        self.assertEqual(symlink.returncode, 2)
        self.assertIn("symlink", symlink.stderr)

    def test_gated_understanding_contract_is_explicit(self) -> None:
        full_lane = FULL_LANE.read_text(encoding="utf-8")
        light_lane = LIGHT_LANE.read_text(encoding="utf-8")
        brief_visual = BRIEF_VISUAL.read_text(encoding="utf-8")
        reply_contract = REPLY_CONTRACT.read_text(encoding="utf-8")
        readme = README_FILE.read_text(encoding="utf-8")
        changelog = CHANGELOG_FILE.read_text(encoding="utf-8")

        for required_contract in (
            "一度に一論点だけ確認する",
            "推奨デフォルトと理由1行",
            "重要な未決事項が残る間は要件確定を宣言せず",
            "gated-display-material:start; reference-only",
            "Markdownの箇条書き記号や連番を付けず",
            "判断素材 D-01",
            "重要判断が0件であることは正当な出力",
            "別案を選ぶと何が壊れるか",
            "逐語引用",
            "mainは欠けた素材を創作せず",
            "参照専用であり、implementerへの編集指示ではない",
            "実装開始を承認する",
            "カード ID を指定して深掘りする",
            "未解消の疑問が残る間は Step 5 へ進まない",
        ):
            self.assertIn(required_contract, full_lane)

        skeleton = brief_visual.split("## HTML スケルトン", 1)[1]
        understanding_order = [
            "<h2>1. 一言要約</h2>",
            "<h2>2. 読む前提</h2>",
            "<h2>3. 構造</h2>",
            "<h2>4. 判断カード</h2>",
            "<h2>5. 原文根拠</h2>",
        ]
        positions = [skeleton.index(marker) for marker in understanding_order]
        self.assertEqual(positions, sorted(positions))

        self.assertIn("0〜5件", brief_visual)
        self.assertIn('<p class="empty">重要判断なし</p>', brief_visual)
        for card_field in (
            "判断 ID",
            "何を決めたか",
            "なぜか",
            "別案を選ぶと何が壊れるか",
            "原文根拠",
        ):
            self.assertIn(card_field, brief_visual)

        self.assertIn("<pre>{{ reading_prerequisites_body }}</pre>", skeleton)
        self.assertNotIn("reading_prerequisite_items", brief_visual)
        self.assertIn("行ごとのwrapper生成や記号の追加は行わない", brief_visual)

        self.assertIn("<summary>確定要件（原文）</summary>", skeleton)
        self.assertIn("<pre>{{ requirements_body }}</pre>", skeleton)
        for original_element in (
            "<pre>{{ brief_body }}</pre>",
            "<pre>{{ open_questions_body }}</pre>",
            "<pre>{{ broken_assumptions_body }}</pre>",
            "<pre>{{ traceability_body }}</pre>",
            "<pre>{{ mini_adr_body }}</pre>",
        ):
            self.assertIn(original_element, skeleton)

        for escaped_character in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            self.assertIn(escaped_character, brief_visual)
        self.assertIn('<article class="decision-card" id="{{ decision_id }}">', brief_visual)
        self.assertIn("ソース値をHTML断片として挿入しない", brief_visual)

        self.assertIn("Content-Security-Policy", skeleton)
        self.assertNotIn("<script", skeleton.lower())
        self.assertNotIn("http://", skeleton)
        self.assertNotIn("https://", skeleton)

        self.assertIn("自律モードでは既存挙動維持", full_lane)
        self.assertNotIn("理解確認gate", light_lane)
        self.assertEqual(
            re.findall(r"^## 要素 ([1-5]):", reply_contract, flags=re.MULTILINE),
            ["1", "2", "3", "4", "5"],
        )
        for forbidden_dependency in ("explain-visually", "grill-with-docs"):
            self.assertNotIn(forbidden_dependency, full_lane)
            self.assertNotIn(forbidden_dependency, brief_visual)

        self.assertIn("one unresolved issue at a time", readme)
        self.assertRegex(readme, r"request a deeper\s+explanation by card ID")
        self.assertIn("重要な未決事項を一度に一論点ずつ", readme)
        self.assertIn("カード ID を", readme)

        unreleased = changelog.split("## [Unreleased]", 1)[1].split("## [1.14.0]", 1)[0]
        self.assertIn("理解確認フロー", unreleased)
        self.assertIn("`--gated`", unreleased)

    def test_behavioral_contract_validator_has_red_probes(self) -> None:
        valid = self.invoke(VALIDATE_EVALS, "--evals", str(EVALS), "--skill", str(SKILL))
        self.assertEqual(valid.stdout.strip(), "fixture-valid; model behavior not executed")
        broken_eval = self.base / "broken-evals.json"
        payload = json.loads(EVALS.read_text(encoding="utf-8"))
        payload["evals"][0]["expectations"] = []
        broken_eval.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(
            self.invoke(VALIDATE_EVALS, "--evals", str(broken_eval), "--skill", str(SKILL), check=False).returncode,
            2,
        )


if __name__ == "__main__":
    unittest.main()
