"""Canonical content binding for the version ledger's final candidate tree."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


UNVERSIONED_PREFIXES = (
    ".codegraph/",
    "knowledge/",
    "reports/",
    "runs/",
)


class VersionSnapshotError(RuntimeError):
    """The candidate tree could not be snapshotted without ambiguity."""


def is_versioned_path(path: str) -> bool:
    return bool(path) and not path.startswith(UNVERSIONED_PREFIXES)


def _run(
    repo: Path,
    arguments: list[str],
    *,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise VersionSnapshotError(
            completed.stderr.decode("utf-8", errors="replace").strip()
            or "Git snapshot command failed"
        )
    return completed.stdout


def _update(hasher: object, *, mode: str, path: str, content: bytes) -> None:
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


def _index_entries(
    repo: Path, *, env: dict[str, str] | None = None
) -> dict[str, tuple[str, str]]:
    entries: dict[str, tuple[str, str]] = {}
    output = _run(repo, ["ls-files", "--stage", "-z"], env=env)
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, separator, raw_path = raw.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != b"0":
            raise VersionSnapshotError(
                "index contains an ambiguous non-stage-zero entry"
            )
        path = os.fsdecode(raw_path)
        entries[path] = (fields[0].decode("ascii"), fields[1].decode("ascii"))
    return entries


def _index_digest(repo: Path, *, env: dict[str, str] | None = None) -> str:
    hasher = hashlib.sha256()
    for path, (mode, object_id) in sorted(_index_entries(repo, env=env).items()):
        if not is_versioned_path(path):
            continue
        content = (
            ("gitlink:" + object_id).encode("ascii")
            if mode == "160000"
            else _run(repo, ["cat-file", "blob", object_id], env=env)
        )
        _update(hasher, mode=mode, path=path, content=content)
    return hasher.hexdigest()


def worktree_snapshot_sha256(repo: Path) -> str:
    """Hash the visible candidate in Git's canonical clean-filter byte domain."""

    repo = repo.resolve()
    object_path = Path(
        os.fsdecode(_run(repo, ["rev-parse", "--git-path", "objects"])).strip()
    )
    if not object_path.is_absolute():
        object_path = (repo / object_path).resolve()

    # A throwaway index is the only reliable way to apply all repository clean
    # filters, including custom filters and eol attributes, while preserving
    # symlinks, executable modes, deletions, and gitlinks exactly as `git add`
    # will. New blobs go to a temporary object database so this read-only
    # snapshot does not mutate the repository's object store or real index.
    with tempfile.TemporaryDirectory(prefix="sage-version-snapshot-") as temporary:
        root = Path(temporary)
        object_directory = root / "objects"
        object_directory.mkdir()
        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = str(root / "index")
        environment["GIT_OBJECT_DIRECTORY"] = str(object_directory)
        alternates = [str(object_path)]
        inherited_alternates = environment.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
        if inherited_alternates:
            alternates.append(inherited_alternates)
        environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(alternates)

        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
            check=False,
        )
        _run(
            repo,
            ["read-tree", "HEAD"] if head.returncode == 0 else ["read-tree", "--empty"],
            env=environment,
        )
        listed = _run(
            repo,
            ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            env=environment,
        )
        paths = sorted(
            {
                os.fsdecode(raw)
                for raw in listed.split(b"\0")
                if raw and is_versioned_path(os.fsdecode(raw))
            }
        )
        if paths:
            environment["GIT_LITERAL_PATHSPECS"] = "1"
            pathspec = b"\0".join(os.fsencode(path) for path in paths) + b"\0"
            _run(
                repo,
                ["add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul"],
                input_bytes=pathspec,
                env=environment,
            )
        return _index_digest(repo, env=environment)


def index_snapshot_sha256(repo: Path) -> str:
    """Hash the exact stage-zero index tree, excluding governance-only prefixes."""

    return _index_digest(repo)


def commit_snapshot_sha256(repo: Path, commit: str) -> str:
    """Hash the exact committed tree, excluding governance-only prefixes."""

    output = _run(repo, ["ls-tree", "-r", "-z", commit])
    entries: list[tuple[str, str, str]] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, separator, raw_path = raw.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise VersionSnapshotError("commit tree contains an ambiguous entry")
        entries.append(
            (
                os.fsdecode(raw_path),
                fields[0].decode("ascii"),
                fields[2].decode("ascii"),
            )
        )
    hasher = hashlib.sha256()
    for path, mode, object_id in sorted(entries):
        if not is_versioned_path(path):
            continue
        content = (
            ("gitlink:" + object_id).encode("ascii")
            if mode == "160000"
            else _run(repo, ["cat-file", "blob", object_id])
        )
        _update(hasher, mode=mode, path=path, content=content)
    return hasher.hexdigest()
