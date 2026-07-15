from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from workflow.public_export import (
    CERTIFICATE_PATH,
    REQUIRED_ATTESTATION_CHECKS,
    SIGNATURE_PATH,
    PublicExportError,
    materialize_public_snapshot,
    prepare_public_repository,
    tree_sha256,
    validate_private_attestation,
    verify_public_export,
    write_export_certificate,
)


class PublicExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def run_git(self, repo: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def init_repo(self, name: str = "source") -> Path:
        repo = self.root / name
        repo.mkdir()
        self.run_git(repo, "init", "-q", "-b", "master")
        self.run_git(repo, "config", "user.name", "Public Export Test")
        self.run_git(
            repo,
            "config",
            "user.email",
            "public-export-test@example.invalid",
        )
        return repo

    def write(self, root: Path, relative: str, content: str) -> None:
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, repo: Path, message: str = "fixture") -> str:
        self.run_git(repo, "add", "--all")
        self.run_git(repo, "commit", "-qm", message)
        return self.run_git(repo, "rev-parse", "HEAD")

    def populate_export_source(self, repo: Path) -> None:
        files = {
            ".gitignore": "*.tmp\n",
            "LICENSE": "test license\n",
            "README.md": "private readme\n",
            ".github/sage-merge-policy.json": "private policy\n",
            ".github/workflows/ci.yml": "private ci\n",
            "templates/github/public-ci.yml": "public ci\n",
            "templates/github/public-oracle.yml": "public oracle\n",
            "templates/github/sage-public-merge-policy.json": "public policy\n",
            "tools/verify_public_export.py": "# verifier\n",
            "workflow/evidence.py": "# evidence\n",
            "workflow/public_export.py": "# exporter\n",
            "workflow/trusted_signers": "test ssh-ed25519 AAAA\n",
            "src/app.py": "VALUE = 1\n",
            "benchmarks/hidden/oracle.py": "SECRET_ORACLE = 1\n",
            "benchmarks/sprite-game-hidden/game.test.js": "hidden();\n",
        }
        for path, content in files.items():
            self.write(repo, path, content)

    def generate_signer(self) -> tuple[Path, Path]:
        key = self.root / "signer"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
        )
        fields = Path(f"{key}.pub").read_text(encoding="utf-8").split()
        allowed = self.root / "allowed_signers"
        allowed.write_text(
            f"test-signer {fields[0]} {fields[1]}\n",
            encoding="utf-8",
        )
        return key, allowed

    def certificate(self, repo: Path) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "SAGE Public Export",
            "repository": "example/sage-public",
            "source_repository": "example/sage-private",
            "source_head": "a" * 40,
            "source_tree_sha256": "b" * 64,
            "public_tree_sha256": tree_sha256(repo, "HEAD"),
            "automated_evidence_manifest_sha256": "c" * 64,
            "automated_evidence_signer_fingerprint": "SHA256:" + "A" * 43,
            "signer_identity": "test-signer",
            "created_at_utc": "2026-07-15T00:00:00+00:00",
            "private_oracle_gates_passed": True,
            "export_secret_scan_passed": True,
            "automated_gates_passed": True,
            "r5_human_verification": "pending",
            "merge_authorized": False,
        }

    def signed_public_repo(self) -> tuple[Path, Path]:
        repo = self.init_repo("public")
        self.write(repo, "app.py", "VALUE = 1\n")
        self.commit(repo)
        key, allowed = self.generate_signer()
        write_export_certificate(
            repo,
            self.certificate(repo),
            signing_key=key,
            signer_identity="test-signer",
            allowed_signers=allowed,
        )
        self.commit(repo, "signed export")
        return repo, allowed

    def test_materialization_excludes_oracles_and_replaces_private_workflows(self):
        source = self.init_repo()
        self.populate_export_source(source)
        head = self.commit(source)
        destination = self.root / "snapshot"

        exported = materialize_public_snapshot(source, head, destination)

        self.assertNotIn("benchmarks/hidden/oracle.py", exported)
        self.assertNotIn("benchmarks/sprite-game-hidden/game.test.js", exported)
        self.assertEqual(
            (destination / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
            "public ci\n",
        )
        self.assertEqual(
            (destination / ".github/workflows/private-oracle.yml").read_text(
                encoding="utf-8"
            ),
            "public oracle\n",
        )
        self.assertFalse((destination / ".git").exists())

    def test_materialization_rejects_public_copy_of_excluded_oracle_blob(self):
        source = self.init_repo()
        self.populate_export_source(source)
        self.write(source, "src/copied_oracle.py", "SECRET_ORACLE = 1\n")
        head = self.commit(source)

        with self.assertRaisesRegex(PublicExportError, "duplicates an excluded"):
            materialize_public_snapshot(source, head, self.root / "snapshot")

    def test_materialization_rejects_symlinks(self):
        source = self.init_repo()
        self.populate_export_source(source)
        (source / "unsafe-link").symlink_to("README.md")
        head = self.commit(source)

        with self.assertRaisesRegex(PublicExportError, "non-regular tracked entry"):
            materialize_public_snapshot(source, head, self.root / "snapshot")

    def test_private_attestation_requires_explicit_hidden_gate_commands(self):
        run_dir = self.root / "attestation"
        (run_dir / "evidence").mkdir(parents=True)
        (run_dir / "evidence/manifest.json").write_text("{}\n", encoding="utf-8")
        checks = {name: {"exit_code": 0} for name in REQUIRED_ATTESTATION_CHECKS}
        checks["acceptance_1"] = {"exit_code": 0}
        result = {
            "automated_gates_passed": True,
            "r5_human_verification": "pending",
            "merge_authorized": False,
            "final_gates": {"passed": True, "checks": checks},
            "promotion_manifest": {
                "acceptance_commands": ["python3 tools/lab.py verify-fixture"]
            },
        }
        result_bytes = json.dumps(result).encode()
        (run_dir / "result.json").write_bytes(result_bytes)
        manifest = {
            "run": {
                "execution_kind": "post_implementation_attestation",
                "attested_head": "a" * 40,
            },
            "artifacts": {
                "result_json_sha256": hashlib.sha256(result_bytes).hexdigest()
            },
            "signer_fingerprint": "SHA256:" + "A" * 43,
        }

        with (
            mock.patch(
                "workflow.public_export.verify_signed_manifest",
                return_value=manifest,
            ),
            self.assertRaisesRegex(PublicExportError, "audit_sprite_game"),
        ):
            validate_private_attestation(
                run_dir,
                allowed_signers=self.root / "unused",
                source_head="a" * 40,
            )

    def test_private_attestation_accepts_exact_successful_hidden_gates(self):
        run_dir = self.root / "attestation"
        (run_dir / "evidence").mkdir(parents=True)
        manifest_bytes = b'{"signed":true}\n'
        (run_dir / "evidence/manifest.json").write_bytes(manifest_bytes)
        checks = {name: {"exit_code": 0} for name in REQUIRED_ATTESTATION_CHECKS}
        checks["acceptance_1"] = {"exit_code": 0}
        checks["acceptance_2"] = {"exit_code": 0}
        checks["acceptance_3"] = {"exit_code": 0}
        commands = [
            "python3 tools/lab.py verify-fixture",
            "python3 tools/audit_sprite_game.py --no-write",
            "python3 tools/check_version_record.py",
        ]
        result = {
            "automated_gates_passed": True,
            "r5_human_verification": "pending",
            "merge_authorized": False,
            "final_gates": {"passed": True, "checks": checks},
            "promotion_manifest": {"acceptance_commands": commands},
        }
        result_bytes = json.dumps(result).encode()
        (run_dir / "result.json").write_bytes(result_bytes)
        fingerprint = "SHA256:" + "A" * 43
        manifest = {
            "run": {
                "execution_kind": "post_implementation_attestation",
                "attested_head": "a" * 40,
            },
            "artifacts": {
                "result_json_sha256": hashlib.sha256(result_bytes).hexdigest()
            },
            "signer_fingerprint": fingerprint,
        }

        with mock.patch(
            "workflow.public_export.verify_signed_manifest",
            return_value=manifest,
        ):
            attestation = validate_private_attestation(
                run_dir,
                allowed_signers=self.root / "unused",
                source_head="a" * 40,
            )

        self.assertEqual(attestation["signer_fingerprint"], fingerprint)
        self.assertEqual(
            attestation["manifest_sha256"],
            hashlib.sha256(manifest_bytes).hexdigest(),
        )

    def test_private_attestation_rejects_boolean_false_exit_code(self):
        run_dir = self.root / "attestation"
        (run_dir / "evidence").mkdir(parents=True)
        manifest_bytes = b'{"signed":true}\n'
        (run_dir / "evidence/manifest.json").write_bytes(manifest_bytes)
        checks = {name: {"exit_code": 0} for name in REQUIRED_ATTESTATION_CHECKS}
        checks["acceptance_1"] = {"exit_code": False}
        checks["acceptance_2"] = {"exit_code": 0}
        checks["acceptance_3"] = {"exit_code": 0}
        result = {
            "automated_gates_passed": True,
            "r5_human_verification": "pending",
            "merge_authorized": False,
            "final_gates": {"passed": True, "checks": checks},
            "promotion_manifest": {
                "acceptance_commands": [
                    "python3 tools/lab.py verify-fixture",
                    "python3 tools/audit_sprite_game.py --no-write",
                    "python3 tools/check_version_record.py",
                ]
            },
        }
        result_bytes = json.dumps(result).encode()
        (run_dir / "result.json").write_bytes(result_bytes)
        manifest = {
            "run": {
                "execution_kind": "post_implementation_attestation",
                "attested_head": "a" * 40,
            },
            "artifacts": {
                "result_json_sha256": hashlib.sha256(result_bytes).hexdigest()
            },
            "signer_fingerprint": "SHA256:" + "A" * 43,
        }

        with (
            mock.patch(
                "workflow.public_export.verify_signed_manifest",
                return_value=manifest,
            ),
            self.assertRaisesRegex(PublicExportError, "lab.py verify-fixture"),
        ):
            validate_private_attestation(
                run_dir,
                allowed_signers=self.root / "unused",
                source_head="a" * 40,
            )

    def test_signed_export_verifies_and_detects_tree_tampering(self):
        repo, allowed = self.signed_public_repo()

        verified = verify_public_export(
            repo,
            allowed_signers=allowed,
            expected_repository="example/sage-public",
            expected_source_repository="example/sage-private",
        )
        self.assertTrue(verified["passed"])

        self.write(repo, "app.py", "VALUE = 2\n")
        self.commit(repo, "tamper")
        with self.assertRaisesRegex(PublicExportError, "tree does not match"):
            verify_public_export(repo, allowed_signers=allowed)

    def test_signed_export_rejects_unexpected_certificate_namespace_file(self):
        repo, allowed = self.signed_public_repo()
        self.write(repo, ".sage-public-export/leak.txt", "unexpected\n")
        self.commit(repo, "unexpected certificate file")

        with self.assertRaisesRegex(PublicExportError, "unexpected certificate files"):
            verify_public_export(repo, allowed_signers=allowed)

    def test_signed_export_requires_trusted_key(self):
        repo, _allowed = self.signed_public_repo()
        _other_key, other_allowed = self.generate_signer_for_name("other")

        with self.assertRaisesRegex(PublicExportError, "signature is invalid"):
            verify_public_export(repo, allowed_signers=other_allowed)

    def generate_signer_for_name(self, name: str) -> tuple[Path, Path]:
        key = self.root / name
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            check=True,
        )
        fields = Path(f"{key}.pub").read_text(encoding="utf-8").split()
        allowed = self.root / f"{name}_allowed_signers"
        allowed.write_text(
            f"test-signer {fields[0]} {fields[1]}\n",
            encoding="utf-8",
        )
        return key, allowed

    def test_signed_export_rejects_hidden_oracle_path(self):
        repo, allowed = self.signed_public_repo()
        self.write(repo, "benchmarks/hidden/leak.py", "oracle\n")
        self.commit(repo, "hidden leak")

        with self.assertRaisesRegex(PublicExportError, "blocked paths"):
            verify_public_export(repo, allowed_signers=allowed)

    def test_prepare_builds_two_commit_history_free_repository(self):
        source = self.init_repo()
        self.populate_export_source(source)
        key, allowed = self.generate_signer()
        (source / "workflow/trusted_signers").write_bytes(allowed.read_bytes())
        source_head = self.commit(source)
        destination = self.root / "public-export"
        attestation = {
            "manifest_sha256": "c" * 64,
            "signer_fingerprint": "SHA256:" + "A" * 43,
        }

        with (
            mock.patch(
                "workflow.public_export.validate_private_attestation",
                return_value=attestation,
            ),
            mock.patch("workflow.public_export.secret_scan") as scan,
        ):
            result = prepare_public_repository(
                source,
                source_head,
                destination,
                source_repository="example/sage-private",
                public_repository="example/sage-public",
                branch="codex/public-v1",
                attestation_run=self.root / "attestation",
                attestation_allowed_signers=allowed,
                signing_key=key,
                signer_identity="test-signer",
            )

        scan.assert_called_once()
        self.assertEqual(result["source_head"], source_head)
        self.assertEqual(self.run_git(destination, "rev-list", "--count", "--all"), "2")
        self.assertEqual(
            self.run_git(destination, "branch", "--show-current"),
            "codex/public-v1",
        )
        tracked = set(
            self.run_git(
                destination, "ls-tree", "-r", "--name-only", "HEAD"
            ).splitlines()
        )
        self.assertNotIn("benchmarks/hidden/oracle.py", tracked)
        self.assertNotIn("benchmarks/sprite-game-hidden/game.test.js", tracked)
        self.assertIn(CERTIFICATE_PATH, tracked)
        self.assertIn(SIGNATURE_PATH, tracked)

    def test_prepare_rejects_snapshot_replacement_after_source_digest(self):
        source = self.init_repo()
        self.populate_export_source(source)
        key, allowed = self.generate_signer()
        (source / "workflow/trusted_signers").write_bytes(allowed.read_bytes())
        source_head = self.commit(source)
        attestation = {
            "manifest_sha256": "c" * 64,
            "signer_fingerprint": "SHA256:" + "A" * 43,
        }

        def replace_snapshot(snapshot: Path) -> None:
            self.write(snapshot, "src/app.py", "VALUE = 999\n")

        with (
            mock.patch(
                "workflow.public_export.validate_private_attestation",
                return_value=attestation,
            ),
            mock.patch(
                "workflow.public_export.secret_scan",
                side_effect=replace_snapshot,
            ),
            self.assertRaisesRegex(PublicExportError, "immutable source snapshot"),
        ):
            prepare_public_repository(
                source,
                source_head,
                self.root / "public-export",
                source_repository="example/sage-private",
                public_repository="example/sage-public",
                branch="codex/public-v1",
                attestation_run=self.root / "attestation",
                attestation_allowed_signers=allowed,
                signing_key=key,
                signer_identity="test-signer",
            )

    def test_certificate_and_signature_are_the_only_digest_exclusions(self):
        repo, _allowed = self.signed_public_repo()
        paths = set(
            self.run_git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
        )
        self.assertIn(CERTIFICATE_PATH, paths)
        self.assertIn(SIGNATURE_PATH, paths)


if __name__ == "__main__":
    unittest.main()
