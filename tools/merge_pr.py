#!/usr/bin/env python3
"""Fail-closed local PR merge wrapper gated by signed human R5 evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.evidence import (
    EvidenceError,
    allowed_signer_fingerprints,
    regular_file_bytes,
    verify_signed_manifest,
    verify_sshsig_bytes,
)


R5_NAMESPACE = "sage-r5"
POLICY_FIELDS = {
    "schema_version",
    "repository",
    "base_branch",
    "merge_method",
    "required_checks",
    "require_all_reported_checks_pass",
    "r5_max_age_hours",
}
R5_FIELDS = {
    "schema_version",
    "kind",
    "repository",
    "pr_number",
    "head_sha",
    "human_identity",
    "human_signer_fingerprint",
    "github_actor",
    "verified_at_utc",
    "policy_sha256",
    "automated_evidence_manifest_sha256",
    "acceptance_log_sha256",
    "files_changed_reviewed",
    "spontaneous_check",
    "r5_human_verification",
    "merge_authorized",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
FINGERPRINT_RE = re.compile(r"SHA256:[A-Za-z0-9+/]{43}")


class MergeGateError(RuntimeError):
    """A merge invariant was missing, stale, ambiguous, or false."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise MergeGateError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _regular_bytes(path: Path, label: str) -> bytes:
    try:
        return regular_file_bytes(path, label)
    except EvidenceError as error:
        raise MergeGateError(str(error)) from error


def _json_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    content = _regular_bytes(path, label)
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MergeGateError(f"{label} is not valid unique-key JSON") from error
    if not isinstance(value, dict):
        raise MergeGateError(f"{label} must be a JSON object")
    return value, content


