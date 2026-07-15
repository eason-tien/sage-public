"""Create and verify signed SAGE evidence manifests."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any
import unicodedata


EVIDENCE_NAMESPACE = "sage-evidence"
EVIDENCE_IDENTITY_DEFAULT = "sage-local"
PUBLIC_KEY_TYPE_RE = re.compile(
    r"(?:ssh-(?:rsa|dss|ed25519)(?:-cert-v01@openssh\.com)?|"
    r"ecdsa-sha2-[A-Za-z0-9@._+-]+|"
    r"sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)"
)
KNOWLEDGE_ARTIFACTS = (
    "briefing.md",
    "task-note.md",
    "Memory.md",
    "Ver.md",
    "post-task.json",
)
REPOSITORY_KNOWLEDGE_ARTIFACTS = (
    "briefing.md",
    "task-note.md",
    "Memory.md",
    "Ver.md",
    "State.json",
    "repository-files.json",
    "post-task.json",
)


class EvidenceError(RuntimeError):
    """Evidence is incomplete, tampered, unsigned, or untrusted."""


def regular_file_bytes(path: Path, label: str = "evidence artifact") -> bytes:
    """Snapshot one regular file without following a replaceable symlink."""

    candidate = path.expanduser().absolute()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        raise EvidenceError(f"{label} is missing or unsafe: {candidate}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceError(f"{label} must be a regular file: {candidate}")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if not stable:
            raise EvidenceError(f"{label} changed while it was being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_publish(path: Path, content: bytes) -> None:
    """Publish generated evidence without following a raced destination symlink."""

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(regular_file_bytes(path)).hexdigest()


def _public_key_fingerprint(key_type: str, encoded_key: str) -> str:
    if not PUBLIC_KEY_TYPE_RE.fullmatch(key_type):
        raise EvidenceError(f"unsupported allowed-signers key type: {key_type}")
    try:
        key_blob = base64.b64decode(encoded_key, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise EvidenceError("allowed-signers contains an invalid public key") from error
    digest = base64.b64encode(hashlib.sha256(key_blob).digest()).decode("ascii")
    return "SHA256:" + digest.rstrip("=")


def allowed_signer_fingerprints(content: bytes) -> set[str]:
    """Return every actual key fingerprint in an OpenSSH allowed-signers snapshot."""

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvidenceError("allowed-signers file is not valid UTF-8") from error
    fingerprints: set[str] = set()
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        key_index = next(
            (
                index
                for index, field in enumerate(fields)
                if PUBLIC_KEY_TYPE_RE.fullmatch(field)
            ),
            None,
        )
        if key_index is None or key_index + 1 >= len(fields):
            raise EvidenceError(f"allowed-signers line {number} has no public key")
        fingerprints.add(
            _public_key_fingerprint(fields[key_index], fields[key_index + 1])
        )
    if not fingerprints:
        raise EvidenceError("allowed-signers file contains no public keys")
    return fingerprints


def verify_sshsig_bytes(
    content: bytes,
    *,
    signature: bytes,
    allowed_signers: bytes,
    identity: str,
    namespace: str,
) -> str:
    """Verify immutable snapshots and return ssh-keygen's actual signer fingerprint."""

    allowed_signer_fingerprints(allowed_signers)
    with tempfile.TemporaryDirectory(prefix="sage-sshsig-") as temporary:
        root = Path(temporary)
        signature_path = root / "signature"
        allowed_path = root / "allowed_signers"
        signature_path.write_bytes(signature)
        allowed_path.write_bytes(allowed_signers)
        os.chmod(signature_path, 0o600)
        os.chmod(allowed_path, 0o600)
        completed = subprocess.run(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(allowed_path),
                "-I",
                identity,
                "-n",
                namespace,
                "-s",
                str(signature_path),
            ],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise EvidenceError(f"signature is invalid or untrusted: {detail}")
    output = (completed.stdout + completed.stderr).decode(errors="replace")
    fingerprint = re.search(r"SHA256:[A-Za-z0-9+/]{43}", output)
    if fingerprint is None:
        raise EvidenceError("ssh-keygen did not report the verified signer fingerprint")
    return fingerprint.group(0)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise EvidenceError(f"duplicate JSON key in knowledge metadata: {key}")
        value[key] = item
    return value


