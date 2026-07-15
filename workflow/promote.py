#!/usr/bin/env python3
"""Promote a verified workflow patch to a draft PR and wait for GitHub CI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import unicodedata

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.acceptance import (
    acceptance_argv,
    acceptance_environment,
    missing_acceptance_shell,
    recorded_acceptance_script,
)
from workflow.codegraph import refresh_codegraph
from workflow.evidence import (
    EvidenceError,
    load_signed_repository_files,
    verify_signed_manifest,
)
from workflow.gates import select_plugin_commands
from workflow.run import ensure_repo, git_stdout, project_quality_commands


class PromotionError(RuntimeError):
    """A safety condition prevented promotion."""


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_command(
    command: list[str],
    cwd: Path,
    *,
    timeout: int = 900,
    env: dict[str, str] | None = None,
    unset_env: tuple[str, ...] = (),
    inherit_env: bool = True,
) -> dict[str, Any]:
    started = time.monotonic()
    command_env = os.environ.copy() if inherit_env else {}
    command_env.update({"GH_PROMPT_DISABLED": "1", "GIT_TERMINAL_PROMPT": "0"})
    if env:
        command_env.update(env)
    for name in unset_env:
        command_env.pop(name, None)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            env=command_env,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": completed.stdout,
        }
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return {
            "command": command,
            "exit_code": 124,
            "timed_out": True,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": output,
        }
    except FileNotFoundError as error:
        return {
            "command": command,
            "exit_code": 127,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": str(error),
        }


def require_success(result: dict[str, Any], context: str) -> dict[str, Any]:
    if result["exit_code"] != 0:
        raise PromotionError(f"{context} failed: {result['output']}")
    return result


def parse_json_result(result: dict[str, Any], context: str) -> Any:
    require_success(result, context)
    try:
        return json.loads(str(result["output"]))
    except json.JSONDecodeError as error:
        raise PromotionError(f"{context} returned invalid JSON") from error


def _acceptance_commands(result: dict[str, Any]) -> list[str]:
    manifest = result.get("promotion_manifest", {})
    commands = manifest.get("acceptance_commands")
    if commands is not None:
        if not isinstance(commands, list) or not all(
            isinstance(command, str) and command for command in commands
        ):
            raise PromotionError("promotion manifest has invalid acceptance commands")
        return commands

    checks = result.get("final_gates", {}).get("checks", {})
    numbered: list[tuple[int, str]] = []
    for name, check in checks.items():
        match = re.fullmatch(r"acceptance_(\d+)", name)
        if not match:
            continue
        command = check.get("command")
        script = recorded_acceptance_script(command)
        if script is None:
            raise PromotionError(f"cannot recover exact command for {name}")
        numbered.append((int(match.group(1)), script))
    return [command for _, command in sorted(numbered)]


def _signed_project_id(result: dict[str, Any]) -> str | None:
    knowledge = result.get("knowledge")
    project_id = knowledge.get("project_id") if isinstance(knowledge, dict) else None
    if project_id is None:
        return None
    if (
        not isinstance(project_id, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", project_id)
        or project_id in {".", ".."}
    ):
        raise PromotionError("verified repository knowledge has no valid project id")
    return project_id


def load_verified_artifact(run_dir: Path, *, allowed_signers: Path) -> dict[str, Any]:
    result_path = run_dir / "result.json"
    patch_path = run_dir / "final.patch"
    if not result_path.is_file() or not patch_path.is_file():
        raise PromotionError("run must contain result.json and final.patch")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PromotionError("result.json is invalid") from error
    automated_passed = result.get("automated_gates_passed", result.get("passed"))
    if automated_passed is not True:
        raise PromotionError("workflow result did not pass")
    if result.get("r5_human_verification", "pending") != "pending":
        raise PromotionError("automated workflow result contains an invalid R5 state")
    if result.get("merge_authorized", False) is not False:
        raise PromotionError("automated workflow result must never authorize merge")
    if result.get("final_gates", {}).get("passed") is not True:
        raise PromotionError("final mechanical gates did not pass")
    try:
        evidence = verify_signed_manifest(run_dir, allowed_signers=allowed_signers)
        repository_knowledge = load_signed_repository_files(run_dir, evidence)
    except EvidenceError as error:
        raise PromotionError(str(error)) from error
    project_id = _signed_project_id(result)
    if patch_path.stat().st_size == 0:
        raise PromotionError("verified patch is empty")

    actual_hash = file_sha256(patch_path)
    manifest = result.get("promotion_manifest", {})
    expected_hash = manifest.get("final_patch_sha256")
    if expected_hash:
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            raise PromotionError("final.patch hash does not match result.json")
    else:
        workspace = run_dir / "workspace"
        if not workspace.is_dir():
            raise PromotionError(
                "legacy run lacks both patch hash and workspace evidence"
            )
        current_patch = git_stdout(["diff", "--no-ext-diff", "HEAD"], workspace)
        if patch_path.read_text(encoding="utf-8") != current_patch:
            raise PromotionError(
                "legacy final.patch no longer matches verified workspace"
            )

    acceptance = _acceptance_commands(result)
    if not acceptance:
        raise PromotionError("verified run has no acceptance commands to replay")
    source_head = result.get("contract", {}).get("source_head")
    if not isinstance(source_head, str) or not re.fullmatch(
        r"[0-9a-f]{40}", source_head
    ):
        raise PromotionError("verified run has no valid source commit")
    return {
        "result": result,
        "patch_path": patch_path,
        "patch_sha256": actual_hash,
        "acceptance": acceptance,
        "source_head": source_head,
        "evidence": evidence,
        "repository_knowledge": repository_knowledge,
        "project_id": project_id,
    }


def default_branch_name(run_dir: Path) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", run_dir.name.lower()).strip("-.")
    if not slug:
        slug = "verified-patch"
    return f"codex/{slug}"


def validate_branch_name(branch: str, cwd: Path) -> None:
    if branch.startswith("-") or branch in {"HEAD", "@"}:
        raise PromotionError(f"unsafe branch name: {branch}")
    result = run_command(["git", "check-ref-format", "--branch", branch], cwd)
    require_success(result, "branch-name validation")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _changed_files(workspace: Path) -> list[str]:
    return git_stdout(
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR", "HEAD"], workspace
    ).splitlines()


def _materialize_repository_knowledge(
    workspace: Path,
    repository_knowledge: dict[str, Any] | None,
    *,
    patch_files: list[str],
) -> list[str]:
    if repository_knowledge is None:
        return []
    vault_path = repository_knowledge.get("vault_path")
    files = repository_knowledge.get("files", {})
    if vault_path is None:
        if files:
            raise PromotionError("external knowledge vault declared repository files")
        return []
    if vault_path != "knowledge":
        raise PromotionError("promotion only restores the repository knowledge/ vault")
    if not isinstance(files, dict):
        raise PromotionError("verified repository knowledge files are invalid")

    materialized: list[str] = []
    patch_owned = set(patch_files)
    patch_aliases = {
        unicodedata.normalize("NFC", relative).casefold() for relative in patch_files
    }
    for relative in sorted(files):
        parts = relative.split("/")
        if (
            not relative
            or "\\" in relative
            or parts[0] != "knowledge"
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise PromotionError(f"unsafe repository knowledge target: {relative!r}")
        if relative in patch_owned or (
            unicodedata.normalize("NFC", relative).casefold() in patch_aliases
        ):
            raise PromotionError(
                f"signed repository knowledge overlaps final.patch: {relative}"
            )
        item = files[relative]
        if not isinstance(item, dict):
            raise PromotionError(
                f"invalid signed repository knowledge file: {relative}"
            )
        source = item.get("path")
        expected_digest = item.get("sha256")
        if not isinstance(source, Path) or source.is_symlink() or not source.is_file():
            raise PromotionError(
                f"signed repository knowledge file is missing: {relative}"
            )
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected_digest:
            raise PromotionError(f"signed repository knowledge changed: {relative}")

        parent = workspace
        for part in parts[:-1]:
            parent /= part
            if parent.is_symlink():
                raise PromotionError(
                    f"repository knowledge target has a symlink parent: {relative}"
                )
            if parent.exists() and not parent.is_dir():
                raise PromotionError(
                    f"repository knowledge target has a non-directory parent: {relative}"
                )
            parent.mkdir(exist_ok=True)
        destination = parent / parts[-1]
        if destination.is_symlink() or (
            destination.exists() and not destination.is_file()
        ):
            raise PromotionError(f"unsafe repository knowledge destination: {relative}")
        destination.write_bytes(content)
        materialized.append(relative)

    if materialized:
        require_success(
            run_command(["git", "add", "--", *materialized], workspace),
            "signed repository knowledge staging",
        )
    return materialized


def run_local_gates(
    workspace: Path,
    acceptance: list[str],
    *,
    quality_files: list[str] | None = None,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    codegraph = refresh_codegraph(workspace)
    checks["codegraph_current"] = {
        "command": ["codegraph", codegraph["action"], str(workspace)],
        "exit_code": 0 if codegraph["passed"] else 1,
        "timed_out": False,
        "duration_seconds": codegraph["refresh"]["duration_seconds"],
        "output": {
            "files": codegraph["files"],
            "nodes": codegraph["nodes"],
            "edges": codegraph["edges"],
        },
    }
    quality_commands = (
        project_quality_commands(workspace)
        if quality_files is None
        else select_plugin_commands(workspace, quality_files)
    )
    isolated_env = {
        "GH_CONFIG_DIR": str(workspace / ".git" / "promotion-gh-disabled"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }
    unset_credentials = ("GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK")
    for index, command in enumerate(acceptance, start=1):
        argv = acceptance_argv(command)
        checks[f"acceptance_{index}"] = (
            missing_acceptance_shell(command)
            if argv is None
            else run_command(
                argv,
                workspace,
                env=acceptance_environment(isolated_env),
                unset_env=unset_credentials,
                inherit_env=False,
            )
        )
    for name, command in quality_commands:
        checks[name] = run_command(
            command,
            workspace,
            env=acceptance_environment(isolated_env),
            unset_env=unset_credentials,
            inherit_env=False,
        )
    checks["staged_diff_check"] = run_command(
        ["git", "diff", "--cached", "--check"], workspace
    )
    unstaged = git_stdout(["diff", "--name-only"], workspace).splitlines()
    untracked = git_stdout(
        ["ls-files", "--others", "--exclude-standard"], workspace
    ).splitlines()
    checks["clean_promotion_workspace"] = {
        "command": ["git", "status", "--porcelain"],
        "exit_code": 1 if unstaged or untracked else 0,
        "timed_out": False,
        "duration_seconds": 0,
        "output": {"unstaged": unstaged, "untracked": untracked},
    }
    return {
        "passed": all(check["exit_code"] == 0 for check in checks.values()),
        "checks": checks,
    }


def _parse_checks(result: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        value = json.loads(str(result["output"]))
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [check for check in value if isinstance(check, dict)]


def _draft_pr_is_safe(view: dict[str, Any], *, branch: str, base: str) -> bool:
    return bool(
        view.get("isDraft") is True
        and view.get("state") == "OPEN"
        and view.get("headRefName") == branch
        and view.get("baseRefName") == base
        and view.get("autoMergeRequest") is None
    )


def wait_for_github_ci(
    *,
    workspace: Path,
    repository: str,
    pr_url: str,
    wait_timeout: int,
    poll_interval: int,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + wait_timeout
    query_command = [
        "gh",
        "pr",
        "checks",
        pr_url,
        "--repo",
        repository,
        "--json",
        "name,state,bucket,link",
    ]
    discovery: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        query = run_command(query_command, workspace)
        discovery.append(query)
        checks = _parse_checks(query)
        if checks:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    if not checks:
        return {
            "discovery": discovery,
            "watch": {
                "command": ["gh", "pr", "checks", pr_url, "--watch"],
                "exit_code": 124,
                "timed_out": True,
                "duration_seconds": round(time.monotonic() - started, 3),
                "output": "no GitHub checks appeared before the timeout",
            },
            "final_query": discovery[-1] if discovery else {},
            "checks": [],
        }

    remaining_seconds = max(1, int(deadline - time.monotonic()))
    watch = run_command(
        [
            "gh",
            "pr",
            "checks",
            pr_url,
            "--repo",
            repository,
            "--watch",
            "--fail-fast",
            "--interval",
            str(poll_interval),
        ],
        workspace,
        timeout=remaining_seconds,
    )
    final_query = run_command(query_command, workspace)
    return {
        "discovery": discovery,
        "watch": watch,
        "final_query": final_query,
        "checks": _parse_checks(final_query),
    }


def publish_sage_evidence_status(
    *,
    workspace: Path,
    repository: str,
    commit_oid: str,
    pr_url: str,
    passed: bool,
) -> dict[str, Any]:
    state = "success" if passed else "failure"
    description = (
        "Signed automated evidence passed; human R5 pending"
        if passed
        else "Automated evidence or CI failed; human R5 blocked"
    )
    return run_command(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repository}/statuses/{commit_oid}",
            "-f",
            f"state={state}",
            "-f",
            "context=SAGE Evidence",
            "-f",
            f"description={description}",
            "-f",
            f"target_url={pr_url}",
        ],
        workspace,
    )


def resume_promotion(
    *,
    record: dict[str, Any],
    result_path: Path,
    workspace: Path,
    repo: Path,
    artifact: dict[str, Any],
    branch: str,
    remote: str,
    wait_timeout: int,
    poll_interval: int,
) -> dict[str, Any]:
    resumable = {
        "waiting_for_ci",
        "ci_wait_timed_out",
        "ci_failed_or_missing",
        "automated_gates_passed_r5_pending",
    }
    if record.get("status") not in resumable:
        raise PromotionError(
            f"promotion status is not safely resumable: {record.get('status')}"
        )
    if not workspace.is_dir():
        raise PromotionError("promotion workspace is missing")
    if (
        record.get("branch") != branch
        or record.get("remote") != remote
        or record.get("final_patch_sha256") != artifact["patch_sha256"]
        or record.get("evidence_fingerprint")
        != artifact["evidence"]["signer_fingerprint"]
    ):
        raise PromotionError("resume inputs do not match the recorded promotion")
    repository = record.get("repository")
    base = record.get("base")
    commit_oid = record.get("commit")
    pr_url = record.get("pr_url")
    if not all(
        isinstance(value, str) and value
        for value in (repository, base, commit_oid, pr_url)
    ):
        raise PromotionError(
            "promotion record lacks pushed branch or draft PR evidence"
        )

    require_success(
        run_command(["gh", "auth", "status"], repo), "GitHub authentication"
    )
    remote_url_result = run_command(["git", "remote", "get-url", remote], repo)
    require_success(remote_url_result, f"Git remote {remote}")
    remote_url = str(remote_url_result["output"]).strip()
    remote_head = run_command(["git", "ls-remote", "--heads", remote_url, branch], repo)
    require_success(remote_head, "remote promotion branch lookup")
    remote_oid = str(remote_head["output"]).split(maxsplit=1)[0]
    if remote_oid != commit_oid:
        raise PromotionError("remote promotion branch changed since the recorded push")

    pr_view_command = [
        "gh",
        "pr",
        "view",
        pr_url,
        "--repo",
        repository,
        "--json",
        "number,url,isDraft,state,headRefName,baseRefName,autoMergeRequest",
    ]
    initial_view = parse_json_result(
        run_command(pr_view_command, workspace), "resumed draft PR verification"
    )
    if not _draft_pr_is_safe(initial_view, branch=branch, base=base):
        raise PromotionError(
            "resumed PR no longer satisfies draft/no-auto-merge safety"
        )

    record["resume_count"] = int(record.get("resume_count", 0)) + 1
    record["status"] = "waiting_for_ci"
    _write_json(result_path, record)
    ci = wait_for_github_ci(
        workspace=workspace,
        repository=repository,
        pr_url=pr_url,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
    )
    record["steps"][f"resume_{record['resume_count']}_ci_discovery"] = ci["discovery"]
    record["steps"][f"resume_{record['resume_count']}_ci_watch"] = ci["watch"]
    record["steps"][f"resume_{record['resume_count']}_ci_checks"] = ci["final_query"]
    checks = ci["checks"]
    record["ci_checks"] = checks
    buckets = [check.get("bucket") for check in checks]
    ci_passed = (
        ci["watch"]["exit_code"] == 0
        and bool(buckets)
        and "pass" in buckets
        and all(bucket in {"pass", "skipping"} for bucket in buckets)
    )
    final_view = parse_json_result(
        run_command(pr_view_command, workspace), "resumed final PR safety verification"
    )
    pr_safe = _draft_pr_is_safe(final_view, branch=branch, base=base)
    draft_safe = final_view.get("isDraft") is True
    auto_merge_safe = final_view.get("autoMergeRequest") is None
    local_passed = record.get("local_gates", {}).get("passed") is True
    preliminary_pass = bool(local_passed and ci_passed and pr_safe)
    evidence_status = publish_sage_evidence_status(
        workspace=workspace,
        repository=repository,
        commit_oid=commit_oid,
        pr_url=pr_url,
        passed=preliminary_pass,
    )
    record["steps"][f"resume_{record['resume_count']}_sage_evidence_status"] = (
        evidence_status
    )
    record.update(
        {
            "draft": draft_safe,
            "no_auto_merge": auto_merge_safe,
            "ci_passed": ci_passed,
            "sage_evidence_check": (
                "success"
                if evidence_status["exit_code"] == 0 and preliminary_pass
                else "failure"
            ),
            "automated_gates_passed": bool(
                preliminary_pass and evidence_status["exit_code"] == 0
            ),
        }
    )
    record["promotion_ready"] = record["automated_gates_passed"]
    record["passed"] = record["automated_gates_passed"]
    if record["automated_gates_passed"]:
        record["status"] = "automated_gates_passed_r5_pending"
    elif ci["watch"].get("timed_out"):
        record["status"] = "ci_wait_timed_out"
    elif not pr_safe:
        record["status"] = "pr_safety_invariant_failed"
    else:
        record["status"] = "ci_failed_or_missing"
    _write_json(result_path, record)
    return record


def promote(
    *,
    run_dir: Path,
    repo: Path,
    branch: str,
    base: str | None,
    remote: str,
    title: str,
    commit_message: str,
    wait_timeout: int,
    poll_interval: int,
    allowed_signers: Path,
    resume: bool = False,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    repo = ensure_repo(repo.resolve())
    artifact = load_verified_artifact(run_dir, allowed_signers=allowed_signers)
    if wait_timeout < 1 or not 1 <= poll_interval <= 60:
        raise PromotionError(
            "CI timeout must be positive and polling must be 1-60 seconds"
        )
    validate_branch_name(branch, repo)

    promotion_dir = run_dir / "promotions" / branch.replace("/", "-")
    if promotion_dir.exists():
        if not resume:
            raise PromotionError(f"promotion attempt already exists: {promotion_dir}")
        result_path = promotion_dir / "result.json"
        if not result_path.is_file():
            raise PromotionError("promotion attempt has no result.json to resume")
        record = json.loads(result_path.read_text(encoding="utf-8"))
        return resume_promotion(
            record=record,
            result_path=result_path,
            workspace=promotion_dir / "workspace",
            repo=repo,
            artifact=artifact,
            branch=branch,
            remote=remote,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )
    promotion_dir.mkdir(parents=True)
    record: dict[str, Any] = {
        "automated_gates_passed": False,
        "r5_human_verification": "pending",
        "merge_authorized": False,
        "promotion_ready": False,
        # Compatibility alias. It never represents human R5 verification.
        "passed": False,
        "status": "preparing",
        "run_dir": str(run_dir),
        "source_head": artifact["source_head"],
        "final_patch_sha256": artifact["patch_sha256"],
        "evidence_signer": artifact["evidence"]["signer_identity"],
        "evidence_fingerprint": artifact["evidence"]["signer_fingerprint"],
        "branch": branch,
        "remote": remote,
        "no_auto_merge": False,
        "steps": {},
    }
    result_path = promotion_dir / "result.json"

    def save() -> None:
        _write_json(result_path, record)

    save()
    try:
        gh_auth = run_command(["gh", "auth", "status"], repo)
        require_success(gh_auth, "GitHub authentication")
        record["steps"]["gh_auth"] = {**gh_auth, "output": "authenticated"}

        origin = run_command(["git", "remote", "get-url", remote], repo)
        record["steps"]["remote_url"] = origin
        require_success(origin, f"Git remote {remote}")
        remote_url = str(origin["output"]).strip()

        repo_info_result = run_command(
            ["gh", "repo", "view", "--json", "nameWithOwner,defaultBranchRef"], repo
        )
        record["steps"]["repo_info"] = repo_info_result
        repo_info = parse_json_result(repo_info_result, "GitHub repository lookup")
        repository = repo_info.get("nameWithOwner")
        if not isinstance(repository, str) or "/" not in repository:
            raise PromotionError("GitHub repository lookup returned no repository name")
        if base is None:
            base_data = repo_info.get("defaultBranchRef") or {}
            base = base_data.get("name")
        if not isinstance(base, str) or not base:
            raise PromotionError("cannot determine the PR base branch")
        validate_branch_name(base, repo)
        record.update({"repository": repository, "base": base})

        remote_branch = run_command(
            ["git", "ls-remote", "--exit-code", "--heads", remote_url, branch], repo
        )
        record["steps"]["remote_branch_absent"] = remote_branch
        if remote_branch["exit_code"] == 0:
            raise PromotionError(f"remote branch already exists: {branch}")
        if remote_branch["exit_code"] != 2:
            raise PromotionError(
                f"could not prove remote branch absence: {remote_branch['output']}"
            )

        workspace = promotion_dir / "workspace"
        clone = run_command(
            ["git", "clone", "--quiet", "--origin", remote, remote_url, str(workspace)],
            repo,
        )
        record["steps"]["clone"] = clone
        require_success(clone, "isolated promotion clone")
        require_success(
            run_command(["git", "fetch", "--quiet", remote, base], workspace),
            "base branch fetch",
        )
        source_exists = run_command(
            ["git", "cat-file", "-e", f"{artifact['source_head']}^{{commit}}"],
            workspace,
        )
        record["steps"]["source_commit_exists"] = source_exists
        require_success(source_exists, "verified source commit lookup")
        ancestry = run_command(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                artifact["source_head"],
                f"{remote}/{base}",
            ],
            workspace,
        )
        record["steps"]["source_is_ancestor"] = ancestry
        require_success(ancestry, "verified source ancestry")
        require_success(
            run_command(
                ["git", "switch", "--quiet", "--create", branch, f"{remote}/{base}"],
                workspace,
            ),
            "new promotion branch",
        )
        require_success(
            run_command(["git", "config", "user.name", "Evidence Workflow"], workspace),
            "Git author setup",
        )
        require_success(
            run_command(
                [
                    "git",
                    "config",
                    "user.email",
                    "evidence-workflow@example.invalid",
                ],
                workspace,
            ),
            "Git author setup",
        )

        patch_copy = promotion_dir / "verified.patch"
        shutil.copy2(artifact["patch_path"], patch_copy)
        apply_result = run_command(
            ["git", "apply", "--3way", "--index", str(patch_copy)], workspace
        )
        record["steps"]["apply_patch"] = apply_result
        require_success(apply_result, "verified patch application")
        patch_files = _changed_files(workspace)
        if not patch_files:
            raise PromotionError("patch application produced no staged changes")
        expected_files = (
            artifact["result"].get("promotion_manifest", {}).get("changed_files")
        )
        if expected_files is not None and patch_files != expected_files:
            raise PromotionError(
                f"promoted file set differs from verified manifest: {patch_files}"
            )
        record["patch_changed_files"] = patch_files

        knowledge_files = _materialize_repository_knowledge(
            workspace,
            artifact["repository_knowledge"],
            patch_files=patch_files,
        )
        changed_files = _changed_files(workspace)
        expected_promoted_files = set(patch_files) | set(knowledge_files)
        if set(changed_files) != expected_promoted_files:
            raise PromotionError(
                "materialized knowledge did not produce the verified staged file set: "
                f"{changed_files}"
            )
        record["knowledge_changed_files"] = knowledge_files
        record["changed_files"] = changed_files

        gated_tree = git_stdout(["write-tree"], workspace).strip()
        gated_head = git_stdout(["rev-parse", "HEAD"], workspace).strip()
        blocked_push_url = "file:///promotion-gate-disabled"
        require_success(
            run_command(
                ["git", "remote", "set-url", "--push", remote, blocked_push_url],
                workspace,
            ),
            "disable pushes during acceptance",
        )

        version_check = None
        repository_knowledge = artifact["repository_knowledge"]
        if (
            repository_knowledge is not None
            and repository_knowledge.get("vault_path") is not None
        ):
            project_id = artifact["project_id"]
            version_command = [
                "python3",
                "tools/check_version_record.py",
                "--repo",
                ".",
                "--vault",
                "knowledge",
                "--project-id",
                project_id or "<missing-signed-project-id>",
                "--require-staged-update",
            ]
            version_check = (
                run_command(version_command, workspace)
                if project_id is not None
                else {
                    "command": version_command,
                    "exit_code": 1,
                    "timed_out": False,
                    "duration_seconds": 0,
                    "output": "verified repository knowledge has no signed project id",
                }
            )
            record["steps"]["version_record"] = version_check
            if version_check["exit_code"] != 0:
                record["local_gates"] = {
                    "passed": False,
                    "checks": {"version_record": version_check},
                }
                raise PromotionError(
                    "signed knowledge version invariant local gate failed: "
                    f"{version_check['output']}"
                )

        local_gates = run_local_gates(
            workspace,
            artifact["acceptance"],
            quality_files=patch_files,
        )
        if version_check is not None:
            local_gates["checks"] = {
                "version_record": version_check,
                **local_gates["checks"],
            }
        record["local_gates"] = local_gates
        if not local_gates["passed"]:
            raise PromotionError(
                "acceptance or local quality gates failed after patch apply"
            )
        post_gate_tree = git_stdout(["write-tree"], workspace).strip()
        post_gate_head = git_stdout(["rev-parse", "HEAD"], workspace).strip()
        post_gate_branch = git_stdout(["branch", "--show-current"], workspace).strip()
        post_gate_push_url = git_stdout(
            ["remote", "get-url", "--push", remote], workspace
        ).strip()
        if (
            post_gate_tree != gated_tree
            or post_gate_head != gated_head
            or post_gate_branch != branch
            or post_gate_push_url != blocked_push_url
        ):
            raise PromotionError(
                "acceptance commands mutated the promoted patch or Git state"
            )
        require_success(
            run_command(
                ["git", "remote", "set-url", "--push", remote, remote_url], workspace
            ),
            "restore promotion push URL",
        )

        commit = run_command(["git", "commit", "-m", commit_message], workspace)
        record["steps"]["commit"] = commit
        require_success(commit, "promotion commit")
        commit_oid = git_stdout(["rev-parse", "HEAD"], workspace).strip()
        record["commit"] = commit_oid
        push = run_command(
            ["git", "push", "--set-upstream", remote, branch],
            workspace,
            timeout=wait_timeout,
        )
        record["steps"]["push"] = push
        require_success(push, "promotion branch push")

        body_path = promotion_dir / "pr-body.md"
        body_path.write_text(
            "\n".join(
                [
                    "## What changed",
                    "",
                    f"Promotes the verified patch from workflow run `{run_dir.name}`.",
                    "",
                    "## Safety evidence",
                    "",
                    f"- Source commit: `{artifact['source_head']}`",
                    f"- Patch SHA-256: `{artifact['patch_sha256']}`",
                    "- The original acceptance commands were replayed after applying the patch.",
                    *(
                        [
                            "- Signed pending knowledge and version records were restored and the staged version invariant passed."
                        ]
                        if artifact["repository_knowledge"] is not None
                        and artifact["repository_knowledge"].get("vault_path")
                        is not None
                        else []
                    ),
                    "- This PR is intentionally draft and automatic merge is forbidden.",
                    "- Automated green is not SAGE R5; human verification remains pending.",
                    "",
                    "## Validation",
                    "",
                    *[f"- `{command}`" for command in artifact["acceptance"]],
                    "",
                ]
            ),
            encoding="utf-8",
        )
        create_pr = run_command(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                repository,
                "--draft",
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body-file",
                str(body_path),
            ],
            workspace,
        )
        record["steps"]["create_draft_pr"] = create_pr
        require_success(create_pr, "draft PR creation")

        pr_view_command = [
            "gh",
            "pr",
            "view",
            branch,
            "--repo",
            repository,
            "--json",
            "number,url,isDraft,state,headRefName,baseRefName,autoMergeRequest",
        ]
        initial_view_result = run_command(pr_view_command, workspace)
        record["steps"]["verify_draft_pr"] = initial_view_result
        initial_view = parse_json_result(initial_view_result, "draft PR verification")
        if not _draft_pr_is_safe(initial_view, branch=branch, base=base):
            raise PromotionError("created PR does not match the requested draft PR")
        pr_url = initial_view.get("url")
        if not isinstance(pr_url, str) or not pr_url.startswith("https://"):
            raise PromotionError("draft PR verification returned no URL")
        record.update(
            {
                "pr_number": initial_view.get("number"),
                "pr_url": pr_url,
                "draft": True,
                "no_auto_merge": True,
                "status": "waiting_for_ci",
            }
        )
        save()

        ci = wait_for_github_ci(
            workspace=workspace,
            repository=repository,
            pr_url=pr_url,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )
        ci_watch = ci["watch"]
        checks = ci["checks"]
        record["steps"]["ci_discovery"] = ci["discovery"]
        record["steps"]["ci_watch"] = ci_watch
        record["steps"]["ci_checks"] = ci["final_query"]
        record["ci_checks"] = checks

        final_view_result = run_command(pr_view_command, workspace)
        record["steps"]["final_pr_safety"] = final_view_result
        final_view = parse_json_result(
            final_view_result, "final PR safety verification"
        )
        pr_safe = _draft_pr_is_safe(final_view, branch=branch, base=base)
        draft_safe = final_view.get("isDraft") is True
        auto_merge_safe = final_view.get("autoMergeRequest") is None
        record["draft"] = draft_safe
        record["no_auto_merge"] = auto_merge_safe
        buckets = [check.get("bucket") for check in checks if isinstance(check, dict)]
        ci_passed = (
            ci_watch["exit_code"] == 0
            and bool(buckets)
            and "pass" in buckets
            and all(bucket in {"pass", "skipping"} for bucket in buckets)
        )
        record["ci_passed"] = ci_passed
        preliminary_pass = bool(local_gates["passed"] and ci_passed and pr_safe)
        evidence_status = publish_sage_evidence_status(
            workspace=workspace,
            repository=repository,
            commit_oid=commit_oid,
            pr_url=pr_url,
            passed=preliminary_pass,
        )
        record["steps"]["sage_evidence_status"] = evidence_status
        record["sage_evidence_check"] = (
            "success"
            if evidence_status["exit_code"] == 0 and preliminary_pass
            else "failure"
        )
        record["automated_gates_passed"] = bool(
            preliminary_pass and evidence_status["exit_code"] == 0
        )
        record["promotion_ready"] = record["automated_gates_passed"]
        record["passed"] = record["automated_gates_passed"]
        if record["automated_gates_passed"]:
            record["status"] = "automated_gates_passed_r5_pending"
        elif ci_watch["timed_out"]:
            record["status"] = "ci_wait_timed_out"
        elif not pr_safe:
            record["status"] = "pr_safety_invariant_failed"
        else:
            record["status"] = "ci_failed_or_missing"
        save()
        return record
    except Exception as error:
        record["status"] = "stopped"
        record["error"] = str(error)
        save()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply a verified patch to a new branch, open a draft PR, and wait for CI."
    )
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--branch")
    parser.add_argument("--base")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--title")
    parser.add_argument("--commit-message")
    parser.add_argument("--wait-timeout", type=int, default=1800)
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume CI waiting for an existing, commit-locked draft promotion",
    )
    args = parser.parse_args()
    if args.wait_timeout < 1 or not 1 <= args.poll_interval <= 60:
        parser.error("CI timeout must be positive and polling must be 1-60 seconds")
    branch = args.branch or default_branch_name(args.run)
    title = args.title or f"Promote verified patch: {args.run.name}"
    commit_message = args.commit_message or f"promote verified patch {args.run.name}"
    try:
        result = promote(
            run_dir=args.run,
            repo=args.repo,
            branch=branch,
            base=args.base,
            remote=args.remote,
            title=title,
            commit_message=commit_message,
            wait_timeout=args.wait_timeout,
            poll_interval=args.poll_interval,
            allowed_signers=args.allowed_signers,
            resume=args.resume,
        )
    except PromotionError as error:
        raise SystemExit(f"promotion stopped: {error}") from error
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["automated_gates_passed"] else 1)


if __name__ == "__main__":
    main()
