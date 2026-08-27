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