def _normalized_repository_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise EvidenceError(f"invalid repository knowledge path: {value!r}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise EvidenceError("repository knowledge path is not valid UTF-8") from error
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise EvidenceError(f"non-normalized repository knowledge path: {value!r}")
    return value


def _repository_metadata(directory: Path) -> dict[str, Any]:
    metadata_path = directory / "repository-files.json"
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise EvidenceError(
            "required knowledge artifact is missing: repository-files.json"
        )
    try:
        metadata = json.loads(
            metadata_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceError("repository knowledge metadata is invalid JSON") from error
    if not isinstance(metadata, dict) or set(metadata) != {
        "schema_version",
        "vault_path",
        "files",
    }:
        raise EvidenceError("repository knowledge metadata has an invalid schema")
    if metadata["schema_version"] != 1:
        raise EvidenceError("unsupported repository knowledge metadata schema")
    vault_path = metadata["vault_path"]
    if vault_path is not None:
        vault_path = _normalized_repository_path(vault_path)
    files = metadata["files"]
    if not isinstance(files, dict):
        raise EvidenceError("repository knowledge file metadata must be an object")
    if vault_path is None and files:
        raise EvidenceError("external knowledge vault cannot declare repository files")

    normalized: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for raw_path, digest in files.items():
        path = _normalized_repository_path(raw_path)
        if vault_path is None or (
            path != vault_path and not path.startswith(f"{vault_path}/")
        ):
            raise EvidenceError(
                f"repository knowledge file is outside its vault: {path}"
            )
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise EvidenceError(f"invalid repository knowledge digest: {path}")
        alias = unicodedata.normalize("NFC", path).casefold()
        previous = aliases.setdefault(alias, path)
        if previous != path:
            raise EvidenceError(
                f"ambiguous repository knowledge paths: {previous!r} and {path!r}"
            )
        normalized[path] = digest
    return {"schema_version": 1, "vault_path": vault_path, "files": normalized}


def _repository_tree_files(root: Path) -> set[str]:
    if not root.is_dir() or root.is_symlink():
        raise EvidenceError("repository knowledge snapshot tree is missing or unsafe")
    files: set[str] = set()
    for current, directories, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise EvidenceError("repository knowledge snapshot contains a symlink")
        for name in names:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise EvidenceError(
                    "repository knowledge snapshot has a non-regular file"
                )
            relative = path.relative_to(root).as_posix()
            _normalized_repository_path(relative)
            files.add(relative)
    return files


def _knowledge_hashes(run_dir: Path, *, legacy: bool = False) -> dict[str, str]:
    directory = run_dir / "knowledge"
    if not directory.is_dir() or directory.is_symlink():
        raise EvidenceError("knowledge artifact directory is missing or unsafe")
    hashes: dict[str, str] = {}
    artifacts = KNOWLEDGE_ARTIFACTS if legacy else REPOSITORY_KNOWLEDGE_ARTIFACTS
    for name in artifacts:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise EvidenceError(f"required knowledge artifact is missing: {name}")
        hashes[name] = sha256_file(path)
    if legacy:
        return hashes

    metadata = _repository_metadata(directory)
    repository_tree = directory / "repository"
    actual_files = _repository_tree_files(repository_tree)
    declared_files = set(metadata["files"])
    if actual_files != declared_files:
        missing = sorted(declared_files - actual_files)
        undeclared = sorted(actual_files - declared_files)
        raise EvidenceError(
            "repository knowledge snapshot file set does not match metadata: "
            f"missing={missing}, undeclared={undeclared}"
        )
    for relative, expected_digest in metadata["files"].items():
        path = repository_tree.joinpath(*relative.split("/"))
        actual_digest = sha256_file(path)
        if actual_digest != expected_digest:
            raise EvidenceError(f"repository knowledge hash mismatch: {relative}")
        hashes[f"repository/{relative}"] = actual_digest
    return hashes


def load_signed_repository_files(
    run_dir: Path, manifest: dict[str, Any]
) -> dict[str, Any] | None:
    signed = manifest.get("artifacts", {}).get("knowledge_artifacts_sha256")
    if not isinstance(signed, dict) or "repository-files.json" not in signed:
        return None
    current = _knowledge_hashes(run_dir)
    if current != signed:
        raise EvidenceError("signed repository knowledge hashes no longer match")
    metadata = _repository_metadata(run_dir / "knowledge")
    repository_tree = run_dir / "knowledge" / "repository"
    return {
        "vault_path": metadata["vault_path"],
        "files": {
            relative: {
                "path": repository_tree.joinpath(*relative.split("/")),
                "sha256": digest,
            }
            for relative, digest in metadata["files"].items()
        },
    }


def _fingerprint(public_key: Path) -> str:
    completed = subprocess.run(
        ["ssh-keygen", "-lf", str(public_key), "-E", "sha256"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise EvidenceError(f"cannot fingerprint signing key: {completed.stderr}")
    fields = completed.stdout.split()
    if len(fields) < 2:
        raise EvidenceError("ssh-keygen returned no signing-key fingerprint")
    return fields[1]


def build_manifest(run_dir: Path, *, signer_identity: str) -> dict[str, Any]:
    result_path = run_dir / "result.json"
    patch_path = run_dir / "final.patch"
    budget_path = run_dir / "budget.json"
    if not result_path.is_file() or not patch_path.is_file():
        raise EvidenceError("run must contain result.json and final.patch")
    result_bytes = regular_file_bytes(result_path, "workflow result")
    patch_bytes = regular_file_bytes(patch_path, "candidate patch")
    budget_bytes = (
        regular_file_bytes(budget_path, "workflow budget")
        if budget_path.is_file()
        else None
    )
    try:
        result = json.loads(result_bytes, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceError("workflow result is invalid JSON") from error
    if not isinstance(result, dict) or result.get("schema_version") != 1:
        raise EvidenceError("workflow result has no supported schema version")
    execution_kind = result.get("execution_kind")
    if execution_kind not in {
        "agent_workflow",
        "post_implementation_attestation",
    }:
        raise EvidenceError("workflow result has no supported execution kind")
    automated = result.get("automated_gates_passed", result.get("passed"))
    if automated is not True or result.get("final_gates", {}).get("passed") is not True:
        raise EvidenceError("cannot sign a run whose automated gates did not pass")
    if result.get("r5_human_verification", "pending") != "pending":
        raise EvidenceError("agent-produced evidence must leave R5 pending")
    if result.get("merge_authorized", False) is not False:
        raise EvidenceError("agent-produced evidence must not authorize merge")
    promotion = result.get("promotion_manifest", {})
    patch_hash = hashlib.sha256(patch_bytes).hexdigest()
    if not patch_bytes.strip():
        raise EvidenceError("cannot sign an empty candidate patch")
    if promotion.get("final_patch_sha256") != patch_hash:
        raise EvidenceError("final.patch does not match the workflow result")
    changed_files = promotion.get("changed_files")
    if (
        not isinstance(changed_files, list)
        or not changed_files
        or not all(isinstance(path, str) and path for path in changed_files)
    ):
        raise EvidenceError("cannot sign evidence without changed files")
    stages = result.get("stages")
    if execution_kind == "agent_workflow":
        if (
            not isinstance(stages, list)
            or not stages
            or any(
                not isinstance(stage, dict) or stage.get("exit_code") != 0
                for stage in stages
            )
        ):
            raise EvidenceError(
                "cannot sign agent-workflow evidence with missing or failed agent stages"
            )
    elif stages != []:
        raise EvidenceError("post-implementation attestation must have no agent stages")
    acceptance_commands = promotion.get("acceptance_commands")
    if not isinstance(acceptance_commands, list) or not acceptance_commands:
        raise EvidenceError("workflow result has no acceptance commands")
    final_checks = result["final_gates"].get("checks", {})
    if execution_kind == "post_implementation_attestation":
        attested_head = result.get("contract", {}).get("attested_head")
        if not isinstance(attested_head, str) or not re.fullmatch(
            r"[0-9a-f]{40}", attested_head
        ):
            raise EvidenceError("attestation is not bound to an exact repository HEAD")
        required_attestation_checks = {
            "repository_immutability",
            "diff_check",
            "gitleaks",
        }
        acceptance_checks = [
            check
            for name, check in final_checks.items()
            if isinstance(name, str) and name.startswith("acceptance_")
        ]
        required_checks = [
            final_checks.get(name) for name in required_attestation_checks
        ]
        if not acceptance_checks or any(
            not isinstance(check, dict) or check.get("exit_code") != 0
            for check in [*required_checks, *acceptance_checks]
        ):
            raise EvidenceError(
                "attestation requires immutable repository, diff, secret, and acceptance gates"
            )
    knowledge_hashes = None
    knowledge = result.get("knowledge")
    if knowledge is not None:
        if (
            knowledge.get("memory_distilled") is not True
            or knowledge.get("codegraph_current") is not True
            or knowledge.get("version_bumped") is not True
        ):
            raise EvidenceError(
                "successful evidence requires distilled memory, CodeGraph, and version bump"
            )
        knowledge_hashes = _knowledge_hashes(run_dir)
        try:
            declared = dict(knowledge.get("artifacts", {}))
        except (TypeError, ValueError) as error:
            raise EvidenceError(
                "knowledge artifact hashes must be an object"
            ) from error
        expected_snapshot_names = set(knowledge_hashes) - {"post-task.json"}
        if set(declared) != expected_snapshot_names or any(
            knowledge_hashes.get(name) != digest for name, digest in declared.items()
        ):
            raise EvidenceError("knowledge snapshot hashes do not match result.json")
        if knowledge_hashes["post-task.json"] != knowledge.get("post_task_sha256"):
            raise EvidenceError("post-task knowledge summary hash does not match")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "SAGE Evidence",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "signer_identity": signer_identity,
        "run": {
            "name": result.get("name"),
            "route": result.get("route"),
            "execution_kind": execution_kind,
            "source_repo": result.get("contract", {}).get("source_repo"),
            "source_head": result.get("contract", {}).get("source_head"),
            "attested_head": result.get("contract", {}).get("attested_head"),
        },
        "artifacts": {
            "result_json_sha256": hashlib.sha256(result_bytes).hexdigest(),
            "final_patch_sha256": patch_hash,
            "budget_json_sha256": (
                hashlib.sha256(budget_bytes).hexdigest()
                if budget_bytes is not None
                else None
            ),
            "knowledge_artifacts_sha256": knowledge_hashes,
        },
        "acceptance": {
            "commands_sha256": hashlib.sha256(
                canonical_json(acceptance_commands)
            ).hexdigest(),
            "checks_sha256": hashlib.sha256(canonical_json(final_checks)).hexdigest(),
            "count": len(acceptance_commands),
        },
        "scope": {"changed_files": changed_files},
        "budget": result.get("budget"),
        "knowledge": knowledge,
        "state": {
            "automated_gates_passed": True,
            "r5_human_verification": "pending",
            "merge_authorized": False,
        },
    }
    return manifest


def write_signed_manifest(
    run_dir: Path,
    *,
    signing_key: Path,
    signer_identity: str = EVIDENCE_IDENTITY_DEFAULT,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    signing_key = signing_key.expanduser().resolve()
    public_key = Path(f"{signing_key}.pub")
    if not signing_key.is_file() or not public_key.is_file():
        raise EvidenceError("signing key and matching .pub file are required")
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(exist_ok=False)
    manifest = build_manifest(run_dir, signer_identity=signer_identity)
    manifest["signer_fingerprint"] = _fingerprint(public_key)
    manifest_bytes = canonical_json(manifest)
    completed = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(signing_key),
            "-n",
            EVIDENCE_NAMESPACE,
        ],
        input=manifest_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    signature_bytes = completed.stdout
    manifest_path = evidence_dir / "manifest.json"
    signature_path = Path(f"{manifest_path}.sig")
    if completed.returncode != 0 or not signature_bytes.strip():
        detail = completed.stderr.decode("utf-8", errors="replace")
        raise EvidenceError(f"evidence signing failed: {detail}")
    public_fields = regular_file_bytes(public_key, "evidence public key").split()
    if len(public_fields) < 2:
        raise EvidenceError("evidence public key is invalid")
    allowed_snapshot = (
        signer_identity.encode("utf-8")
        + b" "
        + public_fields[0]
        + b" "
        + public_fields[1]
        + b"\n"
    )
    actual_fingerprint = verify_sshsig_bytes(
        manifest_bytes,
        signature=signature_bytes,
        allowed_signers=allowed_snapshot,
        identity=signer_identity,
        namespace=EVIDENCE_NAMESPACE,
    )
    if actual_fingerprint != manifest["signer_fingerprint"]:
        raise EvidenceError("signing key changed while evidence was being signed")
    _atomic_publish(manifest_path, manifest_bytes)
    _atomic_publish(signature_path, signature_bytes)
    return {
        "manifest": str(manifest_path),
        "signature": str(signature_path),
        "signer_identity": signer_identity,
        "signer_fingerprint": manifest["signer_fingerprint"],
    }


def verify_signed_manifest(
    run_dir: Path,
    *,
    allowed_signers: Path,
    allowed_signers_snapshot: bytes | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest_path = run_dir / "evidence" / "manifest.json"
    signature_path = Path(f"{manifest_path}.sig")
    allowed_signers = allowed_signers.expanduser().resolve()
    manifest_bytes = regular_file_bytes(manifest_path, "SAGE evidence manifest")
    signature_bytes = regular_file_bytes(signature_path, "SAGE evidence signature")
    allowed_signers_bytes = (
        allowed_signers_snapshot
        if allowed_signers_snapshot is not None
        else regular_file_bytes(allowed_signers, "trusted allowed-signers file")
    )
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if (
        expected_manifest_sha256 is not None
        and manifest_sha256 != expected_manifest_sha256
    ):
        raise EvidenceError(
            "signed evidence manifest does not match the expected digest"
        )
    try:
        manifest = json.loads(manifest_bytes, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceError("evidence manifest is invalid JSON") from error
    if not isinstance(manifest, dict):
        raise EvidenceError("evidence manifest must be a JSON object")
    identity = manifest.get("signer_identity")
    if not isinstance(identity, str) or not identity:
        raise EvidenceError("evidence manifest has no signer identity")
    actual_fingerprint = verify_sshsig_bytes(
        manifest_bytes,
        signature=signature_bytes,
        allowed_signers=allowed_signers_bytes,
        identity=identity,
        namespace=EVIDENCE_NAMESPACE,
    )
    if manifest.get("signer_fingerprint") != actual_fingerprint:
        raise EvidenceError(
            "evidence signer fingerprint does not match the verified key"
        )
    result_path = run_dir / "result.json"
    patch_path = run_dir / "final.patch"
    budget_path = run_dir / "budget.json"
    expected = manifest.get("artifacts", {})
    result_bytes = regular_file_bytes(result_path, "workflow result")
    patch_bytes = regular_file_bytes(patch_path, "candidate patch")
    budget_bytes = (
        regular_file_bytes(budget_path, "workflow budget")
        if budget_path.is_file()
        else None
    )
    artifacts = {
        "result_json_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "final_patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
        "budget_json_sha256": (
            hashlib.sha256(budget_bytes).hexdigest()
            if budget_bytes is not None
            else None
        ),
    }
    if "knowledge_artifacts_sha256" in expected:
        signed_knowledge = expected.get("knowledge_artifacts_sha256")
        if signed_knowledge is None:
            artifacts["knowledge_artifacts_sha256"] = None
        elif not isinstance(signed_knowledge, dict):
            raise EvidenceError("signed knowledge artifact hashes are invalid")
        else:
            legacy = set(signed_knowledge) == set(KNOWLEDGE_ARTIFACTS)
            artifacts["knowledge_artifacts_sha256"] = _knowledge_hashes(
                run_dir, legacy=legacy
            )
    if artifacts != expected:
        raise EvidenceError("signed evidence artifact hashes do not match the run")
    try:
        result = json.loads(result_bytes, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceError("signed workflow result is invalid JSON") from error
    promotion = result.get("promotion_manifest", {})
    contract = result.get("contract", {})
    final_checks = result.get("final_gates", {}).get("checks", {})
    acceptance_commands = promotion.get("acceptance_commands")
    expected_run = {
        "name": result.get("name"),
        "route": result.get("route"),
        "execution_kind": result.get("execution_kind"),
        "source_repo": contract.get("source_repo"),
        "source_head": contract.get("source_head"),
        "attested_head": contract.get("attested_head"),
    }
    if manifest.get("run") != expected_run:
        raise EvidenceError("signed manifest run identity does not match result.json")
    expected_acceptance = {
        "commands_sha256": hashlib.sha256(
            canonical_json(acceptance_commands)
        ).hexdigest(),
        "checks_sha256": hashlib.sha256(canonical_json(final_checks)).hexdigest(),
        "count": len(acceptance_commands)
        if isinstance(acceptance_commands, list)
        else -1,
    }
    if manifest.get("acceptance") != expected_acceptance:
        raise EvidenceError("signed manifest acceptance does not match result.json")
    if manifest.get("scope") != {"changed_files": promotion.get("changed_files")}:
        raise EvidenceError("signed manifest scope does not match result.json")
    state = manifest.get("state", {})
    if state != {
        "automated_gates_passed": True,
        "r5_human_verification": "pending",
        "merge_authorized": False,
    }:
        raise EvidenceError("signed evidence contains an unsafe workflow state")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign or verify SAGE evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    sign = subparsers.add_parser("sign")
    sign.add_argument("--run", type=Path, required=True)
    sign.add_argument("--key", type=Path, required=True)
    sign.add_argument("--identity", default=EVIDENCE_IDENTITY_DEFAULT)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--run", type=Path, required=True)
    verify.add_argument("--allowed-signers", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "sign":
        output = write_signed_manifest(
            args.run, signing_key=args.key, signer_identity=args.identity
        )
    else:
        output = verify_signed_manifest(args.run, allowed_signers=args.allowed_signers)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
