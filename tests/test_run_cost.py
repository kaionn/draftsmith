from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "draftsmith" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from run_cost import CostError, collect

COST = SCRIPTS / "run_cost.py"
SECRET = "SECRET-PROMPT-BODY"
SECRET_PATH = "/private/secret-workspace/app/models/customer.rb"


def usage(inp: int, creation: int, read: int, out: int) -> dict[str, int]:
    return {
        "input_tokens": inp,
        "cache_creation_input_tokens": creation,
        "cache_read_input_tokens": read,
        "output_tokens": out,
    }


def assistant(
    message_id: str,
    timestamp: str,
    tokens: dict[str, int],
    content: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "id": message_id,
            "model": "claude-test",
            "usage": tokens,
            "content": content if content is not None else [{"type": "text", "text": SECRET}],
        },
    }


def agent_launch(
    message_id: str, timestamp: str, tool_use_id: str, subagent_type: str
) -> dict[str, Any]:
    block = {
        "type": "tool_use",
        "name": "Agent",
        "id": tool_use_id,
        "input": {
            "subagent_type": subagent_type,
            "prompt": f"{SECRET} at {SECRET_PATH}",
            "description": SECRET,
        },
    }
    return assistant(message_id, timestamp, usage(100, 0, 900, 20), [block])


def tool_result(timestamp: str, tool_use_id: str, agent_id: str) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": timestamp,
        "toolUseResult": {"agentId": agent_id, "content": SECRET},
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": SECRET}
            ]
        },
    }


def sidechain(
    message_id: str, timestamp: str, agent_id: str, tokens: dict[str, int]
) -> dict[str, Any]:
    record = assistant(message_id, timestamp, tokens)
    record["isSidechain"] = True
    record["agentId"] = agent_id
    return record


