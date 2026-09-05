from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "draftsmith" / "scripts" / "check_reply_contract.py"

REQUIREMENTS = """# 要件書: sample

## 6. 受け入れ基準

- AC-1: first
- AC-2: second
- AC-3: third
"""


def valid_return(digest: str, *, rows: tuple[str, ...] = ("AC-1", "AC-2", "AC-3")) -> str:
    table = "\n".join(f"| {ac} | brief 指示 {ac} |" for ac in rows)
    return f"""<!-- requirements-sha256: {digest} -->
## 要素 1: 実装 brief

### 構造ビジュアル

tree

### 調査済みファイル

- src/a.py — 関数 foo の定義（src/a.py:10）

## 要素 2: 確認事項リスト

なし

## 要素 3: 前提崩れ・要件矛盾の報告

なし

## 要素 4: トレーサビリティ表

| 受け入れ基準 | 対応する brief 要素 |
|---|---|
{table}

## 要素 5: mini-ADR

なし
"""


class CheckReplyContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="draftsmith-reply-contract-")
        self.dir = Path(self.tempdir.name)
        self.requirements = self.dir / "requirements.md"
        self.requirements.write_text(REQUIREMENTS, encoding="utf-8")
        self.digest = hashlib.sha256(self.requirements.read_bytes()).hexdigest()
        self.designer_return = self.dir / "designer-return.md"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_check(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(self.designer_return),
                "--requirements",
                str(self.requirements),
                *extra,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_valid_return_passes(self) -> None:
        self.designer_return.write_text(valid_return(self.digest), encoding="utf-8")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ok", result.stdout)

    def test_missing_element_fails(self) -> None:
        text = valid_return(self.digest).replace("## 要素 3: 前提崩れ・要件矛盾の報告\n\nなし\n", "")
        self.designer_return.write_text(text, encoding="utf-8")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("要素 3", result.stdout)

    def test_missing_ac_fails(self) -> None:
        self.designer_return.write_text(
            valid_return(self.digest, rows=("AC-1", "AC-3")), encoding="utf-8"
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("AC-2", result.stdout)

    def test_duplicated_ac_fails(self) -> None:
        self.designer_return.write_text(
            valid_return(self.digest, rows=("AC-1", "AC-2", "AC-2", "AC-3")), encoding="utf-8"
        )
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("重複", result.stdout)

    def test_digest_mismatch_fails(self) -> None:
        self.designer_return.write_text(valid_return("0" * 64), encoding="utf-8")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("requirements-sha256", result.stdout)

    def test_missing_surveyed_files_fails_unless_light(self) -> None:
        text = valid_return(self.digest).replace(
            "### 調査済みファイル\n\n- src/a.py — 関数 foo の定義（src/a.py:10）\n", ""
        )
        self.designer_return.write_text(text, encoding="utf-8")
        strict = self.run_check()
        self.assertEqual(strict.returncode, 1)
        self.assertIn("調査済みファイル", strict.stdout)
        light = self.run_check("--light")
        self.assertEqual(light.returncode, 0, light.stdout + light.stderr)

    def test_missing_file_is_usage_error(self) -> None:
        result = self.run_check()
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
