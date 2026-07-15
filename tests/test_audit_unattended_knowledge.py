from __future__ import annotations

import json
import unittest
from unittest import mock

from tools import audit_unattended_knowledge
from workflow.knowledge import task_requires_stitch


class AuditVersionConsistencyTests(unittest.TestCase):
    def test_governance_objective_is_not_misclassified_as_ui_implementation(self):
        self.assertFalse(
            task_requires_stitch(
                audit_unattended_knowledge.AUDIT_TASK_NAME,
                audit_unattended_knowledge.audit_task_spec(),
            )
        )
        self.assertIn(
            "docs/unattended-knowledge-objective.md",
            audit_unattended_knowledge.audit_task_spec(),
        )

    @staticmethod
    def result(version: str) -> dict[str, object]:
        return {
            "command": ["python3", "tools/check_version_record.py"],
            "exit_code": 0,
            "duration_seconds": 0,
            "output": json.dumps({"passed": True, "current_version": version}),
        }

    def test_transient_stale_version_is_retried_and_must_match(self):
        with mock.patch.object(
            audit_unattended_knowledge,
            "run",
            side_effect=[self.result("0.1.23"), self.result("0.1.24")],
        ):
            checked = audit_unattended_knowledge.version_record_check("0.1.24")
        self.assertEqual(checked["exit_code"], 0)
        self.assertEqual(checked["reported_current_version"], "0.1.24")
        self.assertEqual(checked["attempts"], 2)

    def test_persistent_version_mismatch_is_a_failed_gate(self):
        with mock.patch.object(
            audit_unattended_knowledge,
            "run",
            return_value=self.result("0.1.23"),
        ):
            checked = audit_unattended_knowledge.version_record_check("0.1.24")
        self.assertEqual(checked["exit_code"], 1)
        self.assertEqual(checked["underlying_exit_code"], 0)
        self.assertIn("version record mismatch", checked["output"])


if __name__ == "__main__":
    unittest.main()