def _exact_fields(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise MergeGateError(
            f"{label} has an invalid schema: missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def load_policy(path: Path) -> tuple[dict[str, Any], str]:
    policy, content = _json_object(path, "merge policy")
    _exact_fields(policy, POLICY_FIELDS, "merge policy")
    if policy["schema_version"] != 1:
        raise MergeGateError("unsupported merge policy schema")
    if not isinstance(policy["repository"], str) or not REPOSITORY_RE.fullmatch(
        policy["repository"]
    ):
        raise MergeGateError("merge policy repository is invalid")
    if not isinstance(policy["base_branch"], str) or not policy["base_branch"]:
        raise MergeGateError("merge policy base branch is invalid")
    if policy["merge_method"] not in {"merge", "squash", "rebase"}:
        raise MergeGateError("merge policy method is invalid")
    if policy["require_all_reported_checks_pass"] is not True:
        raise MergeGateError("merge policy must require every reported check to pass")
    max_age = policy["r5_max_age_hours"]
    if (
        isinstance(max_age, bool)
        or not isinstance(max_age, int)
        or not 1 <= max_age <= 168
    ):
        raise MergeGateError("R5 maximum age must be an integer from 1 to 168 hours")

    checks = policy["required_checks"]
    if not isinstance(checks, list) or not checks:
        raise MergeGateError("merge policy must name required checks")
    identities: set[tuple[str, str]] = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"name", "workflow"}:
            raise MergeGateError("each required check needs only name and workflow")
        identity = (check.get("name"), check.get("workflow"))
        if not all(isinstance(item, str) and item for item in identity):
            raise MergeGateError("required check name and workflow must be nonempty")
        if identity in identities:
            raise MergeGateError(f"duplicate required check: {identity}")
        identities.add(identity)
    return policy, hashlib.sha256(content).hexdigest()


def _parse_r5_artifact(content: bytes) -> dict[str, Any]:
    try:
        artifact = json.loads(content, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MergeGateError(
            "human R5 artifact is not valid unique-key JSON"
        ) from error
    if not isinstance(artifact, dict):
        raise MergeGateError("human R5 artifact must be a JSON object")
    _exact_fields(artifact, R5_FIELDS, "human R5 artifact")
    if artifact["schema_version"] != 1 or artifact["kind"] != "SAGE Human R5":
        raise MergeGateError("unsupported human R5 artifact")
    if not isinstance(artifact["repository"], str) or not REPOSITORY_RE.fullmatch(
        artifact["repository"]
    ):
        raise MergeGateError("R5 repository is invalid")
    number = artifact["pr_number"]
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise MergeGateError("R5 PR number is invalid")
    if not isinstance(artifact["head_sha"], str) or not COMMIT_RE.fullmatch(
        artifact["head_sha"]
    ):
        raise MergeGateError("R5 head SHA is invalid")
    for field in ("human_identity", "github_actor", "spontaneous_check"):
        if not isinstance(artifact[field], str) or not artifact[field].strip():
            raise MergeGateError(f"R5 {field} must be nonempty")
    if not isinstance(
        artifact["human_signer_fingerprint"], str
    ) or not FINGERPRINT_RE.fullmatch(artifact["human_signer_fingerprint"]):
        raise MergeGateError("R5 human signer fingerprint is invalid")
    for field in (
        "policy_sha256",
        "automated_evidence_manifest_sha256",
        "acceptance_log_sha256",
    ):
        if not isinstance(artifact[field], str) or not SHA256_RE.fullmatch(
            artifact[field]
        ):
            raise MergeGateError(f"R5 {field} is invalid")
    if artifact["files_changed_reviewed"] is not True:
        raise MergeGateError("R5 must attest that Files changed was reviewed")
    if artifact["r5_human_verification"] != "passed":
        raise MergeGateError("human R5 is not passed")
    if artifact["merge_authorized"] is not True:
        raise MergeGateError("human merge authorization is absent")
    return artifact


def load_r5_artifact(path: Path) -> tuple[dict[str, Any], bytes]:
    content = _regular_bytes(path, "human R5 artifact")
    return _parse_r5_artifact(content), content


def validate_timestamp(
    value: Any, *, max_age_hours: int, now: datetime | None = None
) -> None:
    if not isinstance(value, str):
        raise MergeGateError("R5 timestamp is invalid")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MergeGateError("R5 timestamp is invalid") from error
    if timestamp.tzinfo is None:
        raise MergeGateError("R5 timestamp must include a timezone")
    current = now or datetime.now(timezone.utc)
    age = current - timestamp.astimezone(timezone.utc)
    if age < -timedelta(minutes=5) or age > timedelta(hours=max_age_hours):
        raise MergeGateError("R5 timestamp is in the future or has expired")


def verify_r5_signature(
    artifact_path: Path,
    signature_path: Path,
    allowed_signers: Path,
    identity: str,
    *,
    artifact_snapshot: bytes | None = None,
    signature_snapshot: bytes | None = None,
    allowed_signers_snapshot: bytes | None = None,
) -> str:
    artifact = (
        artifact_snapshot
        if artifact_snapshot is not None
        else _regular_bytes(artifact_path, "human R5 artifact")
    )
    signature = (
        signature_snapshot
        if signature_snapshot is not None
        else _regular_bytes(signature_path, "human R5 signature")
    )
    allowed = (
        allowed_signers_snapshot
        if allowed_signers_snapshot is not None
        else _regular_bytes(allowed_signers, "human R5 allowed-signers file")
    )
    try:
        return verify_sshsig_bytes(
            artifact,
            signature=signature,
            allowed_signers=allowed,
            identity=identity,
            namespace=R5_NAMESPACE,
        )
    except EvidenceError as error:
        raise MergeGateError(
            f"human R5 signature is invalid or untrusted: {error}"
        ) from error


def validate_automated_evidence(
    run_dir: Path,
    *,
    allowed_signers: Path,
    allowed_signers_snapshot: bytes | None = None,
    head_sha: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    run_dir = run_dir.expanduser().resolve()
    try:
        manifest = verify_signed_manifest(
            run_dir,
            allowed_signers=allowed_signers,
            allowed_signers_snapshot=allowed_signers_snapshot,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except EvidenceError as error:
        raise MergeGateError(f"automated evidence is invalid: {error}") from error
    if manifest.get("run", {}).get("execution_kind") != (
        "post_implementation_attestation"
    ):
        raise MergeGateError("automated merge evidence is not a repository attestation")
    if manifest.get("run", {}).get("attested_head") != head_sha:
        raise MergeGateError("automated evidence is not bound to the R5 head SHA")
    return manifest


def validate_acceptance_log(path: Path, expected_sha256: str) -> None:
    actual = hashlib.sha256(_regular_bytes(path, "human acceptance log")).hexdigest()
    if actual != expected_sha256:
        raise MergeGateError(
            "human acceptance log does not match the signed R5 artifact"
        )


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise MergeGateError(
            f"command failed ({' '.join(command)}): "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return completed


def _git(repo: Path, *arguments: str) -> str:
    return _run(["git", *arguments], repo).stdout.strip()


def _gh_json(repo: Path, command: list[str]) -> Any:
    output = _run(["gh", *command], repo).stdout
    try:
        return json.loads(output, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MergeGateError(
            f"GitHub returned invalid JSON for {' '.join(command)}"
        ) from error


def _remote_repository(remote: str) -> str | None:
    patterns = (
        r"https://github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$",
        r"git@github\.com:(?P<repo>[^/]+/[^/]+?)(?:\.git)?$",
        r"ssh://git@github\.com/(?P<repo>[^/]+/[^/]+?)(?:\.git)?/?$",
    )
    for pattern in patterns:
        if match := re.fullmatch(pattern, remote):
            return match.group("repo")
    return None


def validate_local_repository(
    repo: Path, *, repository: str, branch: str, head_sha: str
) -> None:
    if _git(repo, "status", "--porcelain"):
        raise MergeGateError("local repository must be clean")
    if _git(repo, "rev-parse", "HEAD") != head_sha:
        raise MergeGateError("local HEAD does not equal the signed R5 head")
    if _git(repo, "branch", "--show-current") != branch:
        raise MergeGateError("local branch does not equal the PR head branch")
    remote = _git(repo, "remote", "get-url", "origin")
    if (_remote_repository(remote) or "").casefold() != repository.casefold():
        raise MergeGateError("origin does not match the merge policy repository")


def validate_pr(value: Any, *, policy: dict[str, Any], artifact: dict[str, Any]) -> str:
    if not isinstance(value, dict):
        raise MergeGateError("GitHub PR response is invalid")
    expected = {
        "number": artifact["pr_number"],
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": artifact["head_sha"],
        "baseRefName": policy["base_branch"],
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "autoMergeRequest": None,
    }
    mismatches = {
        key: {"expected": expected_value, "actual": value.get(key)}
        for key, expected_value in expected.items()
        if value.get(key) != expected_value
    }
    if mismatches:
        raise MergeGateError(f"PR is not safe to merge: {mismatches}")
    branch = value.get("headRefName")
    if not isinstance(branch, str) or not branch:
        raise MergeGateError("PR head branch is missing")
    return branch


def validate_checks(value: Any, *, required: list[dict[str, str]]) -> None:
    if not isinstance(value, list) or not value:
        raise MergeGateError("GitHub reported no checks")
    identities: dict[tuple[str, str], int] = {}
    failures: list[dict[str, Any]] = []
    for check in value:
        if not isinstance(check, dict):
            raise MergeGateError("GitHub check response is invalid")
        identity = (check.get("name"), check.get("workflow"))
        if not all(isinstance(item, str) and item for item in identity):
            raise MergeGateError("GitHub check lacks a name or workflow")
        identities[identity] = identities.get(identity, 0) + 1
        if check.get("bucket") != "pass":
            failures.append(check)
    if failures:
        raise MergeGateError(f"not every reported GitHub check passed: {failures}")
    missing_or_ambiguous = {
        (check["name"], check["workflow"]): identities.get(
            (check["name"], check["workflow"]), 0
        )
        for check in required
        if identities.get((check["name"], check["workflow"]), 0) != 1
    }
    if missing_or_ambiguous:
        raise MergeGateError(
            f"required GitHub checks are missing or ambiguous: {missing_or_ambiguous}"
        )


def github_snapshot(
    repo: Path, *, repository: str, pr_number: int
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    pr = _gh_json(
        repo,
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repository,
            "--json",
            (
                "number,state,isDraft,headRefName,headRefOid,baseRefName,mergeable,"
                "mergeStateStatus,autoMergeRequest,url"
            ),
        ],
    )
    checks = _gh_json(
        repo,
        [
            "pr",
            "checks",
            str(pr_number),
            "--repo",
            repository,
            "--json",
            "name,workflow,state,bucket,completedAt,link",
        ],
    )
    actor = _run(["gh", "api", "user", "--jq", ".login"], repo).stdout.strip()
    if not actor:
        raise MergeGateError("GitHub authenticated actor is missing")
    return pr, checks, actor


def validate_external_state(
    repo: Path, *, policy: dict[str, Any], artifact: dict[str, Any]
) -> dict[str, Any]:
    pr, checks, actor = github_snapshot(
        repo,
        repository=policy["repository"],
        pr_number=artifact["pr_number"],
    )
    if actor.casefold() != artifact["github_actor"].casefold():
        raise MergeGateError("authenticated GitHub actor did not sign the R5 artifact")
    branch = validate_pr(pr, policy=policy, artifact=artifact)
    validate_checks(checks, required=policy["required_checks"])
    validate_local_repository(
        repo,
        repository=policy["repository"],
        branch=branch,
        head_sha=artifact["head_sha"],
    )
    return {"pr": pr, "checks": checks, "actor": actor, "branch": branch}


def build_merge_command(policy: dict[str, Any], artifact: dict[str, Any]) -> list[str]:
    return [
        "gh",
        "pr",
        "merge",
        str(artifact["pr_number"]),
        "--repo",
        policy["repository"],
        f"--{policy['merge_method']}",
        "--match-head-commit",
        artifact["head_sha"],
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate signed human R5 evidence and safely merge one exact PR head."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--r5-artifact", type=Path, required=True)
    parser.add_argument("--r5-signature", type=Path)
    parser.add_argument("--r5-allowed-signers", type=Path, required=True)
    parser.add_argument("--automated-run-dir", type=Path, required=True)
    parser.add_argument("--automated-allowed-signers", type=Path, required=True)
    parser.add_argument("--acceptance-log", type=Path, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="merge only after an interactive exact-SHA confirmation",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.expanduser().resolve()
    policy_path = (
        args.policy.expanduser().resolve()
        if args.policy
        else repo / ".github" / "sage-merge-policy.json"
    )
    artifact_path = args.r5_artifact.expanduser().absolute()
    signature_path = (
        args.r5_signature.expanduser().absolute()
        if args.r5_signature
        else Path(f"{artifact_path}.sig")
    )
    try:
        policy, policy_sha256 = load_policy(policy_path)
        artifact, artifact_snapshot = load_r5_artifact(artifact_path)
        signature_snapshot = _regular_bytes(signature_path, "human R5 signature")
        human_allowed_signers = args.r5_allowed_signers.expanduser().absolute()
        automated_allowed_signers = (
            args.automated_allowed_signers.expanduser().absolute()
        )
        human_allowed_snapshot = _regular_bytes(
            human_allowed_signers, "human R5 allowed-signers file"
        )
        automated_allowed_snapshot = _regular_bytes(
            automated_allowed_signers, "automated evidence allowed-signers file"
        )
        if artifact["repository"].casefold() != policy["repository"].casefold():
            raise MergeGateError("R5 repository does not match merge policy")
        if artifact["policy_sha256"] != policy_sha256:
            raise MergeGateError("R5 artifact does not bind the current merge policy")
        validate_timestamp(
            artifact["verified_at_utc"],
            max_age_hours=policy["r5_max_age_hours"],
        )
        human_signer_fingerprint = verify_r5_signature(
            artifact_path,
            signature_path,
            human_allowed_signers,
            artifact["human_identity"],
            artifact_snapshot=artifact_snapshot,
            signature_snapshot=signature_snapshot,
            allowed_signers_snapshot=human_allowed_snapshot,
        )
        if human_signer_fingerprint != artifact["human_signer_fingerprint"]:
            raise MergeGateError(
                "human R5 artifact fingerprint does not match its verified signer"
            )
        try:
            human_trust = allowed_signer_fingerprints(human_allowed_snapshot)
            automated_trust = allowed_signer_fingerprints(automated_allowed_snapshot)
        except EvidenceError as error:
            raise MergeGateError(f"allowed-signers file is invalid: {error}") from error
        shared_trust = human_trust & automated_trust
        if shared_trust:
            raise MergeGateError(
                "human R5 and automated evidence trust stores share signing keys: "
                f"{sorted(shared_trust)}"
            )
        automated_manifest = validate_automated_evidence(
            args.automated_run_dir,
            allowed_signers=automated_allowed_signers,
            allowed_signers_snapshot=automated_allowed_snapshot,
            head_sha=artifact["head_sha"],
            expected_manifest_sha256=artifact["automated_evidence_manifest_sha256"],
        )
        if automated_manifest.get("signer_fingerprint") == human_signer_fingerprint:
            raise MergeGateError(
                "human R5 signer key must differ from automated evidence signer key"
            )
        if automated_manifest.get("signer_identity") == artifact["human_identity"]:
            raise MergeGateError(
                "human R5 identity must differ from the automated evidence identity"
            )
        validate_acceptance_log(args.acceptance_log, artifact["acceptance_log_sha256"])
        state = validate_external_state(repo, policy=policy, artifact=artifact)
        summary = {
            "validation": "passed",
            "repository": policy["repository"],
            "pr_number": artifact["pr_number"],
            "head_sha": artifact["head_sha"],
            "human_r5_artifact_verified": True,
            "required_checks_verified": len(policy["required_checks"]),
            "merge_executed": False,
        }
        if not args.execute:
            print(json.dumps(summary, indent=2))
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise MergeGateError(
                "--execute requires a human-operated interactive terminal"
            )
        phrase = f"MERGE PR #{artifact['pr_number']} {artifact['head_sha']}"
        print(f"Type exactly to authorize the bound merge:\n{phrase}")
        if input("> ") != phrase:
            raise MergeGateError("interactive merge authorization did not match")

        # Human think time is unbounded. Re-evaluate freshness after the prompt so
        # an artifact cannot expire while an already-open merge process waits.
        validate_timestamp(
            artifact["verified_at_utc"],
            max_age_hours=policy["r5_max_age_hours"],
        )
        second = validate_external_state(repo, policy=policy, artifact=artifact)
        if second["pr"].get("headRefOid") != state["pr"].get("headRefOid"):
            raise MergeGateError("PR head changed during merge authorization")
        command = build_merge_command(policy, artifact)
        _run(command, repo)
        summary["merge_executed"] = True
        print(json.dumps(summary, indent=2))
        return 0
    except MergeGateError as error:
        print(f"MERGE BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
