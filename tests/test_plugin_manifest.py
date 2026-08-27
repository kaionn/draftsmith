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
            "マージまで進めて",
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


if __name__ == "__main__":
    unittest.main()
