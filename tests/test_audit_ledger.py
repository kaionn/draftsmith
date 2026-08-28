from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit-ledger.sh"


class AuditLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-audit-test-")
        self.home = Path(self.tempdir.name)
        self.env = {**os.environ, "HOME": str(self.home)}

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def invoke(self, *args: str) -> None:
        subprocess.run(["bash", str(SCRIPT), *args], check=True, env=self.env, capture_output=True, text=True)

    def test_two_structured_occurrences_create_proposal_not_constitution(self) -> None:
        state = self.home / ".local" / "state" / "draftsmith"
        self.invoke("record", "scope-creep", "boundary-expansion", "rubric", "repo-a")
        self.invoke("promote-check")
        proposals = state / "improvement-proposals"
        self.assertEqual(list(proposals.glob("*.json")) if proposals.exists() else [], [])
        self.invoke("record", "scope-creep", "boundary-expansion", "rubric", "repo-b")
        self.invoke("promote-check")
        files = list(proposals.glob("*.json"))
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["evidence"]["occurrences"], 2)
        self.assertEqual(payload["target"], "rubric")
        self.assertIn("falsification", payload)
        self.assertFalse((state / "constitution.md").exists())

    def test_fingerprint_includes_cause_and_target(self) -> None:
        state = self.home / ".local" / "state" / "draftsmith"
        self.invoke("record", "scope-creep", "boundary-expansion", "rubric", "repo")
        self.invoke("record", "scope-creep", "verification-gap", "rubric", "repo")
        self.invoke("record", "scope-creep", "boundary-expansion", "test", "repo")
        rows = [json.loads(line) for line in (state / "audit-pains.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len({row["fp"] for row in rows}), 3)

    def test_symlinked_state_directory_is_rejected(self) -> None:
        state_parent = self.home / ".local" / "state"
        state_parent.mkdir(parents=True)
        outside = self.home / "outside"
        outside.mkdir()
        (state_parent / "draftsmith").symlink_to(outside, target_is_directory=True)
        self.invoke("record", "scope-creep", "boundary-expansion", "rubric", "repo")
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
