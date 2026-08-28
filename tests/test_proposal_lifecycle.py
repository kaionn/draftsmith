from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "draftsmith" / "scripts" / "proposal_lifecycle.py"


class ProposalLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-proposal-test-")
        self.repo = Path(self.tempdir.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("commit", "--allow-empty", "-q", "-m", "init")
        self.receipts = self.repo / ".git" / "draftsmith-delivery-receipts"
        self.receipts.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def write_receipt(self, number: int, test_failures: int) -> None:
        counters = {
            "designer_rounds": 0,
            "auditor_rounds": 0,
            "reviewer_rounds": 0,
            "light_to_full": 0,
            "audit_traceability_miss": 0,
            "audit_adr_unjustified": 0,
            "audit_prediction_divergence": 0,
            "audit_anchor_mismatch": 0,
            "audit_scope_creep": 0,
            "audit_requirement_misread": 0,
            "test_failures": test_failures,
            "ci_failures": 0,
            "implementation_findings": 0,
            "design_findings": 0,
            "human_decisions": 0,
        }
        delivery = {
            "ci_failures": 0,
            "implementation_findings": 0,
            "design_findings": 0,
            "human_decisions": 0,
            "reviewer_rounds": 0,
        }
        payload = {
            "schema_version": 2,
            "run_id": f"{number:032x}",
            "lane": "full",
            "entry": "requirements",
            "goal": "implemented",
            "final_phase": "implemented",
            "counters": counters,
            "delivery_counters": delivery,
            "duration_seconds": 1,
            "started_at": "2026-08-28T00:00:00Z",
            "finished_at": "2026-08-28T00:00:01Z",
        }
        (self.receipts / f"{number:032x}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def prepare_accepted(self) -> tuple[Path, dict[str, object]]:
        self.write_receipt(1, 1)
        self.write_receipt(2, 1)
        paths = json.loads(self.invoke("sync").stdout)
        proposal_path = Path(paths[0])
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        self.invoke(
            "decide",
            "--proposal-id",
            proposal["proposal_id"],
            "--decision",
            "accepted",
            "--expect-revision",
            "0",
        )
        return proposal_path, json.loads(proposal_path.read_text(encoding="utf-8"))

    def test_five_clean_runs_mark_an_accepted_proposal_improved(self) -> None:
        path, proposal = self.prepare_accepted()
        for number in range(3, 8):
            self.write_receipt(number, 0)
        self.invoke(
            "evaluate",
            "--proposal-id",
            proposal["proposal_id"],
            "--expect-revision",
            str(proposal["revision"]),
        )
        evaluated = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(evaluated["evaluation"]["outcome"], "improved")
        self.assertFalse(evaluated["evaluation"]["withdraw_candidate"])

    def test_five_repeating_runs_mark_withdraw_candidate(self) -> None:
        path, proposal = self.prepare_accepted()
        for number in range(3, 8):
            self.write_receipt(number, 1)
        self.invoke(
            "evaluate",
            "--proposal-id",
            proposal["proposal_id"],
            "--expect-revision",
            str(proposal["revision"]),
        )
        evaluated = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(evaluated["evaluation"]["outcome"], "no_improvement")
        self.assertTrue(evaluated["evaluation"]["withdraw_candidate"])


if __name__ == "__main__":
    unittest.main()
