from __future__ import annotations

import json
import os
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
