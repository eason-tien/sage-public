"""Fail-closed public export of a private, oracle-bearing SAGE repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import unicodedata

from workflow.evidence import (
    EvidenceError,
    allowed_signer_fingerprints,
    canonical_json,
    regular_file_bytes,
    verify_signed_manifest,
    verify_sshsig_bytes,
)


EXPORT_NAMESPACE = "sage-public-export"
CERTIFICATE_PATH = ".sage-public-export/certificate.json"
SIGNATURE_PATH = f"{CERTIFICATE_PATH}.sig"
EXPORT_EXCLUDED_PATHS = frozenset({CERTIFICATE_PATH, SIGNATURE_PATH})
ORACLE_BLOCKED_PREFIXES = (
    "benchmarks/hidden/",
    "benchmarks/sprite-game-hidden/",
)
SOURCE_EXCLUDED_PREFIXES = (
    *ORACLE_BLOCKED_PREFIXES,
    ".sage-public-export/",
)
PRIVATE_SOURCE_PATHS = frozenset(
    {
        ".github/sage-merge-policy.json",
        ".github/workflows/ci.yml",
    }
)
PUBLIC_TEMPLATE_MAP = {
    "templates/github/public-ci.yml": ".github/workflows/ci.yml",
    "templates/github/public-oracle.yml": ".github/workflows/private-oracle.yml",
    "templates/github/sage-public-merge-policy.json": (
        ".github/sage-merge-policy.json"
    ),
}
BOOTSTRAP_PATHS = (
    ".gitignore",
    "LICENSE",
    "README.md",
    ".github/workflows/ci.yml",
    ".github/workflows/private-oracle.yml",
    "tools/verify_public_export.py",
    "workflow/evidence.py",
    "workflow/public_export.py",
    "workflow/trusted_signers",
)
REQUIRED_PRIVATE_ACCEPTANCE = (
    "python3 tools/lab.py verify-fixture",
    "python3 tools/audit_sprite_game.py --no-write",
    "python3 tools/check_version_record.py",
)
REQUIRED_ATTESTATION_CHECKS = (
    "candidate_symlink_boundary",
    "candidate_materialization",
    "gitleaks",
    "candidate_symlink_boundary_post",
    "materialized_candidate_immutability",
    "diff_check",
    "repository_immutability",
)
CERTIFICATE_FIELDS = {
    "schema_version",
    "kind",
    "repository",
    "source_repository",
    "source_head",
    "source_tree_sha256",
    "public_tree_sha256",
    "automated_evidence_manifest_sha256",
    "automated_evidence_signer_fingerprint",
    "signer_identity",
    "signer_fingerprint",
    "created_at_utc",
    "private_oracle_gates_passed",
    "export_secret_scan_passed",
    "automated_gates_passed",
    "r5_human_verification",
    "merge_authorized",
}
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
FINGERPRINT_RE = re.compile(r"SHA256:[A-Za-z0-9+/]{43}")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class PublicExportError(RuntimeError):
    """A public export invariant was missing, ambiguous, or false."""


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: str
    object_type: str
    object_id: str


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PublicExportError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_CONFIG_SYSTEM"] = os.devnull
    environment.pop("GIT_INDEX_FILE", None)
    environment.pop("GIT_OBJECT_DIRECTORY", None)
    environment.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
    return environment


def _git(
    repo: Path,
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_git_environment(),
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PublicExportError(detail or f"git {' '.join(arguments)} failed")
    return completed.stdout


def resolve_commit(repo: Path, ref: str) -> str:
    commit = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    if not COMMIT_RE.fullmatch(commit):
        raise PublicExportError("source ref did not resolve to one exact commit")
    return commit


def _normalized_path(value: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise PublicExportError(f"unsafe repository path: {value!r}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise PublicExportError("repository path is not valid UTF-8") from error
    return value


def tree_entries(repo: Path, treeish: str) -> list[TreeEntry]:
    output = _git(repo, "ls-tree", "-r", "-z", treeish)
    entries: list[TreeEntry] = []
    aliases: dict[str, str] = {}
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, separator, raw_path = raw.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise PublicExportError("Git tree contains an ambiguous entry")
        path = _normalized_path(os.fsdecode(raw_path))
        alias = unicodedata.normalize("NFC", path).casefold()
        previous = aliases.setdefault(alias, path)
        if previous != path:
            raise PublicExportError(
                f"ambiguous repository paths: {previous!r} and {path!r}"
            )
        entries.append(
            TreeEntry(
                path=path,
                mode=fields[0].decode("ascii"),
                object_type=fields[1].decode("ascii"),
                object_id=fields[2].decode("ascii"),
            )
        )
    return entries


def _source_excluded(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in SOURCE_EXCLUDED_PREFIXES)


def _oracle_blocked(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in ORACLE_BLOCKED_PREFIXES)


def _public_path(source_path: str) -> str | None:
    if _source_excluded(source_path) or source_path in PRIVATE_SOURCE_PATHS:
        return None
    return PUBLIC_TEMPLATE_MAP.get(source_path, source_path)


def _safe_blob(entry: TreeEntry) -> None:
    if entry.object_type != "blob" or entry.mode not in {"100644", "100755"}:
        raise PublicExportError(
            f"public export rejects non-regular tracked entry: {entry.path}"
        )


def _selected_public_entries(
    source_repo: Path,
    source_commit: str,
) -> dict[str, TreeEntry]:
    entries = tree_entries(source_repo, source_commit)
    blocked_object_ids = {
        entry.object_id for entry in entries if _source_excluded(entry.path)
    }
    selected: dict[str, TreeEntry] = {}
    aliases: dict[str, str] = {}
    for entry in entries:
        output_path = _public_path(entry.path)
        if output_path is None:
            continue
        output_path = _normalized_path(output_path)
        _safe_blob(entry)
        if entry.object_id in blocked_object_ids:
            raise PublicExportError(
                f"public path duplicates an excluded oracle blob: {output_path}"
            )
        alias = unicodedata.normalize("NFC", output_path).casefold()
        previous = aliases.setdefault(alias, output_path)
        if previous != output_path or output_path in selected:
            raise PublicExportError(f"public export path collision: {output_path}")
        selected[output_path] = entry

    required = set(PUBLIC_TEMPLATE_MAP.values()) | {
        "tools/verify_public_export.py",
        "workflow/public_export.py",
        "workflow/evidence.py",
        "workflow/trusted_signers",
    }
    missing = sorted(required - set(selected))
    if missing:
        raise PublicExportError(f"public export is missing trusted files: {missing}")
    return selected


def materialize_public_snapshot(
    source_repo: Path,
    source_commit: str,
    destination: Path,
) -> list[str]:
    """Materialize one sanitized source commit without copying its Git history."""

    source_repo = source_repo.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise PublicExportError(f"public snapshot destination exists: {destination}")
    selected = _selected_public_entries(source_repo, source_commit)

    destination.mkdir(parents=True)
    for output_path, entry in sorted(selected.items()):
        path = destination.joinpath(*output_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        content = _git(source_repo, "cat-file", "blob", entry.object_id)
        path.write_bytes(content)
        os.chmod(path, 0o755 if entry.mode == "100755" else 0o644)
    return sorted(selected)


def _update_digest(
    hasher: Any,
    *,
    mode: str,
    path: str,
    content: bytes,
) -> None:
    path_bytes = os.fsencode(path)
    hasher.update(mode.encode("ascii"))
    hasher.update(b"\0")
    hasher.update(str(len(path_bytes)).encode("ascii"))
    hasher.update(b"\0")
    hasher.update(path_bytes)
    hasher.update(b"\0")
    hasher.update(str(len(content)).encode("ascii"))
    hasher.update(b"\0")
    hasher.update(content)
    hasher.update(b"\0")


def tree_sha256(
    repo: Path,
    treeish: str,
    *,
    excluded_paths: frozenset[str] = frozenset(),
) -> str:
    hasher = hashlib.sha256()
    for entry in sorted(tree_entries(repo, treeish), key=lambda item: item.path):
        if entry.path in excluded_paths:
            continue
        _safe_blob(entry)
        content = _git(repo, "cat-file", "blob", entry.object_id)
        _update_digest(
            hasher,
            mode=entry.mode,
            path=entry.path,
            content=content,
        )
    return hasher.hexdigest()


def public_source_tree_sha256(source_repo: Path, source_commit: str) -> str:
    """Hash the sanitized public tree directly from immutable source blobs."""

    hasher = hashlib.sha256()
    selected = _selected_public_entries(source_repo, source_commit)
    for path, entry in sorted(selected.items()):
        content = _git(source_repo, "cat-file", "blob", entry.object_id)
        _update_digest(hasher, mode=entry.mode, path=path, content=content)
    return hasher.hexdigest()


def _successful_check(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and type(value.get("exit_code")) is int
        and value["exit_code"] == 0
    )


def validate_private_attestation(
    run_dir: Path,
    *,
    allowed_signers: Path,
    source_head: str,
) -> dict[str, Any]:
    """Require signed, exact-head evidence that explicitly ran private oracle gates."""

    try:
        manifest_bytes = regular_file_bytes(
            run_dir / "evidence" / "manifest.json",
            "attestation manifest",
        )
        result_bytes = regular_file_bytes(run_dir / "result.json", "attestation result")
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = verify_signed_manifest(
            run_dir,
            allowed_signers=allowed_signers,
            expected_manifest_sha256=manifest_digest,
        )
    except EvidenceError as error:
        raise PublicExportError(f"private attestation is invalid: {error}") from error
    try:
        result = json.loads(result_bytes, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PublicExportError("private attestation result is invalid JSON") from error
    if not isinstance(result, dict) or not isinstance(manifest, dict):
        raise PublicExportError("private attestation result must be an object")
    artifacts = manifest.get("artifacts")
    run = manifest.get("run")
    signer_fingerprint = manifest.get("signer_fingerprint")
    if (
        not isinstance(artifacts, dict)
        or artifacts.get("result_json_sha256")
        != hashlib.sha256(result_bytes).hexdigest()
    ):
        raise PublicExportError("private attestation result snapshot is not signed")
    if not isinstance(run, dict) or run.get("execution_kind") != (
        "post_implementation_attestation"
    ):
        raise PublicExportError("private evidence is not a repository attestation")
    if run.get("attested_head") != source_head:
        raise PublicExportError("private evidence is not bound to the source head")
    if not isinstance(signer_fingerprint, str) or not FINGERPRINT_RE.fullmatch(
        signer_fingerprint
    ):
        raise PublicExportError("private evidence signer fingerprint is invalid")
    final_gates = result.get("final_gates")
    if (
        result.get("automated_gates_passed") is not True
        or result.get("r5_human_verification") != "pending"
        or result.get("merge_authorized") is not False
        or not isinstance(final_gates, dict)
        or final_gates.get("passed") is not True
    ):
        raise PublicExportError("private attestation has an unsafe state")

    promotion = result.get("promotion_manifest")
    if not isinstance(promotion, dict):
        raise PublicExportError("private attestation promotion manifest is missing")
    commands = promotion.get("acceptance_commands")
    checks = final_gates.get("checks")
    if not isinstance(commands, list) or not isinstance(checks, dict):
        raise PublicExportError("private attestation acceptance is missing")
    for required in REQUIRED_PRIVATE_ACCEPTANCE:
        positions = [
            index for index, command in enumerate(commands) if command == required
        ]
        if len(positions) != 1:
            raise PublicExportError(
                f"private attestation must contain exactly one gate: {required}"
            )
        check = checks.get(f"acceptance_{positions[0] + 1}")
        if not _successful_check(check):
            raise PublicExportError(
                f"private attestation gate did not pass: {required}"
            )
    for name in REQUIRED_ATTESTATION_CHECKS:
        check = checks.get(name)
        if not _successful_check(check):
            raise PublicExportError(f"private attestation check did not pass: {name}")

    return {
        "manifest_sha256": manifest_digest,
        "signer_fingerprint": signer_fingerprint,
    }


def _signer_snapshot(signing_key: Path, identity: str) -> tuple[bytes, str]:
    public_key = Path(f"{signing_key}.pub")
    content = regular_file_bytes(public_key, "public export signing key")
    fields = content.split()
    if len(fields) < 2:
        raise PublicExportError("public export signing key is invalid")
    allowed = identity.encode() + b" " + fields[0] + b" " + fields[1] + b"\n"
    try:
        fingerprints = allowed_signer_fingerprints(allowed)
    except EvidenceError as error:
        raise PublicExportError(str(error)) from error
    if len(fingerprints) != 1:
        raise PublicExportError("public export signer is ambiguous")
    return allowed, next(iter(fingerprints))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_export_certificate(
    repo: Path,
    certificate: dict[str, Any],
    *,
    signing_key: Path,
    signer_identity: str,
    allowed_signers: Path,
) -> dict[str, Any]:
    if set(certificate) != CERTIFICATE_FIELDS - {"signer_fingerprint"}:
        raise PublicExportError("public export certificate input schema is invalid")
    signer_snapshot, fingerprint = _signer_snapshot(signing_key, signer_identity)
    certificate = {**certificate, "signer_fingerprint": fingerprint}
    content = canonical_json(certificate)
    completed = subprocess.run(
        [
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(signing_key.expanduser().resolve()),
            "-n",
            EXPORT_NAMESPACE,
        ],
        input=content,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    signature = completed.stdout
    if completed.returncode != 0 or not signature.strip():
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise PublicExportError(f"public export signing failed: {detail}")
    trusted = regular_file_bytes(allowed_signers, "public export allowed-signers")
    try:
        generated_fingerprint = verify_sshsig_bytes(
            content,
            signature=signature,
            allowed_signers=signer_snapshot,
            identity=signer_identity,
            namespace=EXPORT_NAMESPACE,
        )
        trusted_fingerprint = verify_sshsig_bytes(
            content,
            signature=signature,
            allowed_signers=trusted,
            identity=signer_identity,
            namespace=EXPORT_NAMESPACE,
        )
    except EvidenceError as error:
        raise PublicExportError(
            f"public export signature is untrusted: {error}"
        ) from error
    if generated_fingerprint != fingerprint or trusted_fingerprint != fingerprint:
        raise PublicExportError("public export signing key changed while signing")
    _atomic_write(repo / CERTIFICATE_PATH, content)
    _atomic_write(repo / SIGNATURE_PATH, signature)
    return certificate


def _validate_certificate_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CERTIFICATE_FIELDS:
        raise PublicExportError("public export certificate schema is invalid")
    if value["schema_version"] != 1 or value["kind"] != "SAGE Public Export":
        raise PublicExportError("unsupported public export certificate")
    for field in ("repository", "source_repository"):
        if not isinstance(value[field], str) or not REPOSITORY_RE.fullmatch(
            value[field]
        ):
            raise PublicExportError(f"public export {field} is invalid")
    if not isinstance(value["source_head"], str) or not COMMIT_RE.fullmatch(
        value["source_head"]
    ):
        raise PublicExportError("public export source head is invalid")
    for field in (
        "source_tree_sha256",
        "public_tree_sha256",
        "automated_evidence_manifest_sha256",
    ):
        if not isinstance(value[field], str) or not SHA256_RE.fullmatch(value[field]):
            raise PublicExportError(f"public export {field} is invalid")
    for field in ("automated_evidence_signer_fingerprint", "signer_fingerprint"):
        if not isinstance(value[field], str) or not FINGERPRINT_RE.fullmatch(
            value[field]
        ):
            raise PublicExportError(f"public export {field} is invalid")
    if not isinstance(value["signer_identity"], str) or not value["signer_identity"]:
        raise PublicExportError("public export signer identity is invalid")
    timestamp = value["created_at_utc"]
    if not isinstance(timestamp, str):
        raise PublicExportError("public export timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise PublicExportError("public export timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise PublicExportError("public export timestamp needs a timezone")
    if (
        value["private_oracle_gates_passed"] is not True
        or value["export_secret_scan_passed"] is not True
        or value["automated_gates_passed"] is not True
        or value["r5_human_verification"] != "pending"
        or value["merge_authorized"] is not False
    ):
        raise PublicExportError("public export certificate has an unsafe state")
    return value


def verify_public_export(
    repo: Path,
    *,
    allowed_signers: Path,
    expected_repository: str | None = None,
    expected_source_repository: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    head = resolve_commit(repo, "HEAD")
    status_output = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if status_output.strip():
        raise PublicExportError("public export repository must be clean")
    entries = tree_entries(repo, head)
    leaked = sorted(entry.path for entry in entries if _oracle_blocked(entry.path))
    if leaked:
        raise PublicExportError(f"public export contains blocked paths: {leaked}")
    paths = {entry.path for entry in entries}
    unexpected_certificate_files = sorted(
        path
        for path in paths
        if path.startswith(".sage-public-export/") and path not in EXPORT_EXCLUDED_PATHS
    )
    if unexpected_certificate_files:
        raise PublicExportError(
            "public export contains unexpected certificate files: "
            f"{unexpected_certificate_files}"
        )
    if CERTIFICATE_PATH not in paths or SIGNATURE_PATH not in paths:
        raise PublicExportError("public export certificate or signature is missing")
    certificate_bytes = _git(repo, "show", f"{head}:{CERTIFICATE_PATH}")
    signature_bytes = _git(repo, "show", f"{head}:{SIGNATURE_PATH}")
    try:
        certificate = json.loads(
            certificate_bytes,
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise PublicExportError("public export certificate is invalid JSON") from error
    certificate = _validate_certificate_schema(certificate)
    if (
        expected_repository is not None
        and certificate["repository"] != expected_repository
    ):
        raise PublicExportError("public export repository identity does not match")
    if (
        expected_source_repository is not None
        and certificate["source_repository"] != expected_source_repository
    ):
        raise PublicExportError("public export source repository does not match")
    trusted = regular_file_bytes(allowed_signers, "public export allowed-signers")
    try:
        fingerprint = verify_sshsig_bytes(
            certificate_bytes,
            signature=signature_bytes,
            allowed_signers=trusted,
            identity=certificate["signer_identity"],
            namespace=EXPORT_NAMESPACE,
        )
    except EvidenceError as error:
        raise PublicExportError(
            f"public export signature is invalid: {error}"
        ) from error
    if fingerprint != certificate["signer_fingerprint"]:
        raise PublicExportError("public export signer fingerprint does not match")
    digest = tree_sha256(repo, head, excluded_paths=EXPORT_EXCLUDED_PATHS)
    if digest != certificate["public_tree_sha256"]:
        raise PublicExportError("public export tree does not match its certificate")
    return {
        "passed": True,
        "repository": certificate["repository"],
        "head_sha": head,
        "source_repository": certificate["source_repository"],
        "source_head": certificate["source_head"],
        "public_tree_sha256": digest,
        "signer_identity": certificate["signer_identity"],
        "signer_fingerprint": fingerprint,
        "r5_human_verification": "pending",
        "merge_authorized": False,
    }


def _copy_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise PublicExportError(f"bootstrap source is unsafe: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=False)


def _copy_snapshot(source: Path, destination: Path) -> None:
    for item in source.iterdir():
        target = destination / item.name
        if item.is_symlink():
            raise PublicExportError(f"public snapshot contains a symlink: {item}")
        if item.is_dir():
            shutil.copytree(item, target, copy_function=shutil.copy2)
        elif item.is_file():
            shutil.copy2(item, target, follow_symlinks=False)
        else:
            raise PublicExportError(f"public snapshot contains an unsafe entry: {item}")


def _clear_worktree(repo: Path) -> None:
    for item in repo.iterdir():
        if item.name == ".git":
            continue
        if item.is_symlink() or item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
        else:
            raise PublicExportError(f"cannot clear unsafe worktree entry: {item}")


def secret_scan(snapshot: Path) -> None:
    try:
        completed = subprocess.run(
            [
                "gitleaks",
                "detect",
                "--no-git",
                "--redact",
                "--source",
                str(snapshot),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise PublicExportError(
            f"public export secret scan unavailable: {error}"
        ) from error
    if completed.returncode != 0:
        raise PublicExportError("public export secret scan failed: " + completed.stdout)


def prepare_public_repository(
    source_repo: Path,
    source_ref: str,
    destination: Path,
    *,
    source_repository: str,
    public_repository: str,
    branch: str,
    attestation_run: Path,
    attestation_allowed_signers: Path,
    signing_key: Path,
    signer_identity: str,
) -> dict[str, Any]:
    """Create a two-commit public repository with no private source history."""

    source_repo = source_repo.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise PublicExportError(f"public repository destination exists: {destination}")
    if not REPOSITORY_RE.fullmatch(source_repository) or not REPOSITORY_RE.fullmatch(
        public_repository
    ):
        raise PublicExportError("source or public repository identity is invalid")
    if not branch.startswith("codex/"):
        raise PublicExportError("public candidate branch must use the codex/ prefix")
    source_head = resolve_commit(source_repo, source_ref)
    attestation = validate_private_attestation(
        attestation_run.resolve(),
        allowed_signers=attestation_allowed_signers.resolve(),
        source_head=source_head,
    )
    source_tree_digest = tree_sha256(source_repo, source_head)
    expected_public_tree_digest = public_source_tree_sha256(source_repo, source_head)

    with tempfile.TemporaryDirectory(prefix="sage-public-snapshot-") as temporary:
        snapshot = Path(temporary) / "snapshot"
        exported_files = materialize_public_snapshot(
            source_repo,
            source_head,
            snapshot,
        )
        secret_scan(snapshot)

        destination.mkdir(parents=True)
        _git(destination, "init", "-q", "-b", "master")
        _git(destination, "config", "user.name", "SAGE Public Export")
        _git(
            destination,
            "config",
            "user.email",
            "sage-public-export@example.invalid",
        )
        for relative in BOOTSTRAP_PATHS:
            _copy_file(
                snapshot.joinpath(*relative.split("/")),
                destination.joinpath(*relative.split("/")),
            )
        _git(destination, "add", "--all")
        _git(
            destination,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "bootstrap trusted public export gate",
        )
        bootstrap_head = resolve_commit(destination, "HEAD")
        _git(destination, "switch", "-q", "-c", branch)
        _clear_worktree(destination)
        _copy_snapshot(snapshot, destination)
        _git(destination, "add", "--all")
        pre_certificate_tree = _git(destination, "write-tree").decode().strip()
        staged_paths = {
            entry.path for entry in tree_entries(destination, pre_certificate_tree)
        }
        if staged_paths != set(exported_files):
            missing = sorted(set(exported_files) - staged_paths)
            unexpected = sorted(staged_paths - set(exported_files))
            raise PublicExportError(
                "public Git tree does not match the sanitized snapshot: "
                f"missing={missing}, unexpected={unexpected}"
            )
        public_tree_digest = tree_sha256(destination, pre_certificate_tree)
        if public_tree_digest != expected_public_tree_digest:
            raise PublicExportError(
                "public Git tree bytes do not match the immutable source snapshot"
            )
        certificate = {
            "schema_version": 1,
            "kind": "SAGE Public Export",
            "repository": public_repository,
            "source_repository": source_repository,
            "source_head": source_head,
            "source_tree_sha256": source_tree_digest,
            "public_tree_sha256": public_tree_digest,
            "automated_evidence_manifest_sha256": attestation["manifest_sha256"],
            "automated_evidence_signer_fingerprint": attestation["signer_fingerprint"],
            "signer_identity": signer_identity,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "private_oracle_gates_passed": True,
            "export_secret_scan_passed": True,
            "automated_gates_passed": True,
            "r5_human_verification": "pending",
            "merge_authorized": False,
        }
        write_export_certificate(
            destination,
            certificate,
            signing_key=signing_key,
            signer_identity=signer_identity,
            allowed_signers=destination / "workflow" / "trusted_signers",
        )
        _git(destination, "add", "--all")
        _git(
            destination,
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "import signed sanitized SAGE candidate",
        )

    candidate_head = resolve_commit(destination, "HEAD")
    verification = verify_public_export(
        destination,
        allowed_signers=destination / "workflow" / "trusted_signers",
        expected_repository=public_repository,
        expected_source_repository=source_repository,
    )
    return {
        "schema_version": 1,
        "status": "automated_gates_passed",
        "source_repository": source_repository,
        "source_head": source_head,
        "source_tree_sha256": source_tree_digest,
        "public_repository": public_repository,
        "bootstrap_head": bootstrap_head,
        "candidate_branch": branch,
        "candidate_head": candidate_head,
        "public_tree_sha256": verification["public_tree_sha256"],
        "exported_file_count": len(exported_files),
        "private_oracle_gates_passed": True,
        "r5_human_verification": "pending",
        "merge_authorized": False,
    }