def write_jsonl(path: Path, records: list[dict[str, Any]], *, corrupt: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record) for record in records]
    if corrupt:
        lines.insert(1, "{not json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class RunCostTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-cost-test-")
        root = Path(self.tempdir.name)
        self.transcript = root / "session.jsonl"
        subagents = root / "session" / "subagents"
        # main: 3 message ids, one of them split across 3 streaming chunks (usage grows).
        write_jsonl(
            self.transcript,
            [
                assistant("msg_a", "2026-09-05T00:00:00.000Z", usage(1000, 0, 0, 10)),
                assistant("msg_a", "2026-09-05T00:00:02.000Z", usage(1000, 0, 0, 50)),
                assistant("msg_a", "2026-09-05T00:00:05.000Z", usage(1000, 0, 0, 120)),
                agent_launch("msg_b", "2026-09-05T00:00:10.000Z", "toolu_1", "draftsmith:designer"),
                tool_result("2026-09-05T00:00:20.000Z", "toolu_1", "aaa1"),
                agent_launch(
                    "msg_c", "2026-09-05T00:00:30.000Z", "toolu_2", "draftsmith:reviewer-light"
                ),
                tool_result("2026-09-05T00:01:40.000Z", "toolu_2", "bbb2"),
            ],
            corrupt=True,
        )
        write_jsonl(
            subagents / "agent-aaa1.jsonl",
            [
                sidechain("d1", "2026-09-05T00:00:11.000Z", "aaa1", usage(2000, 500, 100, 300)),
                sidechain("d2", "2026-09-05T00:00:19.000Z", "aaa1", usage(3000, 0, 1000, 400)),
            ],
        )
        write_jsonl(
            subagents / "agent-bbb2.jsonl",
            [sidechain("r1", "2026-09-05T00:00:35.000Z", "bbb2", usage(500, 0, 500, 60))],
        )
        write_jsonl(
            subagents / "agent-ccc3.jsonl",
            [sidechain("o1", "2026-09-05T00:02:00.000Z", "ccc3", usage(700, 0, 300, 90))],
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_streaming_chunks_fold_into_one_turn(self) -> None:
        report = collect(self.transcript)
        main = report["roles"]["main"]
        self.assertEqual(main["turns"], 3)
        # msg_a output max 120, plus two Agent launch turns of 20 each.
        self.assertEqual(main["output_tokens"], 160)
        self.assertEqual(main["max_context_tokens"], 1000)
        self.assertEqual(main["avg_context_tokens"], 1000)
        self.assertEqual(main["cache_read_tokens"], 1800)
        self.assertEqual(main["cache_creation_tokens"], 0)
        self.assertEqual(main["duration_seconds"], 100)
        self.assertEqual(main["agents"], 1)

    def test_roles_are_mapped_through_tool_use_join(self) -> None:
        report = collect(self.transcript)
        self.assertEqual(
            sorted(report["roles"]), ["designer", "main", "other", "reviewer-light"]
        )
        designer = report["roles"]["designer"]
        self.assertEqual(designer["turns"], 2)
        self.assertEqual(designer["max_context_tokens"], 4000)
        self.assertEqual(designer["avg_context_tokens"], 3300)
        self.assertEqual(designer["output_tokens"], 700)
        self.assertEqual(designer["cache_creation_tokens"], 500)
        self.assertEqual(designer["duration_seconds"], 8)
        self.assertEqual(designer["agents"], 1)
        reviewer = report["roles"]["reviewer-light"]
        self.assertEqual(reviewer["turns"], 1)
        self.assertEqual(reviewer["max_context_tokens"], 1000)
        self.assertEqual(reviewer["duration_seconds"], 0)

    def test_unmapped_subagent_falls_back_to_other(self) -> None:
        report = collect(self.transcript)
        self.assertEqual(report["unmapped_subagents"], 1)
        other = report["roles"]["other"]
        self.assertEqual(other["turns"], 1)
        self.assertEqual(other["max_context_tokens"], 1000)
        self.assertEqual(other["output_tokens"], 90)
        self.assertEqual(other["agents"], 1)

    def test_meta_json_resolves_role_without_tool_use_join(self) -> None:
        meta = self.transcript.with_suffix("") / "subagents" / "agent-ccc3.meta.json"
        meta.write_text(
            json.dumps({"agentType": "draftsmith:implementer", "toolUseId": "toolu_9"}),
            encoding="utf-8",
        )
        report = collect(self.transcript)
        self.assertEqual(report["unmapped_subagents"], 0)
        self.assertIn("implementer", report["roles"])
        self.assertNotIn("other", report["roles"])

    def test_totals_and_schema(self) -> None:
        report = collect(self.transcript)
        self.assertEqual(report["schema_version"], 1)
        total = report["total"]
        self.assertEqual(total["turns"], 7)
        self.assertEqual(total["output_tokens"], 160 + 700 + 60 + 90)
        self.assertEqual(total["max_context_tokens"], 4000)
        self.assertEqual(total["agents"], 3)

    def test_main_only_transcript_without_subagents(self) -> None:
        solo = Path(self.tempdir.name) / "solo.jsonl"
        write_jsonl(
            solo,
            [
                assistant("s1", "2026-09-05T00:00:00.000Z", usage(10, 0, 0, 1)),
                {"type": "assistant", "message": {"id": "s2", "content": []}},
            ],
        )
        report = collect(solo)
        self.assertEqual(list(report["roles"]), ["main"])
        self.assertEqual(report["roles"]["main"]["turns"], 1)
        self.assertEqual(report["unmapped_subagents"], 0)

    def test_json_output_leaks_no_prompt_body_or_paths(self) -> None:
        result = subprocess.run(
            [sys.executable, str(COST), "--transcript", str(self.transcript), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout)
        self.assertNotIn(SECRET_PATH, result.stdout)
        self.assertNotIn(str(self.transcript), result.stdout)
        self.assertNotIn("aaa1", result.stdout)
        self.assertNotIn("toolu_", result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], 1)

    def test_table_output_leaks_nothing(self) -> None:
        result = subprocess.run(
            [sys.executable, str(COST), "--transcript", str(self.transcript)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout)
        self.assertNotIn(SECRET_PATH, result.stdout)
        self.assertIn("designer", result.stdout)

    def test_missing_transcript_exits_two(self) -> None:
        missing = Path(self.tempdir.name) / "absent.jsonl"
        result = subprocess.run(
            [sys.executable, str(COST), "--transcript", str(missing)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("error:", result.stderr)
        with self.assertRaises(CostError):
            collect(missing)


if __name__ == "__main__":
    unittest.main()
