from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "claude-stop-hook.py"
LOCK = ROOT / "scripts" / "acceptance-lock.sh"


class ClaudeStopHookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.temp.name)
        self.acceptance = self.cwd / "acceptance.txt"
        self.acceptance.write_text("true\n", encoding="utf-8")
        subprocess.run(
            ["bash", str(LOCK), "lock", "acceptance.txt"],
            cwd=self.cwd,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        self.environment = {
            **os.environ,
            "SAGE_ROOT": str(ROOT),
            "SAGE_ACCEPTANCE_FILE": "acceptance.txt",
        }

    def tearDown(self):
        self.temp.cleanup()

    def run_hook(
        self,
        payload: object | str,
        *,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        input_text = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            ["python3", str(HOOK)],
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment or self.environment,
            check=False,
        )

    def payload(self, *, active: bool) -> dict[str, object]:
        return {
            "hook_event_name": "Stop",
            "stop_hook_active": active,
            "cwd": str(self.cwd),
            "session_id": "test",
        }

    def test_clean_acceptance_allows_stop(self):
        result = self.run_hook(self.payload(active=False))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_first_failure_blocks_stop_with_stderr_feedback(self):
        self.acceptance.write_text("false\n", encoding="utf-8")
        result = self.run_hook(self.payload(active=False))
        self.assertEqual(result.returncode, 2)
        self.assertIn("TAMPERED", result.stderr)
        self.assertIn("R5 remains pending", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_recursive_failure_stops_for_human_instead_of_looping(self):
        self.acceptance.write_text("false\n", encoding="utf-8")
        result = self.run_hook(self.payload(active=True))
        self.assertEqual(result.returncode, 0)
        value = json.loads(result.stdout)
        self.assertIs(value["continue"], False)
        self.assertIn("infinite loop", value["stopReason"])
        self.assertEqual(value["r5_human_verification"], "pending")
        self.assertFalse(value["merge_authorized"])

    def test_recursive_clean_state_allows_stop(self):
        result = self.run_hook(self.payload(active=True))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_malformed_or_incomplete_input_escalates_without_retry(self):
        for payload in ("not-json", {"hook_event_name": "Stop", "cwd": str(self.cwd)}):
            with self.subTest(payload=payload):
                result = self.run_hook(payload)
                self.assertEqual(result.returncode, 0)
                value = json.loads(result.stdout)
                self.assertIs(value["continue"], False)
                self.assertEqual(value["r5_human_verification"], "pending")

    def test_deeply_nested_json_escalates_instead_of_crashing_nonblocking(self):
        nested = '{"x":' + "[" * 2000 + "0" + "]" * 2000 + "}"
        result = self.run_hook(nested)
        self.assertEqual(result.returncode, 0)
        value = json.loads(result.stdout)
        self.assertIs(value["continue"], False)
        self.assertEqual(value["r5_human_verification"], "pending")
        self.assertFalse(value["merge_authorized"])
        self.assertEqual(result.stderr, "")

    def test_embedded_null_cwd_escalates_instead_of_crashing_nonblocking(self):
        payload = self.payload(active=False)
        payload["cwd"] = "\0"
        result = self.run_hook(payload)
        self.assertEqual(result.returncode, 0)
        value = json.loads(result.stdout)
        self.assertIs(value["continue"], False)
        self.assertIn("unsafe", value["stopReason"])
        self.assertEqual(result.stderr, "")

    def test_os_error_while_resolving_sage_root_escalates_for_human(self):
        environment = {
            **self.environment,
            "SAGE_ROOT": "/" + "x" * 5000,
        }
        result = self.run_hook(self.payload(active=False), environment=environment)
        self.assertEqual(result.returncode, 0)
        value = json.loads(result.stdout)
        self.assertIs(value["continue"], False)
        self.assertIn("SAGE_ROOT", value["stopReason"])


if __name__ == "__main__":
    unittest.main()
