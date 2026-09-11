from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/draftsmith/scripts/delivery_state.py"


class PreDeliveryReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="draftsmith-pre-review-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("commit", "--allow-empty", "-qm", "fixture")
        self.policy = self.repo / ".draftsmith/review-policy.json"
        self.policy.parent.mkdir()
        self.policy.write_text(json.dumps({"required_workflows": ["quality-review"]}))
        (self.repo / "code.txt").write_text("reviewed content\n")
        self.call("init", "--goal", "pr_open")

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", "-C", str(self.repo), *args], text=True).strip()

    def call(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), *args],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0 if ok else 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def state(self) -> dict:
        return json.loads(self.call("show").stdout)

    def mutate(self, command: str, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        return self.call(command, "--expect-revision", str(self.state()["revision"]), *args, ok=ok)

    def record(self, workflow: str = "quality-review", status: str = "converged", *, ok: bool = True) -> None:
        snapshot = self.call("review-snapshot").stdout.strip()
        self.mutate(
            "record-pre-review", "--workflow", workflow, "--status", status,
            "--snapshot", snapshot, "--evidence-sha256", hashlib.sha256(b"local review evidence").hexdigest(),
            ok=ok,
        )

    def fixture_commit(self) -> None:
        # Only this disposable test repository is staged/committed, never the source worktree.
        self.git("add", "-A")
        self.git("commit", "-qm", "reviewed fixture")

    def test_red_missing_and_blocked_green_converged(self) -> None:
        before = self.state()
        failed = self.mutate("update", "--phase", "commit_gate", ok=False)
        self.assertIn("pre-delivery review required", failed.stderr)
        self.assertEqual(self.state(), before)
        self.record(status="blocked")
        self.mutate("update", "--phase", "commit_gate", ok=False)
        self.record()
        self.mutate("update", "--phase", "commit_gate")
        self.call("check-pre-review", "--gate", "stage")
        self.record(status="pending")
        self.call("check-pre-review", "--gate", "stage", ok=False)

    def test_all_workflows_required_and_pr_feedback_does_not_satisfy(self) -> None:
        self.mutate("require-pre-review", "--workflow", "security-review")
        self.mutate("record-review", "--fingerprint", "a" * 64, "--disposition", "no_action")
        self.record()
        self.mutate("update", "--phase", "commit_gate", ok=False)
        self.record("security-review")
        self.mutate("update", "--phase", "commit_gate")

    def test_commit_preserves_snapshot_and_push_requires_clean_content(self) -> None:
        snapshot = self.call("review-snapshot").stdout
        self.record()
        self.mutate("update", "--phase", "commit_gate")
        self.mutate("update", "--phase", "prepare_pr", ok=False)
        self.call("check-pre-review", "--gate", "push", ok=False)
        self.call("check-pre-review", "--gate", "commit", ok=False)
        self.git("add", "-A")
        self.call("check-pre-review", "--gate", "commit")
        self.git("reset", "-q")
        # A partial commit is still rejected even though the whole worktree was reviewed.
        self.git("add", "code.txt")
        self.git("commit", "-qm", "partial fixture")
        self.mutate("update", "--phase", "prepare_pr", ok=False)
        self.fixture_commit()
        self.assertEqual(self.call("review-snapshot").stdout, snapshot)
        self.mutate("update", "--phase", "prepare_pr", "--pending-gate", "push")
        self.call("check-pre-review", "--gate", "push")
        self.mutate("update", "--phase", "pr_open", "--pending-gate", "pr_create")

    def test_changes_additions_deletions_and_mode_invalidate(self) -> None:
        self.fixture_commit()
        file = self.repo / "code.txt"
        original_mode = file.stat().st_mode
        mutations = (
            lambda: file.write_text("changed\n"),
            lambda: (self.repo / "new.txt").write_text("new\n"),
            lambda: file.chmod(original_mode | 0o111),
            lambda: file.unlink(),
        )
        for change in mutations:
            with self.subTest(change=change):
                self.record()
                change()
                self.call("check-pre-review", "--gate", "stage", ok=False)

    def test_late_result_cannot_stamp_new_content(self) -> None:
        old = self.call("review-snapshot").stdout.strip()
        (self.repo / "code.txt").write_text("new content")
        before = self.state()
        self.mutate(
            "record-pre-review", "--workflow", "quality-review", "--status", "converged",
            "--snapshot", old, "--evidence-sha256", "a" * 64, ok=False,
        )
        self.assertEqual(self.state(), before)

    def test_gate_only_same_phase_back_edge_and_blocked_resume_are_checked(self) -> None:
        for gate in ("commit", "push", "pr_create", "pr_update"):
            with self.subTest(gate=gate):
                self.mutate("update", "--pending-gate", gate, ok=False)
        self.mutate("update", "--phase", "blocked")
        for phase in ("commit_gate", "prepare_pr", "pr_open", "wait_ci_review", "review_complete", "done"):
            with self.subTest(phase=phase):
                self.mutate("update", "--phase", phase, "--observation", "pr_merged", ok=False)
        self.mutate("update", "--phase", "review_fix")
        self.mutate("update", "--phase", "commit_gate", ok=False)
        self.record()
        self.mutate("update", "--phase", "commit_gate")
        (self.repo / "code.txt").write_text("new findings")
        self.mutate("update", "--phase", "commit_gate", ok=False)
        self.mutate("update", "--phase", "wait_ci_review", ok=False)
        self.mutate("update", "--phase", "blocked", "--pending-gate", "human_decision")

    def test_existing_pr_back_edge_green(self) -> None:
        self.record()
        self.mutate("update", "--phase", "commit_gate")
        self.fixture_commit()
        self.mutate("update", "--phase", "wait_ci_review")

    def test_policy_removal_does_not_clear_pinned_requirement(self) -> None:
        self.policy.unlink()
        self.mutate("update", "--phase", "commit_gate", ok=False)
        self.assertIn("quality-review", self.state()["pre_delivery_reviews"])
        self.record()
        self.mutate("update", "--phase", "commit_gate")

    def test_new_policy_requirement_blocks_existing_run(self) -> None:
        self.record()
        self.policy.write_text(json.dumps({"required_workflows": ["quality-review", "security-review"]}))
        self.record()
        self.mutate("update", "--phase", "commit_gate", ok=False)
        self.record("security-review")
        self.mutate("update", "--phase", "commit_gate")

    def test_policy_cannot_init_past_gate(self) -> None:
        for phase in ("commit_gate", "prepare_pr", "pr_open", "wait_ci_review", "done"):
            with self.subTest(phase=phase):
                self.call("--key", "new-" + phase, "init", "--goal", "pr_open", "--phase", phase, ok=False)

    def test_untrusted_command_policy_and_bad_identifiers_fail_closed(self) -> None:
        marker = self.repo / "must-not-exist"
        payloads = (
            {"required_workflows": [], "command": f"touch {marker}"},
            {"required_workflows": [f"$(touch {marker})"]},
            {"required_workflows": ["../workflow"]},
            {"required_workflows": ["review", "review"]},
            {"required_workflows": "review"},
            {"required_workflows": [None]},
            [],
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                self.policy.write_text(json.dumps(payload))
                self.mutate("update", "--phase", "commit_gate", ok=False)
                self.assertFalse(marker.exists())
        self.policy.write_text("{invalid")
        self.call("check-pre-review", "--gate", "commit", ok=False)

    def test_invalid_attestation_and_unknown_state_fields_rejected(self) -> None:
        snapshot = self.call("review-snapshot").stdout.strip()
        for extra in ([], ["--evidence-sha256", "not-a-digest"]):
            self.mutate(
                "record-pre-review", "--workflow", "quality-review", "--status", "converged",
                "--snapshot", snapshot, *extra, ok=False,
            )
        self.record("not-required", ok=False)
        self.mutate("require-pre-review", "--workflow", "$(unsafe)", ok=False)
        path = Path(self.call("path").stdout.strip())
        state = self.state()
        state["pre_delivery_reviews"]["quality-review"]["command"] = "ignored?"
        path.write_text(json.dumps(state))
        self.call("validate", ok=False)

    def test_stale_revision_and_lock_leave_state_unchanged(self) -> None:
        self.record()
        before = self.state()
        self.call("require-pre-review", "--expect-revision", "0", "--workflow", "other", ok=False)
        module = runpy.run_path(str(SCRIPT))
        with module["state_lock"](Path(self.call("path").stdout.strip())):
            self.mutate("require-pre-review", "--workflow", "other", ok=False)
        self.assertEqual(self.state(), before)

    def test_symlinks_hash_targets_but_policy_symlinks_are_rejected(self) -> None:
        link = self.repo / "link"
        link.symlink_to("code.txt")
        self.record()
        link.unlink()
        link.symlink_to("missing.txt")
        self.call("check-pre-review", "--gate", "stage", ok=False)
        self.policy.unlink()
        self.policy.symlink_to("missing.json")
        self.mutate("update", "--phase", "commit_gate", ok=False)

    def test_special_file_and_sparse_index_fail_closed(self) -> None:
        self.fixture_commit()
        if hasattr(os, "mkfifo"):
            # Git excludes untracked FIFOs from ls-files; replace a tracked file instead.
            fifo = self.repo / "code.txt"
            content = fifo.read_bytes()
            fifo.unlink()
            os.mkfifo(fifo)
            self.call("review-snapshot", ok=False)
            fifo.unlink()
            fifo.write_bytes(content)
            self.policy.unlink()
            os.mkfifo(self.policy)
            self.call("check-pre-review", "--gate", "stage", ok=False)
            self.policy.unlink()
            self.policy.write_text(json.dumps({"required_workflows": ["quality-review"]}))
        self.git("update-index", "--skip-worktree", "code.txt")
        self.call("review-snapshot", ok=False)
        self.git("update-index", "--no-skip-worktree", "code.txt")
        self.git("update-index", "--assume-unchanged", "code.txt")
        self.call("review-snapshot", ok=False)

    def test_uninitialized_submodule_and_unmerged_index_are_rejected(self) -> None:
        self.fixture_commit()
        self.git("update-index", "--add", "--cacheinfo", "160000", self.git("rev-parse", "HEAD"), "vendor")
        self.call("review-snapshot", ok=False)
        self.git("update-index", "--force-remove", "vendor")
        oid = self.git("rev-parse", "HEAD:code.txt")
        self.git("update-index", "--force-remove", "code.txt")
        subprocess.run(
            ["git", "-C", str(self.repo), "update-index", "--index-info"],
            input=f"100644 {oid} 1\tcode.txt\n100644 {oid} 2\tcode.txt\n".encode(),
            check=True, capture_output=True,
        )
        self.call("review-snapshot", ok=False)

    def test_committed_deletion_and_unusual_paths_preserve_review(self) -> None:
        unusual = self.repo / "space tab\tnewline\n日本語.txt"
        unusual.write_text("delivery content")
        self.fixture_commit()
        (self.repo / "code.txt").unlink()
        self.record()
        snapshot = self.call("review-snapshot").stdout
        self.git("add", "-A")
        self.call("check-pre-review", "--gate", "commit")
        self.git("commit", "-qm", "fixture deletion")
        self.assertEqual(self.call("review-snapshot").stdout, snapshot)
        self.call("check-pre-review", "--gate", "push")

    def test_no_filter_or_external_diff_execution(self) -> None:
        module = runpy.run_path(str(SCRIPT))
        original_run = subprocess.run
        calls = []

        def inspect_run(args, **kwargs):
            calls.append(args)
            return original_run(args, **kwargs)

        self.record()
        self.fixture_commit()
        with patch("subprocess.run", side_effect=inspect_run):
            module["check_pre_delivery_reviews"](self.state(), self.repo, clean=True)
        git_calls = [args[3:] for args in calls if args[0] == "git"]
        self.assertTrue(git_calls)
        self.assertTrue(all(args[0] in ("ls-files", "ls-tree", "rev-parse") for args in git_calls))
        self.assertIn(["ls-tree", "-r", "-z", "HEAD"], git_calls)

    def test_configured_git_filters_are_never_executed_by_gate(self) -> None:
        (self.repo / ".gitattributes").write_text("code.txt filter=review-probe diff=review-probe\n")
        self.fixture_commit()
        self.record()
        marker = Path(self.temp.name) / "filter-ran"
        self.git("config", "filter.review-probe.clean", f"touch '{marker}'; cat")
        self.git("config", "diff.review-probe.textconv", f"touch '{marker}'; cat")
        self.call("check-pre-review", "--gate", "stage")
        self.call("check-pre-review", "--gate", "commit")
        self.call("check-pre-review", "--gate", "push")
        self.assertFalse(marker.exists())
        # Safe red probe: prove the configured sentinel really detects filter execution.
        subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "--path=code.txt", "--stdin"],
            input=b"probe", capture_output=True, check=True,
        )
        self.assertTrue(marker.exists())

    def test_staged_content_different_from_reviewed_worktree_is_rejected(self) -> None:
        self.fixture_commit()
        code = self.repo / "code.txt"
        code.write_text("unreviewed staged code")
        self.git("add", "code.txt")
        code.write_text("reviewed working code")
        self.record()
        self.call("check-pre-review", "--gate", "stage")
        self.call("check-pre-review", "--gate", "commit", ok=False)
        self.git("add", "code.txt")
        self.call("check-pre-review", "--gate", "commit")

    def test_plan_commit_excludes_only_declared_untracked_artifact(self) -> None:
        plan = self.repo / "plans/task.md"
        plan.parent.mkdir()
        plan.write_text("> ⚠ 一時設計文書\n- Status: implemented\n")
        self.mutate("update", "--plan-file", "plans/task.md")
        self.record()
        snapshot = self.call("review-snapshot").stdout
        self.git("add", "code.txt", ".draftsmith/review-policy.json")
        self.call("check-pre-review", "--gate", "commit")
        self.git("commit", "-qm", "fixture with design message")
        plan.unlink()
        self.assertEqual(self.call("review-snapshot").stdout, snapshot)
        self.call("check-pre-review", "--gate", "push")
        other = self.repo / "plans/other.md"
        other.write_text("not the declared artifact")
        self.call("check-pre-review", "--gate", "stage", ok=False)
        plan.write_text("tracked plan is not supported")
        self.git("add", "plans/task.md")
        self.call("review-snapshot", ok=False)

    def test_push_rejects_dirty_index_even_when_worktree_matches_head(self) -> None:
        self.fixture_commit()
        self.record()
        code = self.repo / "code.txt"
        original = code.read_text()
        code.write_text("unreviewed staged change")
        self.git("add", "code.txt")
        code.write_text(original)
        self.call("check-pre-review", "--gate", "push", ok=False)

    def test_contract_keeps_review_and_human_gates_separate(self) -> None:
        skill = (ROOT / "skills/draftsmith/SKILL.md").read_text()
        delivery = (ROOT / "skills/draftsmith/references/delivery-loop.md").read_text()
        plan_commit = (ROOT / "skills/plan-commit/SKILL.md").read_text()
        for contract in ("reviewer-light", "review-only", "human_decision", "承認ではない"):
            self.assertIn(contract, skill)
        for command in ("require-pre-review", "record-pre-review", "review-snapshot", "check-pre-review"):
            self.assertIn(command, delivery)
        self.assertIn("check-pre-review --gate stage", plan_commit)
        self.assertIn("check-pre-review --gate commit", plan_commit)
        self.assertIn("第二のstate owner", skill)

    def test_old_state_unchanged_when_no_requirements(self) -> None:
        self.policy.unlink()
        self.call("--key", "legacy", "init", "--goal", "pr_open", "--phase", "pr_open")
        state = json.loads(self.call("--key", "legacy", "show").stdout)
        self.assertNotIn("pre_delivery_reviews", state)
        self.call("--key", "legacy", "update", "--expect-revision", "0", "--phase", "wait_ci_review")

    def test_linked_worktree_does_not_inherit_review_attestation(self) -> None:
        self.fixture_commit()
        self.record()
        linked = Path(self.temp.name) / "linked"
        self.git("worktree", "add", "-qb", "linked-review", str(linked))
        original = self.repo
        try:
            self.repo = linked
            state = json.loads(self.call("init", "--goal", "pr_open").stdout)
            self.assertEqual(state["pre_delivery_reviews"]["quality-review"]["status"], "pending")
            self.mutate("update", "--phase", "commit_gate", ok=False)
        finally:
            self.repo = original


if __name__ == "__main__":
    unittest.main()
