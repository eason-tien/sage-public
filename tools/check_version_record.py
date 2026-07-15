#!/usr/bin/env python3
"""Validate staged or committed version-ledger updates without false-green merges."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.version_snapshot import (
    VersionSnapshotError,
    commit_snapshot_sha256,
    index_snapshot_sha256,
    is_versioned_path,
    worktree_snapshot_sha256,
)


def _git(repo: Path, arguments: list[str], *, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        raise SystemExit(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def staged_files(repo: Path) -> list[str]:
    return _git_paths(
        repo,
        [
            "diff",
            "--cached",
            "--no-renames",
            "--name-only",
            "-z",
            "--diff-filter=ACDMRTUXB",
        ],
    )


def _git_paths(repo: Path, arguments: list[str]) -> list[str]:
    return [path for path in _git(repo, arguments).split("\0") if path]


def resolve_commit(repo: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", commit):
        detail = completed.stderr.strip() or "not a commit"
        raise SystemExit(f"cannot resolve version-check ref {ref!r}: {detail}")
    return commit


def optional_commit(repo: Path, ref: str) -> str | None:
    """Resolve a commit, returning None only when the ref is genuinely unborn."""

    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0:
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(f"cannot resolve version-check ref {ref!r}: not a commit")
    return commit


def _first_parent(repo: Path, head: str) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{head}^1"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def comparison_base(
    repo: Path,
    *,
    head: str,
    base_ref: str | None,
    comparison: str,
) -> str | None:
    if base_ref is None:
        return _first_parent(repo, head)
    base = resolve_commit(repo, base_ref)
    if comparison == "merge-base":
        merged = _git(repo, ["merge-base", base, head]).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", merged):
            raise SystemExit("version-check refs have no merge base")
        return merged
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if ancestor.returncode != 0:
        raise SystemExit(
            "direct version-check base must be an ancestor of head; "
            "refusing a non-fast-forward or incomplete range"
        )
    return base


def head_files(
    repo: Path,
    head_ref: str = "HEAD",
    *,
    base_ref: str | None = None,
    comparison: str = "direct",
) -> list[str]:
    head = resolve_commit(repo, head_ref)
    base = comparison_base(repo, head=head, base_ref=base_ref, comparison=comparison)
    if base is None:
        return _git_paths(repo, ["ls-tree", "--name-only", "-r", "-z", head])
    return _git_paths(
        repo,
        [
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            "--diff-filter=ACDMRTUXB",
            base,
            head,
        ],
    )


def versioned_files(files: list[str]) -> set[str]:
    return {path for path in files if is_versioned_path(path)}


def _relative_to_repo(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo).as_posix()
    except ValueError as error:
        raise SystemExit(
            "committed version ledger must be inside the repository"
        ) from error


def _commit_text(
    repo: Path, commit: str, path: str, *, required: bool = True
) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    if required:
        raise SystemExit(f"candidate commit is missing required ledger file: {path}")
    return None


def _index_text(repo: Path, path: str, *, required: bool = True) -> str | None:
    completed = subprocess.run(
        ["git", "show", f":{path}"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode == 0:
        return completed.stdout
    if required:
        raise SystemExit(f"staged candidate is missing required ledger file: {path}")
    return None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _parse_state(text: str, *, source: str) -> dict[str, Any]:
    try:
        state = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"{source} State.json is invalid JSON: {error}") from error
    if not isinstance(state, dict) or not isinstance(state.get("history"), list):
        raise SystemExit(f"{source} State.json has an invalid schema")
    return state


def _frontmatter(text: str, *, source: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise SystemExit(f"{source} is missing YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise SystemExit(f"{source} has unterminated YAML frontmatter") from error
    values: dict[str, str] = {}
    for line in lines[1:end]:
        if not line or ":" not in line:
            raise SystemExit(f"{source} has malformed YAML frontmatter")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key or not value:
            raise SystemExit(f"{source} has malformed YAML frontmatter")
        if key in values:
            raise SystemExit(f"{source} has duplicate YAML frontmatter key: {key}")
        values[key] = value
    return values, "\n".join(lines[end + 1 :]) + "\n"


def _markdown_section(text: str, heading: str, *, source: str) -> str:
    lines = text.splitlines()
    matches = [index for index, line in enumerate(lines) if line == heading]
    if len(matches) != 1:
        raise SystemExit(f"{source} must contain exactly one {heading!r} section")
    start = matches[0]
    level = len(heading) - len(heading.lstrip("#"))
    prefix = "#" * level + " "
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith(prefix)
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _task_note_path(record: dict[str, Any], *, project_id: str) -> str:
    task_note = record.get("task_note")
    if not isinstance(task_note, str) or not task_note:
        raise SystemExit("history record has no task note")
    pure = PurePosixPath(task_note)
    if (
        pure.is_absolute()
        or pure.as_posix() != task_note
        or any(part in {"", ".", ".."} for part in pure.parts)
        or pure.suffix != ".md"
        or pure.parent.as_posix() != f"Tasks/{project_id}"
    ):
        raise SystemExit(f"history record has invalid task note path: {task_note!r}")
    return task_note


def _validate_history_context(
    *,
    records: list[Any],
    state_current: str,
    memory_text: str,
    version_text: str,
    project_id: str,
    vault_relative: str,
    load_text: Callable[[str], str],
    source: str,
) -> tuple[set[str], set[str]]:
    memory_frontmatter, _ = _frontmatter(memory_text, source=f"{source} Memory.md")
    if memory_frontmatter.get("project") != project_id:
        raise SystemExit(f"{source} Memory.md project does not match State.json")
    if memory_frontmatter.get("current_version") != state_current:
        raise SystemExit(
            f"{source} Memory.md current_version does not match State.json"
        )

    required_records: set[str] = set()
    declared: set[str] = set()
    for raw_record in records:
        if not isinstance(raw_record, dict):
            raise SystemExit(f"{source} added history entries must be JSON objects")
        record = raw_record
        required_fields = {
            "task_id",
            "task_name",
            "completed_at",
            "status",
            "route",
            "source_head",
            "version",
            "version_bumped",
            "changed_files",
            "task_note",
            "distilled_lesson",
        }
        missing_fields = required_fields - set(record)
        if missing_fields:
            raise SystemExit(
                f"{source} history entry is missing fields: "
                + ", ".join(sorted(missing_fields))
            )
        task_id = record["task_id"]
        task_name = record["task_name"]
        completed_at = record["completed_at"]
        status = record["status"]
        route = record["route"]
        source_head = record["source_head"]
        lesson = record["distilled_lesson"]
        for label, value in (
            ("task_id", task_id),
            ("task_name", task_name),
            ("completed_at", completed_at),
            ("status", status),
            ("route", route),
            ("distilled_lesson", lesson),
        ):
            if not isinstance(value, str) or not value.strip():
                raise SystemExit(f"{source} history entry has invalid {label}")
        if not isinstance(source_head, str) or not re.fullmatch(
            r"[0-9a-f]{40}", source_head
        ):
            raise SystemExit(f"{source} history entry has invalid source_head")
        changed_files = record["changed_files"]
        if not isinstance(changed_files, list) or not all(
            isinstance(path, str) and path for path in changed_files
        ):
            raise SystemExit(f"{source} history entry has invalid changed_files")

        bumped = record["version_bumped"]
        version = record["version"]
        if bumped is True:
            _semver(version, source=f"{source} successful history entry")
            if status not in {"automated_gates_passed", "ci_passed"}:
                raise SystemExit(
                    f"{source} successful history entry has invalid status: {status}"
                )
            declared.update(changed_files)
        elif bumped is False:
            if version is not None or status != "failed":
                raise SystemExit(
                    f"{source} failed history entry has invalid result state"
                )
        else:
            raise SystemExit(f"{source} history entry has non-boolean version_bumped")

        task_note = _task_note_path(record, project_id=project_id)
        if PurePosixPath(task_note).stem != task_id:
            raise SystemExit(f"{source} task note path does not match task_id")
        task_path = f"{vault_relative}/{task_note}"
        required_records.add(task_path)
        note_text = load_text(task_path)
        note_frontmatter, note_body = _frontmatter(
            note_text, source=f"{source} task note {task_note}"
        )
        expected_note = {
            "task_id": task_id,
            "project": project_id,
            "status": status,
            "observed_at": completed_at,
            "route": route,
        }
        for key, expected in expected_note.items():
            if note_frontmatter.get(key) != expected:
                raise SystemExit(
                    f"{source} task note {task_note} {key} does not match State.json"
                )
        required_note_lines = {
            f"# {task_name}",
            f"Project memory: [[Projects/{project_id}/Memory]]",
            f"Version ledger: [[Projects/{project_id}/Ver]]",
            f"- Source HEAD: `{source_head}`",
            "## Result",
            "## Distilled lesson",
        }
        missing_note_lines = required_note_lines - set(note_body.splitlines())
        if missing_note_lines:
            raise SystemExit(
                f"{source} task note {task_note} is missing required context: "
                + ", ".join(sorted(missing_note_lines))
            )
        if not any(
            line.startswith("- Changed files:") for line in note_body.splitlines()
        ) or not any(
            line.startswith("- Failing checks:") for line in note_body.splitlines()
        ):
            raise SystemExit(f"{source} task note {task_note} has no result context")
        lesson_section = _markdown_section(
            note_body, "## Distilled lesson", source=f"{source} task note {task_note}"
        )
        if lesson not in lesson_section:
            raise SystemExit(
                f"{source} task note {task_note} lesson does not match State.json"
            )

        memory_heading = f"### {completed_at} — {task_name}"
        memory_section = _markdown_section(
            memory_text, memory_heading, source=f"{source} Memory.md"
        )
        memory_version = version if bumped else "unchanged"
        task_link = PurePosixPath(task_note).with_suffix("").as_posix()
        required_memory_lines = {
            f"- Status: `{status}`",
            f"- Route: `{route}`",
            f"- Version: `{memory_version}`",
            f"- Detail: [[{task_link}]]",
        }
        missing_memory = required_memory_lines - set(memory_section.splitlines())
        if missing_memory or lesson not in memory_section:
            raise SystemExit(
                f"{source} Memory.md entry for {task_id} does not match State.json"
            )

        if bumped:
            version_heading = f"## {version} — {completed_at}"
            version_section = _markdown_section(
                version_text, version_heading, source=f"{source} Ver.md"
            )
            briefing = record.get("briefing_sha256")
            if not isinstance(briefing, str) or not re.fullmatch(
                r"[0-9a-f]{64}", briefing
            ):
                raise SystemExit(
                    f"{source} successful history entry has invalid briefing_sha256"
                )
            changed = ", ".join(changed_files) if changed_files else "none"
            required_version_lines = {
                f"- Task: [[{task_link}|{task_name}]]",
                f"- Source HEAD: `{source_head}`",
                f"- Route: `{route}`",
                f"- Changed: {changed}",
                f"- Knowledge briefing: `{briefing}`",
            }
            candidate_tree = record.get("candidate_tree_sha256")
            if candidate_tree is not None:
                if not isinstance(candidate_tree, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", candidate_tree
                ):
                    raise SystemExit(
                        f"{source} successful history entry has invalid candidate_tree_sha256"
                    )
                required_version_lines.add(f"- Candidate tree: `{candidate_tree}`")
            if not required_version_lines <= set(version_section.splitlines()):
                raise SystemExit(
                    f"{source} Ver.md entry for {version} does not match State.json"
                )
    return required_records, declared


def _semver(value: Any, *, source: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise SystemExit(f"{source} has no valid semantic version")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _validate_ledger(
    *,
    state: dict[str, Any],
    version_text: str,
    memory_text: str,
    project_id: str,
    source: str,
) -> list[dict[str, Any]]:
    current = state.get("current_version")
    _semver(current, source=f"{source} knowledge state")
    version_frontmatter, _ = _frontmatter(version_text, source=f"{source} Ver.md")
    if version_frontmatter.get("current_version") != current:
        raise SystemExit(f"{source} Ver.md current_version does not match State.json")
    if version_frontmatter.get("project") not in {None, project_id}:
        raise SystemExit(f"{source} Ver.md project does not match State.json")
    memory_frontmatter, _ = _frontmatter(memory_text, source=f"{source} Memory.md")
    if memory_frontmatter.get("current_version") != current:
        raise SystemExit(
            f"{source} Memory.md current_version does not match State.json"
        )
    if memory_frontmatter.get("project") not in {None, project_id}:
        raise SystemExit(f"{source} Memory.md project does not match State.json")
    successful = [
        item
        for item in state["history"]
        if isinstance(item, dict) and item.get("version_bumped") is True
    ]
    if not successful or successful[-1].get("version") != current:
        raise SystemExit(
            f"{source} latest successful task does not match current project version"
        )
    versions = [item.get("version") for item in successful]
    if len(versions) != len(set(versions)):
        raise SystemExit(f"{source} successful task versions must be unique")
    current_headings = re.findall(
        rf"(?m)^## {re.escape(str(current))}(?: — [^\n]+)?$", version_text
    )
    if len(current_headings) != 1:
        raise SystemExit(
            f"{source} Ver.md must contain exactly one current version section"
        )
    return successful


def _validate_committed_range(
    repo: Path,
    *,
    vault_relative: str,
    project_id: str,
    head_ref: str,
    base_ref: str | None,
    comparison: str,
) -> dict[str, Any]:
    head = resolve_commit(repo, head_ref)
    base = comparison_base(repo, head=head, base_ref=base_ref, comparison=comparison)
    project = f"{vault_relative}/Projects/{project_id}"
    state_path = f"{project}/State.json"
    memory_path = f"{project}/Memory.md"
    version_path = f"{project}/Ver.md"
    state = _parse_state(_commit_text(repo, head, state_path) or "", source="candidate")
    version_text = _commit_text(repo, head, version_path) or ""
    memory_text = _commit_text(repo, head, memory_path) or ""
    successful = _validate_ledger(
        state=state,
        version_text=version_text,
        memory_text=memory_text,
        project_id=project_id,
        source="candidate",
    )

    if base is None:
        changed = _git_paths(repo, ["ls-tree", "--name-only", "-r", "-z", head])
        base_history: list[Any] = []
        base_version: str | None = None
    else:
        changed = _git_paths(
            repo,
            [
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                "--diff-filter=ACDMRTUXB",
                base,
                head,
            ],
        )
        base_state_text = _commit_text(repo, base, state_path, required=False)
        if base_state_text is None:
            base_history = []
            base_version = None
        else:
            base_state = _parse_state(base_state_text, source="base")
            base_history = base_state["history"]
            base_version = base_state.get("current_version")
            _semver(base_version, source="base knowledge state")

    history = state["history"]
    if history[: len(base_history)] != base_history:
        raise SystemExit("candidate rewrites or deletes pre-existing version history")
    added_history = history[len(base_history) :]
    added_successful = [
        item
        for item in added_history
        if isinstance(item, dict) and item.get("version_bumped") is True
    ]
    changed_versioned = versioned_files(changed)
    if changed_versioned and not added_successful:
        raise SystemExit(
            "committed project changes require a new successful version record"
        )

    # Every retained history entry must still have its task, Memory, and Ver
    # context. A candidate may not hollow out old knowledge while keeping State.
    _validate_history_context(
        records=history,
        state_current=state["current_version"],
        memory_text=memory_text,
        version_text=version_text,
        project_id=project_id,
        vault_relative=vault_relative,
        load_text=lambda path: _commit_text(repo, head, path) or "",
        source="candidate",
    )

    required_records = {state_path, memory_path} if added_history else set()
    contextual_records, declared = _validate_history_context(
        records=added_history,
        state_current=state["current_version"],
        memory_text=memory_text,
        version_text=version_text,
        project_id=project_id,
        vault_relative=vault_relative,
        load_text=lambda path: _commit_text(repo, head, path) or "",
        source="candidate",
    )
    required_records.update(contextual_records)
    if added_successful:
        required_records.add(version_path)
    previous = (
        _semver(base_version, source="base knowledge state") if base_version else None
    )
    for record in added_successful:
        version = record.get("version")
        parsed = _semver(version, source="new successful version record")
        if previous is not None and parsed != (
            previous[0],
            previous[1],
            previous[2] + 1,
        ):
            raise SystemExit(
                f"new successful versions are not continuous: expected "
                f"{previous[0]}.{previous[1]}.{previous[2] + 1}, got {version}"
            )
        previous = parsed
    if added_successful and added_successful[-1].get("version") != state.get(
        "current_version"
    ):
        raise SystemExit(
            "last new successful version does not match candidate current_version"
        )
    if added_history:
        missing_records = required_records - set(changed)
        if missing_records:
            raise SystemExit(
                "committed project changes require memory/version records in range: "
                + ", ".join(sorted(missing_records))
            )
    undeclared = changed_versioned - declared
    if undeclared:
        raise SystemExit(
            "new version records do not declare committed project changes: "
            + ", ".join(sorted(undeclared))
        )
    if added_successful:
        candidate_tree = added_successful[-1].get("candidate_tree_sha256")
        if not isinstance(candidate_tree, str) or not re.fullmatch(
            r"[0-9a-f]{64}", candidate_tree
        ):
            raise SystemExit("new successful version must bind candidate_tree_sha256")
        try:
            actual_tree = commit_snapshot_sha256(repo, head)
        except VersionSnapshotError as error:
            raise SystemExit(
                f"cannot snapshot committed candidate tree: {error}"
            ) from error
        if actual_tree != candidate_tree:
            raise SystemExit(
                "committed candidate tree does not match the latest version record"
            )
    return {
        "head": head,
        "base": base,
        "changed": changed,
        "changed_versioned": changed_versioned,
        "required_records": required_records,
        "successful": successful,
        "added_successful": added_successful,
        "current_version": state["current_version"],
    }


def _validate_staged_range(
    repo: Path,
    *,
    vault_relative: str,
    project_id: str,
    staged: list[str],
) -> dict[str, Any]:
    project = f"{vault_relative}/Projects/{project_id}"
    state_path = f"{project}/State.json"
    memory_path = f"{project}/Memory.md"
    version_path = f"{project}/Ver.md"
    state = _parse_state(_index_text(repo, state_path) or "", source="staged candidate")
    version_text = _index_text(repo, version_path) or ""
    memory_text = _index_text(repo, memory_path) or ""
    successful = _validate_ledger(
        state=state,
        version_text=version_text,
        memory_text=memory_text,
        project_id=project_id,
        source="staged candidate",
    )

    head = optional_commit(repo, "HEAD")
    base_state_text = (
        _commit_text(repo, head, state_path, required=False)
        if head is not None
        else None
    )
    if base_state_text is None:
        base_history: list[Any] = []
        base_version: str | None = None
    else:
        base_state = _parse_state(base_state_text, source="HEAD")
        base_history = base_state["history"]
        base_version = base_state.get("current_version")
        _semver(base_version, source="HEAD knowledge state")

    history = state["history"]
    if history[: len(base_history)] != base_history:
        raise SystemExit(
            "staged candidate rewrites or deletes pre-existing version history"
        )
    added_history = history[len(base_history) :]
    added_successful = [
        item
        for item in added_history
        if isinstance(item, dict) and item.get("version_bumped") is True
    ]
    staged_versioned = versioned_files(staged)
    if staged_versioned and not added_successful:
        raise SystemExit(
            "staged project changes require a new successful version record"
        )

    _validate_history_context(
        records=history,
        state_current=state["current_version"],
        memory_text=memory_text,
        version_text=version_text,
        project_id=project_id,
        vault_relative=vault_relative,
        load_text=lambda path: _index_text(repo, path) or "",
        source="staged candidate",
    )

    required_records = {state_path, memory_path} if added_history else set()
    contextual_records, declared = _validate_history_context(
        records=added_history,
        state_current=state["current_version"],
        memory_text=memory_text,
        version_text=version_text,
        project_id=project_id,
        vault_relative=vault_relative,
        load_text=lambda path: _index_text(repo, path) or "",
        source="staged candidate",
    )
    required_records.update(contextual_records)
    if added_successful:
        required_records.add(version_path)
    previous = (
        _semver(base_version, source="HEAD knowledge state") if base_version else None
    )
    for record in added_successful:
        version = record.get("version")
        parsed = _semver(version, source="new staged successful version record")
        if previous is not None and parsed != (
            previous[0],
            previous[1],
            previous[2] + 1,
        ):
            raise SystemExit(
                f"new staged successful versions are not continuous: expected "
                f"{previous[0]}.{previous[1]}.{previous[2] + 1}, got {version}"
            )
        previous = parsed
    if added_successful and added_successful[-1].get("version") != state.get(
        "current_version"
    ):
        raise SystemExit(
            "last new staged successful version does not match candidate current_version"
        )
    missing_records = required_records - set(staged)
    if missing_records:
        raise SystemExit(
            "project changes require staged memory/version records: "
            + ", ".join(sorted(missing_records))
        )
    undeclared = staged_versioned - declared
    if undeclared:
        raise SystemExit(
            "new staged version records do not declare project changes: "
            + ", ".join(sorted(undeclared))
        )
    if added_successful:
        candidate_tree = added_successful[-1].get("candidate_tree_sha256")
        if not isinstance(candidate_tree, str) or not re.fullmatch(
            r"[0-9a-f]{64}", candidate_tree
        ):
            raise SystemExit(
                "new staged successful version must bind candidate_tree_sha256"
            )
        try:
            actual_tree = index_snapshot_sha256(repo)
        except VersionSnapshotError as error:
            raise SystemExit(
                f"cannot snapshot staged candidate tree: {error}"
            ) from error
        if actual_tree != candidate_tree:
            raise SystemExit(
                "staged candidate tree does not match the latest version record"
            )
    return {
        "state": state,
        "successful": successful,
        "added_successful": added_successful,
        "required_records": required_records,
        "changed_versioned": staged_versioned,
    }


def _validate_worktree_ledger(
    repo: Path,
    *,
    vault_relative: str,
    project: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    state_path = project / "State.json"
    version_path = project / "Ver.md"
    memory_path = project / "Memory.md"
    if not all(path.is_file() for path in (state_path, version_path, memory_path)):
        raise SystemExit("knowledge State.json, Memory.md, and Ver.md are required")
    state = _parse_state(state_path.read_text(encoding="utf-8"), source="worktree")
    successful = _validate_ledger(
        state=state,
        version_text=version_path.read_text(encoding="utf-8"),
        memory_text=memory_path.read_text(encoding="utf-8"),
        project_id=project.name,
        source="worktree",
    )

    def load_worktree_text(path: str) -> str:
        candidate = repo / path
        if not candidate.is_file():
            raise SystemExit(f"worktree history task note is missing: {path}")
        return candidate.read_text(encoding="utf-8")

    _validate_history_context(
        records=state["history"],
        state_current=state["current_version"],
        memory_text=memory_path.read_text(encoding="utf-8"),
        version_text=version_path.read_text(encoding="utf-8"),
        project_id=project.name,
        vault_relative=vault_relative,
        load_text=load_worktree_text,
        source="worktree",
    )
    if state.get("schema_version") != 2:
        raise SystemExit(
            "worktree knowledge state must use content-bound schema_version 2"
        )
    expected_tree = successful[-1].get("candidate_tree_sha256")
    if not isinstance(expected_tree, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_tree
    ):
        raise SystemExit("latest successful version has no candidate tree binding")
    try:
        actual_tree = worktree_snapshot_sha256(repo)
    except VersionSnapshotError as error:
        raise SystemExit(f"cannot snapshot worktree candidate tree: {error}") from error
    if actual_tree != expected_tree:
        raise SystemExit(
            "worktree candidate tree does not match the latest version record"
        )
    task_note = project.parents[1] / str(successful[-1].get("task_note", ""))
    if not task_note.is_file():
        raise SystemExit("latest successful task note is missing")
    return state, successful, task_note


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--vault", type=Path, default=Path("knowledge"))
    parser.add_argument("--project-id", default="multi-cli-workflow-lab")
    parser.add_argument("--require-staged-update", action="store_true")
    parser.add_argument("--require-head-update", action="store_true")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument(
        "--comparison", choices=("direct", "merge-base"), default="direct"
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    vault = args.vault if args.vault.is_absolute() else repo / args.vault
    vault_relative = _relative_to_repo(repo, vault)
    project = vault / "Projects" / args.project_id
    staged = staged_files(repo)
    staged_versioned = versioned_files(staged)
    staged_ledger = any(
        path.startswith(f"{vault_relative}/Projects/{args.project_id}/")
        or path.startswith(f"{vault_relative}/Tasks/{args.project_id}/")
        for path in staged
    )
    staged_validation: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    successful: list[dict[str, Any]] = []
    staged_records: set[str] = set()
    if args.require_staged_update and (staged_versioned or staged_ledger):
        staged_validation = _validate_staged_range(
            repo,
            vault_relative=vault_relative,
            project_id=args.project_id,
            staged=staged,
        )
        state = staged_validation["state"]
        successful = staged_validation["successful"]
        staged_records = staged_validation["required_records"]
    elif not args.require_head_update:
        state, successful, task_note = _validate_worktree_ledger(
            repo,
            vault_relative=vault_relative,
            project=project,
        )
        version_relative = _relative_to_repo(repo, project / "Ver.md")
        state_relative = _relative_to_repo(repo, project / "State.json")
        memory_relative = _relative_to_repo(repo, project / "Memory.md")
        task_relative = _relative_to_repo(repo, task_note)
        staged_records = {
            version_relative,
            state_relative,
            memory_relative,
            task_relative,
        }

    committed: dict[str, Any] | None = None
    if args.require_head_update:
        committed = _validate_committed_range(
            repo,
            vault_relative=vault_relative,
            project_id=args.project_id,
            head_ref=args.head_ref,
            base_ref=args.base_ref,
            comparison=args.comparison,
        )

    print(
        json.dumps(
            {
                "passed": True,
                "project_id": args.project_id,
                "current_version": committed["current_version"]
                if committed
                else state["current_version"]
                if state
                else None,
                "successful_versions": len(
                    committed["successful"] if committed else successful
                ),
                "staged_version_update_required": bool(staged_versioned),
                "staged_version_update_present": staged_records <= set(staged),
                "staged_candidate_source": "index" if staged_validation else None,
                "head_version_update_required": bool(
                    committed and committed["changed_versioned"]
                ),
                "head_version_update_present": bool(
                    committed
                    and committed["added_successful"]
                    and committed["required_records"] <= set(committed["changed"])
                ),
                "comparison": args.comparison if committed else None,
                "base": committed["base"] if committed else None,
                "head": committed["head"] if committed else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
