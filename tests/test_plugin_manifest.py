from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginManifestTest(unittest.TestCase):
    def test_plugin_and_marketplace_metadata_are_consistent(self) -> None:
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        entry = marketplace["plugins"][0]

        self.assertEqual(plugin["name"], "draftsmith")
        self.assertEqual(entry["name"], plugin["name"])
        self.assertEqual(entry["version"], plugin["version"])
        self.assertEqual(marketplace["metadata"]["version"], plugin["version"])
        self.assertEqual(entry["source"], "./")
        self.assertIn("./skills/", plugin["skills"])
        self.assertIn("./skills/adapters/", plugin["skills"])
        self.assertEqual(plugin["hooks"], "./hooks/draftsmith-hooks.json")

    def test_plugin_hooks_are_declared_and_resolvable(self) -> None:
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        hooks_path = ROOT / plugin["hooks"].lstrip("./")
        self.assertTrue(hooks_path.is_file())
        # The default auto-discovery location stays empty so the manifest reference is the only
        # registration, under either reading of the docs ("default is additive" / "replaces").
        self.assertFalse((ROOT / "hooks" / "hooks.json").exists())

        config = json.loads(hooks_path.read_text(encoding="utf-8"))
        self.assertEqual(set(config), {"hooks"})
        self.assertEqual(set(config["hooks"]), {"SessionStart", "Stop"})

        session_start = config["hooks"]["SessionStart"]
        self.assertEqual([group["matcher"] for group in session_start], ["startup|resume|clear|fork"])
        for group in config["hooks"]["Stop"]:
            self.assertNotIn("matcher", group)

        commands = []
        for event in ("SessionStart", "Stop"):
            for group in config["hooks"][event]:
                self.assertTrue(group["hooks"], f"{event} declares no hook command")
                for hook in group["hooks"]:
                    self.assertEqual(hook["type"], "command")
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", hook["command"])
                    # The default command timeout is 600s, which a hung git call would burn in
                    # full; an explicit short timeout is the only thing that bounds it.
                    self.assertIsInstance(hook["timeout"], int)
                    self.assertGreater(hook["timeout"], 0)
                    self.assertLessEqual(hook["timeout"], 10)
                    commands.append(hook["command"])

        relative = [command.split('"')[-1].lstrip("/") for command in commands]
        self.assertEqual(
            sorted(relative),
            ["hooks/session-start-resume-brief.sh", "hooks/stop-park-reminder.sh"],
        )
        for name in relative:
            self.assertTrue((ROOT / name).is_file(), f"{name} is declared but missing")

    def test_skill_frontmatter_keeps_required_discovery_fields(self) -> None:
        text = (ROOT / "skills" / "draftsmith" / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("---", 2)[1]
        self.assertIn("\nname: draftsmith\n", f"\n{frontmatter}\n")
        self.assertIn("\ndescription: ", f"\n{frontmatter}\n")
        self.assertIn("\nuser-invocable: true\n", f"\n{frontmatter}\n")
        self.assertNotIn("disable-model-invocation: true", frontmatter)

        for phrase in (
            "設計から実装して",
            "今の差分をPRにして",
            "このPRのCI・レビュー対応を続けて",
            "コメント対応して",
            "レビュー待ちにして",
            "マージまで進めて",
            "entry=requirements",
            "goal=implemented",
            "entry=delivery",
            "goal=review_complete",
            "PR作成=pr_open",
            "レビュー依頼=review_requested",
            "merge-ready=merge_ready",
            "マージ=merged",
        ):
            self.assertIn(phrase, frontmatter)

    def test_codex_allows_implicit_draftsmith_invocation(self) -> None:
        policy = (
            ROOT / "skills" / "draftsmith" / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            policy,
            "policy:\n  allow_implicit_invocation: true\n",
        )

    def test_root_skill_keeps_shared_safety_contracts_and_progressive_routes(self) -> None:
        text = (ROOT / "skills" / "draftsmith" / "SKILL.md").read_text(encoding="utf-8")
        for marker in (
            "## Routing contract",
            "## Human gates",
            "## Untrusted input",
            "## Lane selection and escalation",
            "consultant",
            "delivery_state.py",
            "references/full-lane.md",
            "references/light-lane.md",
            "references/artifacts.md",
            "references/delivery-loop.md",
        ):
            self.assertIn(marker, text)
        for reference in ("full-lane.md", "light-lane.md", "artifacts.md", "delivery-loop.md"):
            self.assertTrue((ROOT / "skills" / "draftsmith" / "references" / reference).is_file())

    def test_ux_adapter_skills_are_discoverable(self) -> None:
        for name in ("draftsmith-inspect", "draftsmith-review-cockpit"):
            path = ROOT / "skills" / "adapters" / name / "SKILL.md"
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            frontmatter = text.split("---", 2)[1]
            self.assertIn(f"\nname: {name}\n", f"\n{frontmatter}\n")
            self.assertIn("\nuser-invocable: true\n", f"\n{frontmatter}\n")


if __name__ == "__main__":
    unittest.main()
