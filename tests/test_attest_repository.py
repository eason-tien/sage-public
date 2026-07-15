from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools import attest_repository
from tools.merge_pr import validate_automated_evidence


class RepositoryAttestationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.name", "Attestation Test")
        self._git("config", "user.email", "attestation-test@example.invalid")
        (self.repo / "removed.txt").write_text("delete me\n", encoding="utf-8")
        self._git("add", "removed.txt")
        self._git("commit", "-qm", "baseline")
        self.base = self._git_output("rev-parse", "HEAD")
        (self.repo / "removed.txt").unlink()
        self._git("add", "-u")
        self._git("commit", "-qm", "delete tracked file")
        self.run_dir = self.root / "attestation"
        self.signing_key = self.root / "evidence-key"
        subprocess.run(
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-f",
                str(self.signing_key),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        public_key = Path(f"{self.signing_key}.pub").read_text(encoding="utf-8").strip()
        self.allowed_signers = self.root / "allowed_signers"
        self.allowed_signers.write_text(f"test-signer {public_key}\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def _git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def _git_output(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repo,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        ).stdout.strip()

    @staticmethod
    def _passed_command(command, *_args, **_kwargs):
        return {
            "command": command,
            "exit_code": 0,
            "duration_seconds": 0,
            "output": "passed",
        }

    def test_attestation_uses_explicit_kind_and_records_deletions(self):
        arguments = [
            "attest_repository.py",
            "--repo",
            str(self.repo),
            "--base",
            self.base,
            "--name",
            "deletion-attestation",
            "--run-dir",
            str(self.run_dir),
            "--acceptance",
            "true",
            "--signing-key",
            str(self.signing_key),
            "--signer-identity",
            "test-signer",
            "--allowed-signers",
            str(self.allowed_signers),
        ]
        with (
            mock.patch.object(
                attest_repository, "run", side_effect=self._passed_command
            ),
            mock.patch.object(sys, "argv", arguments),
        ):
            attest_repository.main()

        result = json.loads((self.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["execution_kind"], "post_implementation_attestation")
        self.assertEqual(result["stages"], [])
        self.assertFalse(result["runtime_boundary"]["filesystem_sandbox"])
        self.assertTrue(
            result["runtime_boundary"][
                "hostile_candidate_requires_external_container_or_vm"
            ]
        )
        self.assertEqual(result["promotion_manifest"]["changed_files"], ["removed.txt"])
        self.assertEqual(len(result["contract"]["attested_head"]), 40)
        manifest_path = self.run_dir / "evidence" / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        manifest = validate_automated_evidence(
            self.run_dir,
            allowed_signers=self.allowed_signers,
            head_sha=result["contract"]["attested_head"],
            expected_manifest_sha256=hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            manifest["run"]["execution_kind"],
            "post_implementation_attestation",
        )
        self.assertEqual(
            manifest["run"]["attested_head"], result["contract"]["attested_head"]
        )

    def test_new_file_is_in_exact_materialized_patch_and_signed_evidence(self):
        (self.repo / "added.txt").write_text("new candidate file\n", encoding="utf-8")
        self._git("add", "added.txt")
        self._git("commit", "-qm", "add candidate file")
        arguments = [
            "attest_repository.py",
            "--repo",
            str(self.repo),
            "--base",
            self.base,
            "--name",
            "new-file-attestation",
            "--run-dir",
            str(self.run_dir),
            "--acceptance",
            "true",
            "--signing-key",
            str(self.signing_key),
            "--signer-identity",
            "test-signer",
            "--allowed-signers",
            str(self.allowed_signers),
        ]
        with (
            mock.patch.object(
                attest_repository, "run", side_effect=self._passed_command
            ),
            mock.patch.object(sys, "argv", arguments),
        ):
            attest_repository.main()

        result = json.loads((self.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["automated_gates_passed"])
        self.assertEqual(
            result["final_gates"]["checks"]["candidate_materialization"]["exit_code"],
            0,
        )
        self.assertEqual(
            result["final_gates"]["checks"]["materialized_candidate_immutability"][
                "exit_code"
            ],
            0,
        )
        self.assertIn("added.txt", result["promotion_manifest"]["changed_files"])
        self.assertTrue((self.run_dir / "evidence" / "manifest.json").is_file())

    def test_local_status_config_cannot_hide_an_untracked_attestation_input(self):
        self._git("config", "status.showUntrackedFiles", "no")
        (self.repo / "hidden-input.py").write_text("VALUE = 99\n", encoding="utf-8")
        arguments = [
            "attest_repository.py",
            "--repo",
            str(self.repo),
            "--base",
            self.base,
            "--name",
            "unsafe-attestation",
            "--run-dir",
            str(self.run_dir),
            "--acceptance",
            "true",
            "--signing-key",
            str(self.signing_key),
            "--signer-identity",
            "test-signer",
            "--allowed-signers",
            str(self.allowed_signers),
        ]
        with mock.patch.object(sys, "argv", arguments):
            with self.assertRaisesRegex(SystemExit, "clean before attestation"):
                attest_repository.main()

    def test_ignored_payload_behind_symlink_cannot_receive_signed_attestation(self):
        exclude = Path(self._git_output("rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = self.repo / exclude
        exclude.write_text(".codegraph/\n", encoding="utf-8")
        payload = self.repo / ".codegraph" / "payload.txt"
        payload.parent.mkdir()
        payload.write_text("hidden attestation input\n", encoding="utf-8")
        (self.repo / "link.txt").symlink_to(".codegraph/payload.txt")
        self._git("add", "link.txt")
        self._git("commit", "-qm", "add hidden-input symlink")
        arguments = [
            "attest_repository.py",
            "--repo",
            str(self.repo),
            "--base",
            self.base,
            "--name",
            "hidden-payload-attestation",
            "--run-dir",
            str(self.run_dir),
            "--acceptance",
            'python3 -c "from pathlib import Path; '
            "assert Path('link.txt').read_text() == 'hidden attestation input\\n'\"",
            "--signing-key",
            str(self.signing_key),
            "--signer-identity",
            "test-signer",
            "--allowed-signers",
            str(self.allowed_signers),
        ]
        with mock.patch.object(sys, "argv", arguments):
            with self.assertRaisesRegex(SystemExit, "attestation gates failed"):
                attest_repository.main()
        result = json.loads((self.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(result["automated_gates_passed"])
        self.assertNotEqual(
            result["final_gates"]["checks"]["acceptance_1"]["exit_code"], 0
        )
        self.assertFalse((self.run_dir / "evidence").exists())

    def test_absolute_symlink_cannot_receive_signed_attestation(self):
        payload = self.root / "host-only-payload.txt"
        payload.write_text("host attestation input\n", encoding="utf-8")
        (self.repo / "link.txt").symlink_to(payload)
        self._git("add", "link.txt")
        self._git("commit", "-qm", "add absolute host symlink")
        arguments = [
            "attest_repository.py",
            "--repo",
            str(self.repo),
            "--base",
            self.base,
            "--name",
            "absolute-symlink-attestation",
            "--run-dir",
            str(self.run_dir),
            "--acceptance",
            'python3 -c "from pathlib import Path; '
            "assert Path('link.txt').read_text() == 'host attestation input\\n'\"",
            "--signing-key",
            str(self.signing_key),
            "--signer-identity",
            "test-signer",
            "--allowed-signers",
            str(self.allowed_signers),
        ]
        with mock.patch.object(sys, "argv", arguments):
            with self.assertRaisesRegex(SystemExit, "attestation gates failed"):
                attest_repository.main()
        result = json.loads((self.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(result["automated_gates_passed"])
        self.assertEqual(
            result["final_gates"]["checks"]["candidate_symlink_boundary"]["exit_code"],
            1,
        )
        self.assertNotIn("acceptance_1", result["final_gates"]["checks"])
        self.assertFalse((self.run_dir / "evidence").exists())

    def test_unversioned_gitlink_payload_cannot_receive_signed_attestation(self):
        gitlink_target = self._git_output("rev-parse", "HEAD")
        self._git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"160000,{gitlink_target},vendor",
        )
        self._git("commit", "-qm", "add gitlink")
        vendor = self.repo / "vendor"
        vendor.mkdir()
        (vendor / "value.txt").write_text("hidden vendor value\n", encoding="utf-8")
        arguments = [
            "attest_repository.py",
            "--repo",
            str(self.repo),
            "--base",
            self.base,
            "--name",
            "gitlink-payload-attestation",
            "--run-dir",
            str(self.run_dir),
            "--acceptance",
            'python3 -c "from pathlib import Path; '
            "assert Path('vendor/value.txt').read_text() == 'hidden vendor value\\n'\"",
            "--signing-key",
            str(self.signing_key),
            "--signer-identity",
            "test-signer",
            "--allowed-signers",
            str(self.allowed_signers),
        ]
        with mock.patch.object(sys, "argv", arguments):
            with self.assertRaisesRegex(SystemExit, "attestation gates failed"):
                attest_repository.main()
        result = json.loads((self.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertFalse(result["automated_gates_passed"])
        self.assertNotEqual(
            result["final_gates"]["checks"]["acceptance_1"]["exit_code"], 0
        )
        self.assertFalse((self.run_dir / "evidence").exists())


if __name__ == "__main__":
    unittest.main()
