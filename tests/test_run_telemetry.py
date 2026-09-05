from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "draftsmith" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from run_telemetry import TelemetryError, validate_receipt

STATE = SCRIPTS / "delivery_state.py"
TELEMETRY = SCRIPTS / "run_telemetry.py"
PROPOSALS = SCRIPTS / "receipt_proposals.py"


class RunTelemetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-telemetry-test-")
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("commit", "--allow-empty", "-q", "-m", "init")
        self.git("branch", "-M", "feature/user@example.invalid-WFINFRA-1234")
        self.revisions: dict[str, int] = {}

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def invoke(self, script: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), "--repo", str(self.repo), *args],
            check=check,
            capture_output=True,
            text=True,
        )

    def start(self, lane: str = "full", entry: str = "requirements", goal: str = "implemented") -> str:
        payload = json.loads(
            self.invoke(
                TELEMETRY, "start", "--lane", lane, "--entry", entry, "--goal", goal
            ).stdout
        )
        self.revisions[payload["run_id"]] = payload["revision"]
        return payload["run_id"]

    def event(self, run_id: str, name: str, event_id: str) -> subprocess.CompletedProcess[str]:
        result = self.invoke(
            TELEMETRY,
            "event",
            "--run-id",
            run_id,
            "--expect-revision",
            str(self.revisions[run_id]),
            "--event",
            name,
            "--event-id",
            event_id,
        )
        self.revisions[run_id] = json.loads(result.stdout)["revision"]
        return result

    def finish_result(
        self, run_id: str, phase: str = "implemented", *extra: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return self.invoke(
            TELEMETRY,
            "finish",
            "--run-id",
            run_id,
            "--final-phase",
            phase,
            *extra,
            "--expect-revision",
            str(self.revisions[run_id]),
            check=check,
        )

    def finish(self, run_id: str, phase: str = "implemented", *extra: str) -> Path:
        # The receipt path is always the first stdout line; bundled extras follow as JSON.
        return Path(self.finish_result(run_id, phase, *extra).stdout.splitlines()[0].strip())

    def test_default_run_does_not_create_delivery_state_and_resumes_active_telemetry(self) -> None:
        before = list((self.repo / ".git").glob("draftsmith-delivery/*.json"))
        first = self.start()
        second = self.start()
        self.assertEqual(first, second)
        self.assertEqual(before, list((self.repo / ".git").glob("draftsmith-delivery/*.json")))
        receipt = self.finish(first)
        self.assertTrue(receipt.is_file())
        self.assertFalse((self.repo / ".git" / "draftsmith-runs" / f"{first}.json").exists())

    def test_unknown_lane_is_reserved_for_delivery_entry(self) -> None:
        result = self.invoke(
            TELEMETRY,
            "start",
            "--lane",
            "unknown",
            "--entry",
            "requirements",
            "--goal",
            "implemented",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        delivery = self.invoke(
            TELEMETRY,
            "start",
            "--lane",
            "unknown",
            "--entry",
            "delivery",
            "--goal",
            "review_complete",
        )
        self.assertEqual(json.loads(delivery.stdout)["revision"], 0)

    def test_parallel_start_never_creates_multiple_active_runs(self) -> None:
        def invoke_start(_: int) -> subprocess.CompletedProcess[str]:
            return self.invoke(
                TELEMETRY,
                "start",
                "--lane",
                "full",
                "--entry",
                "requirements",
                "--goal",
                "implemented",
                check=False,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(invoke_start, range(8)))
        active = list((self.repo / ".git" / "draftsmith-runs").glob("*.json"))
        self.assertEqual(len(active), 1)
        successful_ids = {
            json.loads(result.stdout)["run_id"] for result in results if result.returncode == 0
        }
        self.assertLessEqual(len(successful_ids), 1)

    def test_v2_receipt_is_private_recursive_and_immutable(self) -> None:
        run_id = self.start()
        event_id = "a" * 32
        self.event(run_id, "ci_failure", event_id)
        first = self.finish(run_id)
        before = first.read_bytes()
        second = self.finish(run_id)
        self.assertEqual(first, second)
        self.assertEqual(before, second.read_bytes())
        conflicting_finish = self.invoke(
            TELEMETRY,
            "finish",
            "--run-id",
            run_id,
            "--expect-revision",
            "999",
            "--final-phase",
            "done",
            check=False,
        )
        self.assertEqual(conflicting_finish.returncode, 2)
        self.assertIn("different final phase", conflicting_finish.stderr)
        receipt = json.loads(before)
        forbidden = {"branch", "key", "pr_number", "repo", "task", "body", "command", "authorization", "email"}

        def keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(keys(item) for item in value), set())
            return set()

        self.assertFalse(keys(receipt) & forbidden)
        rendered = json.dumps(receipt)
        self.assertNotIn("user@example.invalid", rendered)
        self.assertNotIn("WFINFRA-1234", rendered)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(first.parent.stat().st_mode), 0o700)
        privacy_red_probe = dict(receipt)
        privacy_red_probe["authorization"] = "approved"
        with self.assertRaises(TelemetryError):
            validate_receipt(privacy_red_probe)
        phase_red_probe = dict(receipt)
        phase_red_probe["final_phase"] = "done"
        with self.assertRaises(TelemetryError):
            validate_receipt(phase_red_probe)
        after_finish = self.invoke(
            TELEMETRY,
            "event",
            "--run-id",
            run_id,
            "--event",
            "ci_failure",
            "--event-id",
            "d" * 32,
            "--expect-revision",
            str(self.revisions[run_id]),
            check=False,
        )
        self.assertEqual(after_finish.returncode, 2)
        self.assertIn("immutable", after_finish.stderr)

    def test_duplicate_event_is_counted_once(self) -> None:
        run_id = self.start("light")
        for _ in range(2):
            self.event(run_id, "implementation_finding", "b" * 32)
        receipt = json.loads(self.finish(run_id).read_text(encoding="utf-8"))
        self.assertEqual(receipt["counters"]["implementation_findings"], 1)

    def test_stale_telemetry_revision_is_rejected(self) -> None:
        run_id = self.start()
        stale = self.invoke(
            TELEMETRY,
            "event",
            "--run-id",
            run_id,
            "--expect-revision",
            "1",
            "--event",
            "test_failure",
            "--event-id",
            "e" * 32,
            check=False,
        )
        self.assertEqual(stale.returncode, 2)
        self.assertIn("revision conflict", stale.stderr)
        self.event(run_id, "test_failure", "e" * 32)
        receipt = json.loads(self.finish(run_id).read_text(encoding="utf-8"))
        self.assertEqual(receipt["counters"]["test_failures"], 1)

    def test_requirements_run_can_finish_blocked_before_delivery_state_exists(self) -> None:
        run_id = self.start("full", "requirements", "merge_ready")
        receipt = json.loads(self.finish(run_id, "blocked").read_text(encoding="utf-8"))
        self.assertEqual(receipt["goal"], "merge_ready")
        self.assertEqual(receipt["final_phase"], "blocked")
        self.assertFalse((self.repo / ".git" / "draftsmith-delivery").exists())

    def test_symlinked_metadata_output_is_rejected(self) -> None:
        outside = Path(self.tempdir.name) / "outside"
        outside.mkdir()
        (self.repo / ".git" / "draftsmith-runs").symlink_to(outside, target_is_directory=True)
        result = self.invoke(
            TELEMETRY,
            "start",
            "--lane",
            "full",
            "--entry",
            "requirements",
            "--goal",
            "implemented",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_linked_worktree_and_detached_head_use_worktree_git_metadata(self) -> None:
        linked = Path(self.tempdir.name) / "linked"
        self.git("worktree", "add", "-q", "-b", "kaionn/telemetry-linked", str(linked))
        self.git("switch", "-q", "--detach", "HEAD", cwd=linked)
        started = subprocess.run(
            [
                sys.executable,
                str(TELEMETRY),
                "--repo",
                str(linked),
                "start",
                "--lane",
                "light",
                "--entry",
                "requirements",
                "--goal",
                "implemented",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(started.stdout)
        finished = subprocess.run(
            [
                sys.executable,
                str(TELEMETRY),
                "--repo",
                str(linked),
                "finish",
                "--run-id",
                payload["run_id"],
                "--expect-revision",
                str(payload["revision"]),
                "--final-phase",
                "implemented",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        receipt = Path(finished.stdout.strip())
        self.assertIn("worktrees", receipt.parts)
        self.assertTrue(receipt.is_file())

    def test_mixed_v1_v2_receipts_need_two_repeated_signals(self) -> None:
        self.invoke(
            STATE,
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
        self.invoke(
            STATE,
            "record-event",
            "--expect-revision",
            "0",
            "--event",
            "ci_failure",
        )
        run_id = self.start("full", "delivery", "review_complete")
        key = Path(self.invoke(STATE, "path").stdout.strip()).stem
        receipt_dir = self.finish(run_id, "review_complete", "--delivery-key", key).parent
        one = json.loads(self.invoke(PROPOSALS).stdout)
        self.assertEqual(one["proposals"], [])
        v1 = {
            "schema_version": 1,
            "key": "legacy-branch-email@example.invalid",
            "pr_number": 42,
            "metrics": {"ci_failures": 1, "implementation_findings": 0, "design_findings": 0, "human_decisions": 0},
            "review_cycles": 0,
        }
        (receipt_dir / "legacy.json").write_text(json.dumps(v1), encoding="utf-8")
        two = json.loads(self.invoke(PROPOSALS).stdout)
        self.assertEqual(two["versions"], {"v1": 1, "v2": 1})
        self.assertEqual(
            [item["signal"] for item in two["proposals"]], ["delivery_ci_failures"]
        )
        self.assertNotIn("legacy-branch", json.dumps(two))

    def test_start_with_run_card_bundles_card_and_run(self) -> None:
        result = self.invoke(
            TELEMETRY,
            "start",
            "--lane",
            "full",
            "--entry",
            "requirements",
            "--goal",
            "implemented",
            "--run-card",
        )
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {"run_card", "run"})
        self.assertEqual(payload["run_card"]["lane"], "full")
        self.assertEqual(payload["run_card"]["references"], ["references/full-lane.md"])
        self.assertTrue(payload["run_card"]["read_only"])
        self.assertEqual(payload["run"]["revision"], 0)
        self.revisions[payload["run"]["run_id"]] = 0
        # The bundled start is the same start: a second plain start resumes the same run.
        self.assertEqual(self.start(), payload["run"]["run_id"])

    def test_finish_warns_on_all_zero_counters_unless_forced(self) -> None:
        run_id = self.start("light")
        result = self.finish_result(run_id)
        self.assertEqual(result.returncode, 0)
        self.assertIn("all telemetry counters are 0", result.stderr)
        forced = self.start("light", "requirements", "pr_open")
        quiet = self.finish_result(forced, "blocked", "--force-empty")
        self.assertNotIn("counters are 0", quiet.stderr)
        counted = self.start("full", "requirements", "review_requested")
        self.event(counted, "designer_round", "c" * 32)
        counted_result = self.finish_result(counted, "blocked")
        self.assertNotIn("counters are 0", counted_result.stderr)

    def test_finish_bundles_promote_check_and_plan_status(self) -> None:
        plan = self.repo / "plans" / "task.md"
        plan.parent.mkdir()
        plan.write_text(
            "# Plan: task\n\n- Lane: light\n- Status: designed\n- Created: 2026-09-05\n",
            encoding="utf-8",
        )
        ledger_home = Path(self.tempdir.name) / "home"
        (ledger_home / ".local" / "state" / "draftsmith").mkdir(parents=True)
        ledger = ledger_home / ".local" / "state" / "draftsmith" / "audit-pains.jsonl"
        pain = {"ts": "2026-09-05T00:00:00Z", "repo": "r", "category": "scope-creep",
                "cause": "boundary-expansion", "target_kind": "rubric", "fp": "abcd1234abcd1234"}
        ledger.write_text((json.dumps(pain) + "\n") * 2, encoding="utf-8")
        run_id = self.start("light")
        self.event(run_id, "reviewer_round", "d" * 32)
        env = dict(os.environ, HOME=str(ledger_home))
        result = subprocess.run(
            [
                sys.executable,
                str(TELEMETRY),
                "--repo",
                str(self.repo),
                "finish",
                "--run-id",
                run_id,
                "--final-phase",
                "implemented",
                "--expect-revision",
                str(self.revisions[run_id]),
                "--promote-check",
                "--plan-file",
                str(plan),
                "--plan-status",
                "implemented",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        receipt_path, extras_line = result.stdout.splitlines()[:2]
        self.assertTrue(Path(receipt_path).is_file())
        extras = json.loads(extras_line)
        self.assertEqual(extras["plan"]["previous"], "designed")
        self.assertIn("- Status: implemented\n", plan.read_text(encoding="utf-8"))
        self.assertNotIn("- Status: designed", plan.read_text(encoding="utf-8"))
        promote = extras["promote_check"]
        if shutil.which("jq"):
            self.assertEqual(promote["status"], "ok")
            self.assertEqual(promote["proposals"], 1)
        else:
            self.assertIn(promote["status"], {"ok", "failed", "missing"})
        # Re-running the bundled finish is safe: the receipt is immutable and the plan stays.
        again = subprocess.run(
            [
                sys.executable,
                str(TELEMETRY),
                "--repo",
                str(self.repo),
                "finish",
                "--run-id",
                run_id,
                "--final-phase",
                "implemented",
                "--expect-revision",
                str(self.revisions[run_id]),
                "--plan-file",
                str(plan),
                "--plan-status",
                "implemented",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(again.stdout.splitlines()[0], receipt_path)
        missing_plan = self.finish_result(
            self.start("light", "requirements", "pr_open"),
            "blocked",
            "--plan-file",
            str(self.repo / "plans" / "missing.md"),
            "--plan-status",
            "implemented",
            check=False,
        )
        # The receipt is already immutable; the missing plan is reported as an error afterwards.
        self.assertEqual(missing_plan.returncode, 2)
        self.assertIn("plan file not found", missing_plan.stderr)

    def test_finish_projects_transcript_cost_into_receipt(self) -> None:
        transcript = Path(self.tempdir.name) / "session.jsonl"
        rows = [
            {
                "type": "assistant",
                "timestamp": "2026-09-05T00:00:00Z",
                "message": {
                    "id": "m1",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 20,
                        "cache_read_input_tokens": 30,
                        "output_tokens": 5,
                    },
                    "content": [{"type": "text", "text": "SECRET-BODY"}],
                },
            },
            {"type": "user", "timestamp": "2026-09-05T00:00:10Z", "message": {"content": "x"}},
        ]
        transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        run_id = self.start("full")
        self.event(run_id, "designer_round", "e" * 32)
        result = self.finish_result(run_id, "implemented", "--cost-from", str(transcript))
        receipt_path = Path(result.stdout.splitlines()[0])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validate_receipt(receipt)
        self.assertEqual(receipt["cost"]["roles"]["main"]["turns"], 1)
        self.assertEqual(receipt["cost"]["roles"]["main"]["avg_context_tokens"], 60)
        self.assertEqual(receipt["cost"]["roles"]["main"]["duration_seconds"], 10)
        self.assertNotIn("SECRET-BODY", receipt_path.read_text(encoding="utf-8"))
        self.assertNotIn(str(transcript), receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(result.stdout.splitlines()[1])["cost"], "projected")
        bad_role = json.loads(json.dumps(receipt))
        bad_role["cost"]["roles"]["branch-name"] = bad_role["cost"]["roles"]["main"]
        with self.assertRaises(TelemetryError):
            validate_receipt(bad_role)
        missing = self.finish_result(
            self.start("light", "requirements", "pr_open"),
            "blocked",
            "--cost-from",
            str(Path(self.tempdir.name) / "nope.jsonl"),
            check=False,
        )
        self.assertEqual(missing.returncode, 2)

    def test_receipt_proposals_rank_cost_hotspots_from_cost_blocks(self) -> None:
        def metrics(cache_read: int, turns: int, output: int) -> dict[str, int]:
            return {
                "turns": turns,
                "avg_context_tokens": 1,
                "max_context_tokens": 1,
                "output_tokens": output,
                "cache_read_tokens": cache_read,
                "cache_creation_tokens": 0,
                "duration_seconds": 1,
                "agents": 1,
            }

        # Producing cost blocks through finish --cost-from would need two real transcripts;
        # inject validated cost blocks into finished receipts instead.
        for roles in (
            {"main": metrics(100, 10, 5), "designer": metrics(300, 30, 7)},
            {"main": metrics(100, 20, 9), "auditor": metrics(150, 12, 3)},
        ):
            run_id = self.start("full", "requirements", "pr_open")
            receipt_path = self.finish(run_id, "blocked", "--force-empty")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["cost"] = {
                "schema_version": 1,
                "roles": roles,
                "total": metrics(0, 0, 0),
                "unmapped_subagents": 0,
            }
            validate_receipt(receipt)
            receipt_path.chmod(0o600)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        payload = json.loads(self.invoke(PROPOSALS).stdout)
        hotspots = payload["cost_hotspots"]
        self.assertEqual([item["role"] for item in hotspots], ["designer", "main"])
        designer, main = hotspots
        self.assertEqual(designer["evidence"]["receipt_count"], 1)
        self.assertEqual(designer["evidence"]["cache_read_tokens_total"], 300)
        self.assertEqual(main["evidence"]["receipt_count"], 2)
        self.assertEqual(main["evidence"]["cache_read_tokens_total"], 200)
        self.assertEqual(main["evidence"]["turns_mean"], 15)
        self.assertEqual(main["evidence"]["output_tokens_mean"], 7)
        self.assertNotIn("auditor", json.dumps(hotspots))
        self.assertEqual(payload["proposals"], [])

    def test_delivery_metric_api_prevents_finding_double_count(self) -> None:
        self.invoke(STATE, "init", "--goal", "implemented")
        rejected = self.invoke(
            STATE,
            "record-event",
            "--expect-revision",
            "0",
            "--event",
            "implementation_finding",
            check=False,
        )
        self.assertEqual(rejected.returncode, 2)
        state = json.loads(self.invoke(STATE, "show").stdout)
        self.assertEqual(state["metrics"]["implementation_findings"], 0)

    def test_delivery_metrics_are_projected_into_v2_receipt_once(self) -> None:
        self.invoke(
            STATE,
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
        self.invoke(
            STATE,
            "record-event",
            "--expect-revision",
            "0",
            "--event",
            "ci_failure",
        )
        self.invoke(
            STATE,
            "record-review",
            "--expect-revision",
            "1",
            "--fingerprint",
            "f" * 64,
            "--disposition",
            "implementation",
        )
        self.invoke(STATE, "update", "--expect-revision", "2", "--increment-review-cycles")
        run_id = self.start("full", "delivery", "review_complete")
        key = Path(self.invoke(STATE, "path").stdout.strip()).stem
        receipt = json.loads(
            self.finish(run_id, "review_complete", "--delivery-key", key).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(receipt["delivery_counters"]["ci_failures"], 1)
        self.assertEqual(receipt["delivery_counters"]["implementation_findings"], 1)
        self.assertEqual(receipt["delivery_counters"]["reviewer_rounds"], 1)


if __name__ == "__main__":
    unittest.main()
