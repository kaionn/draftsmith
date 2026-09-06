from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INSPECT = ROOT / "skills" / "draftsmith" / "scripts" / "run_inspect.py"

COUNTER_KEYS = (
    "designer_rounds",
    "auditor_rounds",
    "reviewer_rounds",
    "light_to_full",
    "audit_traceability_miss",
    "audit_adr_unjustified",
    "audit_prediction_divergence",
    "audit_anchor_mismatch",
    "audit_scope_creep",
    "audit_requirement_misread",
    "test_failures",
    "ci_failures",
    "implementation_findings",
    "design_findings",
    "human_decisions",
)
DELIVERY_KEYS = (
    "ci_failures",
    "implementation_findings",
    "design_findings",
    "human_decisions",
    "reviewer_rounds",
)


def cost_metrics(cache_read: int, output: int, turns: int) -> dict[str, int]:
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


class ReceiptSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-summary-test-")
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

    def summary(self) -> dict[str, Any]:
        result = subprocess.run(
            [sys.executable, str(INSPECT), "--repo", str(self.repo), "summary"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_raw(self, name: str, text: str) -> None:
        (self.receipts / name).write_text(text, encoding="utf-8")

    def write_v2(
        self,
        number: int,
        *,
        lane: str = "full",
        goal: str = "implemented",
        final_phase: str = "implemented",
        cost: dict[str, dict[str, int]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 2,
            "run_id": f"{number:032x}",
            "lane": lane,
            "entry": "requirements",
            "goal": goal,
            "final_phase": final_phase,
            "counters": {key: 0 for key in COUNTER_KEYS},
            "delivery_counters": {key: 0 for key in DELIVERY_KEYS},
            "duration_seconds": 1,
            "started_at": "2026-09-01T00:00:00Z",
            "finished_at": "2026-09-01T00:00:01Z",
        }
        if cost is not None:
            payload["cost"] = {
                "schema_version": 1,
                "roles": cost,
                "total": cost_metrics(0, 0, 0),
                "unmapped_subagents": 0,
            }
        self.write_raw(f"{number:032x}.json", json.dumps(payload))
        return payload

    def test_summary_aggregates_lane_goal_phase_and_role_tokens(self) -> None:
        self.write_v2(
            1,
            cost={"main": cost_metrics(100, 5, 10), "designer": cost_metrics(300, 7, 30)},
        )
        self.write_v2(
            2,
            lane="light",
            goal="pr_open",
            final_phase="pr_open",
            cost={"main": cost_metrics(50, 3, 4)},
        )
        self.write_v2(3, lane="light", goal="pr_open", final_phase="blocked")
        payload = self.summary()
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["receipts_read"], 3)
        self.assertEqual(payload["skipped"], 0)
        self.assertEqual(payload["versions"], {"v1": 0, "v2": 3})
        self.assertEqual(payload["lanes"], {"full": 1, "light": 2})
        self.assertEqual(payload["goals"], {"implemented": 1, "pr_open": 2})
        self.assertEqual(
            payload["final_phases"], {"implemented": 1, "pr_open": 1, "blocked": 1}
        )
        self.assertEqual(payload["cost"]["receipts_with_cost"], 2)
        self.assertEqual(
            payload["cost"]["roles"]["main"],
            {
                "receipt_count": 2,
                "turns": 14,
                "output_tokens": 8,
                "cache_read_tokens": 150,
                "cache_creation_tokens": 0,
            },
        )
        self.assertEqual(payload["cost"]["roles"]["designer"]["cache_read_tokens"], 300)

    def test_v1_and_v2_receipts_are_both_summarized(self) -> None:
        self.write_v2(1)
        self.write_raw(
            "legacy.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "key": "legacy-branch-email@example.invalid",
                    "pr_number": 42,
                    "metrics": {
                        "ci_failures": 1,
                        "implementation_findings": 0,
                        "design_findings": 0,
                        "human_decisions": 0,
                    },
                    "review_cycles": 0,
                }
            ),
        )
        payload = self.summary()
        self.assertEqual(payload["versions"], {"v1": 1, "v2": 1})
        self.assertEqual(payload["receipts_read"], 2)
        self.assertEqual(payload["skipped"], 0)
        self.assertEqual(payload["lanes"], {"full": 1, "unknown": 1})
        self.assertEqual(payload["goals"], {"implemented": 1, "unknown": 1})
        self.assertEqual(payload["final_phases"], {"implemented": 1, "unknown": 1})
        self.assertNotIn("legacy-branch", json.dumps(payload))

    def test_broken_receipts_are_skipped_and_counted(self) -> None:
        good = self.write_v2(1)

        # 1. JSON that cannot be read at all.
        self.write_raw("not-json.json", "{oops")

        # 2. JSON but not a dict, or schema_version has an unknown value or type.
        self.write_raw("not-object.json", json.dumps([1, 2, 3]))
        self.write_raw("unknown-version.json", json.dumps({"schema_version": 99}))
        self.write_raw("float-version.json", json.dumps({"schema_version": 1.0}))
        self.write_raw("bool-version.json", json.dumps({"schema_version": True}))

        # 3. v2 but violates an enum (validate_receipt raises TelemetryError).
        invalid_enum = dict(good)
        invalid_enum["lane"] = "sideways"
        self.write_raw("invalid-v2-enum.json", json.dumps(invalid_enum))

        # 4. v2 but a malformed timestamp (validate_receipt raises StateError).
        invalid_timestamp = dict(good)
        invalid_timestamp["started_at"] = "nope"
        self.write_raw("invalid-v2-timestamp.json", json.dumps(invalid_timestamp))

        payload = self.summary()
        self.assertEqual(payload["receipts_read"], 1)
        self.assertEqual(payload["skipped"], 7)
        self.assertEqual(payload["versions"], {"v1": 0, "v2": 1})
        self.assertEqual(payload["lanes"], {"full": 1})


if __name__ == "__main__":
    unittest.main()
