from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from tools import merge_pr
from tools.merge_pr import (
    MergeGateError,
    build_merge_command,
    load_policy,
    load_r5_artifact,
    validate_checks,
    validate_pr,
    validate_timestamp,
    verify_r5_signature,
)
from workflow.evidence import allowed_signer_fingerprints


HEAD = "a" * 40


def policy_value() -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": "owner/repo",
        "base_branch": "master",
        "merge_method": "merge",
        "required_checks": [
            {"name": "test", "workflow": "Workflow Lab CI"},
            {"name": "ShellCheck", "workflow": "Workflow Lab CI"},
        ],
        "require_all_reported_checks_pass": True,
        "r5_max_age_hours": 24,
    }


def r5_value(*, policy_sha256: str = "b" * 64) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "SAGE Human R5",
        "repository": "owner/repo",
        "pr_number": 12,
        "head_sha": HEAD,
        "human_identity": "human@example.com",
        "human_signer_fingerprint": "SHA256:" + "A" * 43,
        "github_actor": "human",
        "verified_at_utc": "2026-07-14T12:00:00+00:00",
        "policy_sha256": policy_sha256,
        "automated_evidence_manifest_sha256": "c" * 64,
        "acceptance_log_sha256": "d" * 64,
        "files_changed_reviewed": True,
        "spontaneous_check": "Manually exercised a fail-closed path.",
        "r5_human_verification": "passed",
        "merge_authorized": True,
    }


def pr_value(**overrides: object) -> dict[str, object]:
    value = {
        "number": 12,
        "state": "OPEN",
        "isDraft": False,
        "headRefName": "codex/recovery",
        "headRefOid": HEAD,
        "baseRefName": "master",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "autoMergeRequest": None,
    }
    value.update(overrides)
    return value


def check(name: str, bucket: str = "pass") -> dict[str, str]:
    return {
        "name": name,
        "workflow": "Workflow Lab CI",
        "state": "SUCCESS" if bucket == "pass" else "FAILURE",
        "bucket": bucket,
    }


class MergePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, name: str, value: object) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        return path

    def test_policy_and_r5_are_strict_and_content_bound(self):
        policy_path = self.write_json("policy.json", policy_value())
        policy, digest = load_policy(policy_path)
        self.assertEqual(digest, hashlib.sha256(policy_path.read_bytes()).hexdigest())
        r5_path = self.write_json("r5.json", r5_value(policy_sha256=digest))
        artifact, _ = load_r5_artifact(r5_path)
        self.assertEqual(artifact["policy_sha256"], digest)
        self.assertEqual(policy["repository"], artifact["repository"])

    def test_execute_rechecks_r5_freshness_after_interactive_wait(self):
        policy = policy_value()
        artifact = r5_value()
        artifact["human_signer_fingerprint"] = "SHA256:human"
        args = SimpleNamespace(
            repo=self.root,
            policy=None,
            r5_artifact=self.root / "r5.json",
            r5_signature=None,
            r5_allowed_signers=self.root / "human-allowed",
            automated_run_dir=self.root / "automated",
            automated_allowed_signers=self.root / "automated-allowed",
            acceptance_log=self.root / "acceptance.log",
            execute=True,
        )
        state = {
            "pr": pr_value(),
            "checks": [check("test"), check("ShellCheck")],
            "actor": "human",
            "branch": "codex/recovery",
        }
        phrase = f"MERGE PR #{artifact['pr_number']} {artifact['head_sha']}"
        with (
            mock.patch.object(merge_pr, "parse_args", return_value=args),
            mock.patch.object(merge_pr, "load_policy", return_value=(policy, "b" * 64)),
            mock.patch.object(
                merge_pr, "load_r5_artifact", return_value=(artifact, b"artifact")
            ),
            mock.patch.object(merge_pr, "_regular_bytes", return_value=b"snapshot"),
            mock.patch.object(
                merge_pr,
                "verify_r5_signature",
                return_value="SHA256:human",
            ),
            mock.patch.object(
                merge_pr,
                "allowed_signer_fingerprints",
                side_effect=[{"SHA256:human"}, {"SHA256:automated"}],
            ),
            mock.patch.object(
                merge_pr,
                "validate_automated_evidence",
                return_value={
                    "signer_fingerprint": "SHA256:automated",
                    "signer_identity": "automation@example.com",
                },
            ),
            mock.patch.object(merge_pr, "validate_acceptance_log"),
            mock.patch.object(
                merge_pr, "validate_external_state", side_effect=[state, state]
            ),
            mock.patch.object(merge_pr, "validate_timestamp") as freshness,
            mock.patch.object(merge_pr, "_run"),
            mock.patch("builtins.input", return_value=phrase),
            mock.patch.object(sys.stdin, "isatty", return_value=True),
            mock.patch.object(sys.stdout, "isatty", return_value=True),
        ):
            self.assertEqual(merge_pr.main(), 0)
        self.assertEqual(freshness.call_count, 2)

    def test_policy_rejects_empty_or_duplicate_required_checks(self):
        for checks in (
            [],
            [
                {"name": "test", "workflow": "Workflow Lab CI"},
                {"name": "test", "workflow": "Workflow Lab CI"},
            ],
        ):
            with self.subTest(checks=checks):
                value = policy_value()
                value["required_checks"] = checks
                with self.assertRaises(MergeGateError):
                    load_policy(self.write_json(f"policy-{len(checks)}.json", value))

    def test_r5_rejects_pending_false_or_extra_fields(self):
        variants = []
        pending = r5_value()
        pending["r5_human_verification"] = "pending"
        variants.append(pending)
        unauthorized = r5_value()
        unauthorized["merge_authorized"] = False
        variants.append(unauthorized)
        extra = r5_value()
        extra["agent_claim"] = True
        variants.append(extra)
        for index, value in enumerate(variants):
            with self.subTest(index=index):
                with self.assertRaises(MergeGateError):
                    load_r5_artifact(self.write_json(f"r5-{index}.json", value))

    def test_r5_artifact_rejects_symlink(self):
        target = self.write_json("target.json", r5_value())
        link = self.root / "r5-link.json"
        os.symlink(target, link)
        with self.assertRaises(MergeGateError):
            load_r5_artifact(link)

    def test_r5_signature_verifies_exact_bytes_and_rejects_tampering(self):
        key = self.root / "human-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        artifact = self.write_json("r5-signed.json", r5_value())
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                "sage-r5",
                str(artifact),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        public_key = Path(f"{key}.pub").read_text(encoding="utf-8").strip()
        allowed = self.root / "allowed_signers"
        allowed.write_text(
            f'human@example.com namespaces="sage-r5" {public_key}\n',
            encoding="utf-8",
        )
        signature = Path(f"{artifact}.sig")
        fingerprint = verify_r5_signature(
            artifact, signature, allowed, "human@example.com"
        )
        self.assertIn(fingerprint, allowed_signer_fingerprints(allowed.read_bytes()))
        artifact.write_text(json.dumps(r5_value(), indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(MergeGateError):
            verify_r5_signature(artifact, signature, allowed, "human@example.com")

    def test_signature_verification_uses_one_immutable_snapshot(self):
        trusted_key = self.root / "trusted-key"
        attacker_key = self.root / "attacker-key"
        for key in (trusted_key, attacker_key):
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        artifact = self.write_json("r5-snapshot.json", r5_value())
        subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "sign",
                "-f",
                str(trusted_key),
                "-n",
                "sage-r5",
                str(artifact),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        signature = Path(f"{artifact}.sig")
        allowed = self.root / "snapshot_allowed_signers"
        trusted_public = Path(f"{trusted_key}.pub").read_text(encoding="utf-8").strip()
        allowed.write_text(
            f'human@example.com namespaces="sage-r5" {trusted_public}\n',
            encoding="utf-8",
        )
        artifact_snapshot = artifact.read_bytes()
        signature_snapshot = signature.read_bytes()
        allowed_snapshot = allowed.read_bytes()

        attacker_public = (
            Path(f"{attacker_key}.pub").read_text(encoding="utf-8").strip()
        )
        allowed.write_text(
            f'human@example.com namespaces="sage-r5" {attacker_public}\n',
            encoding="utf-8",
        )
        artifact.write_text('{"swapped":true}\n', encoding="utf-8")
        actual = verify_r5_signature(
            artifact,
            signature,
            allowed,
            "human@example.com",
            artifact_snapshot=artifact_snapshot,
            signature_snapshot=signature_snapshot,
            allowed_signers_snapshot=allowed_snapshot,
        )
        self.assertIn(actual, allowed_signer_fingerprints(allowed_snapshot))
        self.assertNotIn(actual, allowed_signer_fingerprints(allowed.read_bytes()))

    def test_same_key_in_human_and_automation_trust_stores_is_detectable(self):
        key = self.root / "shared-key"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        public = Path(f"{key}.pub").read_text(encoding="utf-8").strip()
        human = f'human namespaces="sage-r5" {public}\n'.encode()
        automated = f'automation namespaces="sage-evidence" {public}\n'.encode()
        self.assertTrue(
            allowed_signer_fingerprints(human) & allowed_signer_fingerprints(automated)
        )

    def test_r5_timestamp_must_be_fresh_and_timezone_aware(self):
        now = datetime(2026, 7, 14, 13, tzinfo=timezone.utc)
        validate_timestamp("2026-07-14T12:00:00+00:00", max_age_hours=24, now=now)
        for value in (
            "2026-07-12T12:00:00+00:00",
            "2026-07-14T13:06:00+00:00",
            "2026-07-14T12:00:00",
        ):
            with self.subTest(value=value), self.assertRaises(MergeGateError):
                validate_timestamp(value, max_age_hours=24, now=now)
        validate_timestamp(
            (now - timedelta(hours=23)).isoformat(), max_age_hours=24, now=now
        )

    def test_pr_requires_exact_open_ready_clean_head_without_auto_merge(self):
        policy = policy_value()
        artifact = r5_value()
        self.assertEqual(
            validate_pr(pr_value(), policy=policy, artifact=artifact),
            "codex/recovery",
        )
        unsafe = {
            "state": "MERGED",
            "isDraft": True,
            "headRefOid": "b" * 40,
            "mergeable": "CONFLICTING",
            "mergeStateStatus": "BLOCKED",
            "autoMergeRequest": {"enabledAt": "now"},
        }
        for field, value in unsafe.items():
            with self.subTest(field=field), self.assertRaises(MergeGateError):
                validate_pr(
                    pr_value(**{field: value}), policy=policy, artifact=artifact
                )

    def test_checks_require_every_reported_check_and_exact_policy_set(self):
        required = policy_value()["required_checks"]
        good = [check("test"), check("ShellCheck")]
        validate_checks(good, required=required)
        for value in (
            [],
            [check("test")],
            [check("test"), check("ShellCheck", "fail")],
            [check("test"), check("ShellCheck"), check("optional", "pending")],
            [check("test"), check("test"), check("ShellCheck")],
        ):
            with self.subTest(value=value), self.assertRaises(MergeGateError):
                validate_checks(value, required=required)

    def test_merge_command_binds_head_and_has_no_bypass_or_auto_flags(self):
        command = build_merge_command(policy_value(), r5_value())
        self.assertIn("--match-head-commit", command)
        self.assertIn(HEAD, command)
        self.assertNotIn("--admin", command)
        self.assertNotIn("--auto", command)
        self.assertNotIn("--delete-branch", command)


if __name__ == "__main__":
    unittest.main()
