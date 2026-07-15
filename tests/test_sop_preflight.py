from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "workflows" / "sop-preflight.py"
SPEC = importlib.util.spec_from_file_location("sop_preflight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sop_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sop_preflight)


class SopPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in sop_preflight.REQUIRED_MATERIALS.values():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {relative}\nverified\n", encoding="utf-8")
        self.spec = self.root / "task-spec.md"
        self.spec.write_text(
            "# Task\nUpdate the governance script.\n", encoding="utf-8"
        )
        self.knowledge = self.root / "SAGE_KNOWLEDGE.md"
        self.knowledge.write_text("# Shared knowledge\nimmutable\n", encoding="utf-8")
        self.codegraph = {
            "passed": True,
            "action": "sync",
            "files": 10,
            "nodes": 20,
            "edges": 30,
        }

    def tearDown(self):
        self.temp.cleanup()

    def build(self, **overrides):
        values = {
            "sage_root": self.root,
            "task": "governance-audit",
            "spec": self.spec,
            "knowledge": self.knowledge,
            "reviewers": 3,
            "stitch_design": None,
        }
        values.update(overrides)
        with (
            mock.patch.object(
                sop_preflight, "_git_root", return_value=self.root.resolve()
            ),
            mock.patch.object(sop_preflight, "_git_head", return_value="b" * 40),
            mock.patch.object(
                sop_preflight, "refresh_codegraph", return_value=self.codegraph
            ),
        ):
            return sop_preflight.build_bundle(**values)

    def test_valid_bundle_embeds_content_hashes_source_head_and_safety_state(self):
        bundle = self.build()
        self.assertEqual(bundle["schemaVersion"], 2)
        self.assertEqual(bundle["generatedBy"], "sop-preflight.py/v2")
        self.assertEqual(bundle["sourceHead"], "b" * 40)
        self.assertEqual(bundle["codegraph"]["status"], "current")
        self.assertIn("immutable", bundle["materials"]["knowledge"]["content"])
        self.assertRegex(bundle["materials"]["spec"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(bundle["r5_human_verification"], "pending")
        self.assertFalse(bundle["merge_authorized"])

    def test_malformed_source_head_is_rejected(self):
        completed = mock.Mock(returncode=0, stdout="not-a-commit\n")
        with (
            mock.patch.object(sop_preflight.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(SystemExit, "source HEAD"),
        ):
            sop_preflight._git_head(self.root)

    def test_missing_or_symlinked_spec_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "regular file"):
            self.build(spec=self.root / "missing.md")
        link = self.root / "linked-spec.md"
        link.symlink_to(self.spec)
        with self.assertRaisesRegex(SystemExit, "regular file"):
            self.build(spec=link)

    def test_invalid_reviewer_count_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "2 through 4"):
            self.build(reviewers=1)

    def test_ui_task_requires_locked_stitch_design(self):
        self.spec.write_text("# Task\nBuild a WPF UI dashboard.\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "--stitch-design"):
            self.build()
        design = self.root / "STITCH_DESIGN.md"
        design.write_text("# Locked Stitch export\n", encoding="utf-8")
        bundle = self.build(stitch_design=design)
        self.assertTrue(bundle["stitchRequired"])
        self.assertIn("stitchDesign", bundle["materials"])


if __name__ == "__main__":
    unittest.main()
