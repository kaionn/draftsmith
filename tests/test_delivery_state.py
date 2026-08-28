from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "draftsmith" / "scripts" / "delivery_state.py"
TELEMETRY_SCRIPT = ROOT / "skills" / "draftsmith" / "scripts" / "run_telemetry.py"
RECEIPT_COMPAT = ROOT / "skills" / "draftsmith" / "scripts" / "delivery_receipt.py"


class DeliveryStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-delivery-test-")
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("commit", "--allow-empty", "-q", "-m", "init")
        self.git("branch", "-M", "main")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def state(self, *args: str, repo: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(repo or self.repo), *args],
            check=check,
            capture_output=True,
            text=True,
        )

    def update(
        self,
        *args: str,
        repo: Path | None = None,
        check: bool = True,
        expect_revision: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if expect_revision is None:
            expect_revision = json.loads(self.state("show", repo=repo).stdout)["revision"]
        return self.state(
            "update",
            "--expect-revision",
            str(expect_revision),
            *args,
            repo=repo,
            check=check,
        )

    def test_init_uses_git_metadata_and_keeps_worktree_clean(self) -> None:
        result = self.state(
            "init",
            "--entry",
            "requirements",
            "--goal",
            "review_complete",
            "--plan-file",
            "plans/example.md",
        )
        payload = json.loads(result.stdout)
        path = Path(self.state("path").stdout.strip())

        self.assertEqual(payload["phase"], "implemented")
        self.assertEqual(payload["plan_file"], "plans/example.md")
        self.assertEqual(payload["revision"], 0)
        self.assertTrue(path.is_file())
        self.assertIn(str(self.repo / ".git" / "draftsmith-delivery"), str(path))
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.git("status", "--porcelain").stdout, "")

    def test_valid_and_invalid_transitions(self) -> None:
        self.state("init", "--goal", "review_complete")
        self.update("--phase", "commit_gate")
        invalid = self.update("--phase", "review_complete", check=False)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid transition", invalid.stderr)
        payload = json.loads(self.state("show").stdout)
        self.assertEqual(payload["phase"], "commit_gate")

    def test_review_feedback_loop_and_goal_extension(self) -> None:
        self.state(
            "init",
            "--entry",
            "delivery",
            "--goal",
            "review_complete",
            "--phase",
            "pr_open",
            "--pr-number",
            "42",
        )
        for phase in ("wait_ci_review", "review_triage"):
            self.update("--phase", phase)
        self.update("--phase", "review_fix", "--increment-review-cycles")
        self.update("--phase", "commit_gate")
        self.update("--phase", "wait_ci_review", "--observation", "ci_green")
        self.update("--phase", "final_verify", "--observation", "verification_passed")
        self.update("--phase", "prepare_review_request")
        self.update("--phase", "wait_human_review", "--observation", "review_requested")
        self.update("--phase", "review_complete", "--observation", "review_complete")

        payload = json.loads(self.state("show").stdout)
        self.assertEqual(payload["phase"], "review_complete")
        self.assertEqual(payload["review_cycles"], 1)

        self.update("--goal", "merge_ready", "--phase", "final_verify")
        self.update("--phase", "merge_ready")
        self.assertEqual(json.loads(self.state("show").stdout)["phase"], "merge_ready")

    def test_fourth_review_cycle_is_rejected(self) -> None:
        self.state("init", "--goal", "review_complete")
        for _ in range(3):
            self.update("--increment-review-cycles")
        result = self.update("--increment-review-cycles", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("review cycle limit reached", result.stderr)
        self.assertEqual(json.loads(self.state("show").stdout)["review_cycles"], 3)

    def test_external_merge_reconciliation_requires_observation(self) -> None:
        self.state(
            "init",
            "--entry",
            "delivery",
            "--goal",
            "review_complete",
            "--phase",
            "pr_open",
            "--pr-number",
            "42",
        )
        rejected = self.update("--phase", "done", check=False)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("done requires", rejected.stderr)

        self.update("--phase", "done", "--observation", "pr_merged")
        self.assertEqual(json.loads(self.state("show").stdout)["phase"], "done")

    def test_stale_revision_is_rejected_without_mutating_state(self) -> None:
        self.state("init", "--goal", "review_complete")
        self.update("--phase", "commit_gate", expect_revision=0)

        stale = self.update(
            "--phase", "prepare_pr", expect_revision=0, check=False
        )
        self.assertEqual(stale.returncode, 2)
        self.assertIn("revision conflict", stale.stderr)

        payload = json.loads(self.state("show").stdout)
        self.assertEqual(payload["phase"], "commit_gate")
        self.assertEqual(payload["revision"], 1)

    def test_concurrent_update_is_rejected_by_lock(self) -> None:
        self.state("init", "--goal", "review_complete")
        path = Path(self.state("path").stdout.strip())
        state_lock = runpy.run_path(str(SCRIPT))["state_lock"]

        with state_lock(path):
            result = self.update(
                "--phase", "commit_gate", expect_revision=0, check=False
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("locked by another updater", result.stderr)
        self.assertEqual(json.loads(self.state("show").stdout)["revision"], 0)

    def test_delivery_entry_rejects_implemented_goal(self) -> None:
        result = self.state("init", "--entry", "delivery", "--goal", "implemented", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("delivery entry requires", result.stderr)

    def test_routing_defaults_and_shortcuts(self) -> None:
        default = json.loads(self.state("resolve").stdout)
        self.assertEqual(default, {"entry": "requirements", "goal": "implemented"})

        through_review = json.loads(self.state("resolve", "--through-review").stdout)
        self.assertEqual(through_review, {"entry": "requirements", "goal": "review_complete"})

        delivery = json.loads(self.state("resolve", "--entry", "delivery").stdout)
        self.assertEqual(delivery, {"entry": "delivery", "goal": "review_complete"})

        conflict = self.state(
            "resolve", "--through-review", "--goal", "merge_ready", check=False
        )
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("conflicts", conflict.stderr)

        merged = json.loads(
            self.state("resolve", "--entry", "delivery", "--goal", "merged").stdout
        )
        self.assertEqual(merged, {"entry": "delivery", "goal": "merged"})

    def test_review_fingerprint_is_non_reversible_and_deduplicated(self) -> None:
        head_sha = self.git("rev-parse", "HEAD").stdout.strip()
        fingerprint = self.state(
            "fingerprint", "--thread-id", "thread-42", "--head-sha", head_sha
        ).stdout.strip()
        self.assertEqual(len(fingerprint), 64)
        self.assertNotIn("thread-42", fingerprint)

        self.state("init", "--goal", "review_complete")
        recorded = self.state(
            "record-review",
            "--expect-revision",
            "0",
            "--fingerprint",
            fingerprint,
            "--disposition",
            "implementation",
        )
        payload = json.loads(recorded.stdout)
        self.assertEqual(payload["revision"], 1)
        self.assertEqual(payload["metrics"]["implementation_findings"], 1)

        duplicate = self.state(
            "record-review",
            "--expect-revision",
            "1",
            "--fingerprint",
            fingerprint,
            "--disposition",
            "implementation",
        )
        self.assertEqual(json.loads(duplicate.stdout)["revision"], 1)

        conflict = self.state(
            "record-review",
            "--expect-revision",
            "1",
            "--fingerprint",
            fingerprint,
            "--disposition",
            "design",
            check=False,
        )
        self.assertEqual(conflict.returncode, 2)

    def test_single_driver_lease(self) -> None:
        self.state("init", "--goal", "review_complete")
        claimed = self.state(
            "claim-driver",
            "--expect-revision",
            "0",
            "--kind",
            "runtime_monitor",
            "--lease-id",
            "driver-a",
            "--lease-seconds",
            "60",
        )
        self.assertEqual(json.loads(claimed.stdout)["revision"], 1)

        blocked = self.state(
            "claim-driver",
            "--expect-revision",
            "1",
            "--kind",
            "github_event",
            "--lease-id",
            "driver-b",
            check=False,
        )
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("active driver lease", blocked.stderr)

        released = self.state(
            "release-driver", "--expect-revision", "1", "--lease-id", "driver-a"
        )
        self.assertIsNone(json.loads(released.stdout)["driver"])

    def test_merged_goal_requires_merge_gate_and_observation(self) -> None:
        self.state(
            "init",
            "--entry",
            "delivery",
            "--goal",
            "merged",
            "--phase",
            "merge_ready",
            "--pr-number",
            "42",
        )
        self.update("--phase", "merge_gate")
        rejected = self.update("--phase", "done", check=False)
        self.assertEqual(rejected.returncode, 2)
        self.update("--phase", "done", "--observation", "pr_merged")
        self.assertEqual(json.loads(self.state("show").stdout)["phase"], "done")

    def test_schema_v1_is_migrated_on_next_update(self) -> None:
        self.state("init", "--goal", "review_complete")
        path = Path(self.state("path").stdout.strip())
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = 1
        for field in ("handled_reviews", "metrics", "driver"):
            payload.pop(field)
        path.write_text(json.dumps(payload), encoding="utf-8")

        migrated = json.loads(self.state("show").stdout)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["handled_reviews"], [])
        self.update("--phase", "commit_gate", expect_revision=0)
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["schema_version"], 2)

    def test_receipt_contains_metrics_without_review_content(self) -> None:
        self.state(
            "init",
            "--entry",
            "delivery",
            "--goal",
            "review_complete",
            "--phase",
            "review_complete",
            "--pr-number",
            "42",
        )
        started = subprocess.run(
            [
                sys.executable,
                str(TELEMETRY_SCRIPT),
                "--repo",
                str(self.repo),
                "start",
                "--lane",
                "full",
                "--entry",
                "delivery",
                "--goal",
                "review_complete",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        run_id = json.loads(started.stdout)["run_id"]
        event_result = subprocess.run(
            [
                sys.executable,
                str(TELEMETRY_SCRIPT),
                "--repo",
                str(self.repo),
                "event",
                "--run-id",
                run_id,
                "--expect-revision",
                "0",
                "--event",
                "ci_failure",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        revision = json.loads(event_result.stdout)["revision"]
        receipt_result = subprocess.run(
            [
                sys.executable,
                str(TELEMETRY_SCRIPT),
                "--repo",
                str(self.repo),
                "finish",
                "--run-id",
                run_id,
                "--final-phase",
                "review_complete",
                "--delivery-key",
                Path(self.state("path").stdout.strip()).stem,
                "--expect-revision",
                str(revision),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        receipt_path = Path(receipt_result.stdout.strip())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["counters"]["ci_failures"], 1)
        self.assertNotIn("handled_reviews", receipt)
        self.assertNotIn("authorization", receipt)
        self.assertEqual(stat.S_IMODE(receipt_path.stat().st_mode), 0o600)

    def test_legacy_delivery_receipt_cli_creates_private_v2_receipt(self) -> None:
        self.state(
            "init",
            "--entry",
            "delivery",
            "--goal",
            "review_complete",
            "--phase",
            "review_complete",
            "--pr-number",
            "42",
        )
        self.state("record-event", "--expect-revision", "0", "--event", "ci_failure")
        result = subprocess.run(
            [sys.executable, str(RECEIPT_COMPAT), "--repo", str(self.repo)],
            check=True,
            capture_output=True,
            text=True,
        )
        receipt = json.loads(Path(result.stdout.strip()).read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], 2)
        self.assertEqual(receipt["lane"], "unknown")
        self.assertEqual(receipt["final_phase"], "review_complete")
        self.assertEqual(receipt["delivery_counters"]["ci_failures"], 1)
        self.assertNotIn("pr_number", receipt)
        self.assertNotIn("key", receipt)

    def test_delivery_documentation_matches_state_enums(self) -> None:
        state = runpy.run_path(str(SCRIPT))
        skill = (ROOT / "skills" / "draftsmith" / "SKILL.md").read_text(encoding="utf-8")
        reference = (
            ROOT / "skills" / "draftsmith" / "references" / "delivery-loop.md"
        ).read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for goal in state["GOALS"]:
            for label, text in (("skill", skill), ("reference", reference), ("README", readme)):
                self.assertIn(f"`{goal}`", text, f"{label} does not document goal {goal}")
        for phase in state["PHASES"]:
            self.assertIn(f"`{phase}`", reference, f"reference does not document phase {phase}")
        self.assertNotIn("- `--from=auto`", skill)

    def test_plan_path_traversal_is_rejected(self) -> None:
        result = self.state("init", "--plan-file", "../secret.md", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("plan_file", result.stderr)

    def test_unknown_state_key_is_rejected(self) -> None:
        self.state("init")
        path = Path(self.state("path").stdout.strip())
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["authorization"] = "persisted"
        path.write_text(json.dumps(payload), encoding="utf-8")

        result = self.state("validate", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid state keys", result.stderr)

    def test_linked_worktree_and_detached_head_get_distinct_state(self) -> None:
        linked = Path(self.tempdir.name) / "linked"
        self.git("worktree", "add", "-q", "-b", "kaionn/linked", str(linked))
        main_path = Path(self.state("init").stdout and self.state("path").stdout.strip())
        linked_path = Path(
            self.state(
                "init",
                "--entry",
                "delivery",
                "--goal",
                "review_complete",
                "--phase",
                "pr_open",
                repo=linked,
            ).stdout
            and self.state("path", repo=linked).stdout.strip()
        )
        self.assertNotEqual(main_path, linked_path)
        self.assertIn("worktrees", linked_path.parts)

        self.git("switch", "-q", "--detach", "HEAD", cwd=linked)
        detached_path = Path(self.state("path", repo=linked).stdout.strip())
        self.assertIn("detached-", detached_path.name)
        self.git("worktree", "remove", "--force", str(linked))


if __name__ == "__main__":
    unittest.main()
