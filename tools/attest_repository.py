#!/usr/bin/env python3
"""Create signed SAGE evidence for an already implemented clean branch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.evidence import verify_signed_manifest, write_signed_manifest
from workflow.acceptance import (
    acceptance_argv,
    acceptance_environment,
    missing_acceptance_shell,
)
from workflow.run import (
    GATE_RUNTIME_BOUNDARY,
    candidate_symlink_boundary_check,
    capture_diff,
    git_integrity_check,
    git_metadata_snapshot,
    isolated_git_environment,
    materialized_candidate,
)


def run(
    command: list[str],
    cwd: Path,
    timeout: int = 900,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            env=env,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": completed.stdout,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError) as error:
        return {
            "command": command,
            "exit_code": 124 if isinstance(error, subprocess.TimeoutExpired) else 127,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": str(error),
        }


def git_output(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=isolated_git_environment(),
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout)
    return completed.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--signer-identity", required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    run_dir = args.run_dir.resolve()
    if run_dir.exists():
        raise SystemExit(f"attestation run already exists: {run_dir}")
    if not args.acceptance:
        parser.error("at least one acceptance command is required")
    initial_git_metadata = git_metadata_snapshot(repo)
    initial_integrity = git_integrity_check(repo, initial_git_metadata)
    if initial_integrity["exit_code"] != 0:
        raise SystemExit(
            "repository Git state is unsafe for attestation: "
            + json.dumps(initial_integrity["output"], sort_keys=True)
        )
    if git_output(repo, "status", "--porcelain", "--untracked-files=all").strip():
        raise SystemExit("repository must be clean before attestation")
    source_head = git_output(repo, "rev-parse", args.base).strip()
    head = git_output(repo, "rev-parse", "HEAD").strip()
    ancestry = run(
        ["git", "merge-base", "--is-ancestor", source_head, head],
        repo,
        env=isolated_git_environment(),
    )
    if ancestry["exit_code"] != 0:
        raise SystemExit("attestation base is not an ancestor of HEAD")
    patch = git_output(
        repo,
        "diff",
        "--binary",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        source_head,
        head,
    )
    if not patch:
        raise SystemExit("attestation patch is empty")
    changed_files = git_output(
        repo,
        "diff",
        "--no-renames",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        source_head,
        head,
    ).splitlines()

    checks: dict[str, dict[str, Any]] = {}
    with materialized_candidate(repo, source_head, patch) as candidate:
        boundary = candidate_symlink_boundary_check(candidate)
        checks["candidate_symlink_boundary"] = boundary
        # Expose newly added, untracked paths with intent-to-add before comparing
        # the reconstructed candidate to the committed source patch. A raw
        # ``git diff <base>`` silently omits new files after ``git apply``.
        reconstructed = capture_diff(candidate, source_head)
        checks["candidate_materialization"] = {
            "command": ["git", "clone", "+", "git", "apply"],
            "exit_code": 0 if reconstructed == patch else 1,
            "duration_seconds": 0,
            "output": "clean-clone reconstruction matched source patch"
            if reconstructed == patch
            else "clean-clone reconstruction differs from source patch",
        }
        if boundary["exit_code"] == 0:
            for index, command in enumerate(args.acceptance, start=1):
                current_boundary = candidate_symlink_boundary_check(candidate)
                argv = acceptance_argv(command)
                checks[f"acceptance_{index}"] = (
                    {
                        "command": ["candidate-symlink-boundary-check"],
                        "exit_code": 1,
                        "duration_seconds": 0,
                        "output": current_boundary["output"],
                    }
                    if current_boundary["exit_code"] != 0
                    else missing_acceptance_shell(command)
                    if argv is None
                    else run(
                        argv,
                        candidate,
                        env=acceptance_environment(isolated_git_environment()),
                    )
                )
            checks["gitleaks"] = run(
                [
                    "gitleaks",
                    "detect",
                    "--no-git",
                    "--redact",
                    "--source",
                    str(candidate),
                ],
                candidate,
            )
        checks["candidate_symlink_boundary_post"] = candidate_symlink_boundary_check(
            candidate
        )
        final_reconstructed = git_output(
            candidate,
            "diff",
            "--binary",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            source_head,
        )
        checks["materialized_candidate_immutability"] = {
            "command": ["git", "diff", "--binary", source_head],
            "exit_code": 0 if final_reconstructed == patch else 1,
            "duration_seconds": 0,
            "output": "unchanged"
            if final_reconstructed == patch
            else "acceptance changed the materialized candidate",
        }
    checks["diff_check"] = run(
        ["git", "diff", "--no-ext-diff", "--no-textconv", "--check", source_head, head],
        repo,
        env=isolated_git_environment(),
    )
    final_head = git_output(repo, "rev-parse", "HEAD").strip()
    final_status = git_output(
        repo, "status", "--porcelain", "--untracked-files=all"
    ).splitlines()
    final_integrity = git_integrity_check(repo, initial_git_metadata)
    immutable = bool(
        final_head == head and not final_status and final_integrity["exit_code"] == 0
    )
    checks["repository_immutability"] = {
        "command": ["git", "status", "--porcelain", "+", "metadata-integrity"],
        "exit_code": 0 if immutable else 1,
        "duration_seconds": 0,
        "output": {
            "head": final_head,
            "changes": final_status,
            "git_integrity": final_integrity["output"],
        },
    }
    passed = all(check["exit_code"] == 0 for check in checks.values())
    run_dir.mkdir(parents=True)
    patch_path = run_dir / "final.patch"
    patch_path.write_text(patch, encoding="utf-8")
    result = {
        "schema_version": 1,
        "execution_kind": "post_implementation_attestation",
        "name": args.name,
        "route": "post-implementation-attestation",
        "automated_gates_passed": passed,
        "r5_human_verification": "pending",
        "merge_authorized": False,
        "runtime_boundary": dict(GATE_RUNTIME_BOUNDARY),
        "passed": passed,
        "stages": [],
        "contract": {
            "source_repo": str(repo),
            "source_head": source_head,
            "attested_head": head,
        },
        "final_gates": {"passed": passed, "checks": checks},
        "promotion_manifest": {
            "final_patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
            "changed_files": changed_files,
            "acceptance_commands": args.acceptance,
        },
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    if not passed:
        raise SystemExit("attestation gates failed; unsigned evidence retained")
    signed = write_signed_manifest(
        run_dir,
        signing_key=args.signing_key,
        signer_identity=args.signer_identity,
    )
    verified = verify_signed_manifest(run_dir, allowed_signers=args.allowed_signers)
    print(
        json.dumps(
            {
                "automated_gates_passed": True,
                "r5_human_verification": "pending",
                "head": head,
                "signed": signed,
                "verified_fingerprint": verified["signer_fingerprint"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
