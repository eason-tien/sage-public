#!/usr/bin/env python3
"""Prepare and verify isolated multi-CLI benchmark workspaces."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workflow.codegraph import refresh_codegraph  # noqa: E402


FIXTURE = ROOT / "benchmarks" / "fixture"
HIDDEN = ROOT / "benchmarks" / "hidden"
RUNS = ROOT / "runs"
PROTECTED = {"TASK.md", "AGENTS.md"}


def run(command: list[str], cwd: Path, timeout: int = 120) -> dict[str, object]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "exit_code": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output": result.stdout,
    }


def redact_hidden_check(check: dict[str, object]) -> dict[str, object]:
    """Preserve gate evidence without exposing a hidden test command or oracle output."""
    output = str(check.get("output", ""))
    encoded = output.encode("utf-8", errors="replace")
    return {
        **check,
        "command": ["<redacted-hidden-test>"],
        "output": {
            "redacted": True,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
        },
    }


def workspace_for(name: str) -> Path:
    if not name or any(part in {"", ".", ".."} for part in Path(name).parts):
        raise SystemExit("run name must be a simple non-empty relative path")
    return RUNS / name / "workspace"


def prepare(name: str) -> Path:
    workspace = workspace_for(name)
    if workspace.parent.exists():
        raise SystemExit(f"run already exists: {workspace.parent}")
    workspace.parent.mkdir(parents=True)
    shutil.copytree(FIXTURE, workspace)
    commands = [
        ["git", "init", "-q"],
        ["git", "config", "user.name", "Workflow Lab"],
        ["git", "config", "user.email", "workflow-lab@example.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "benchmark baseline"],
    ]
    for command in commands:
        result = run(command, workspace)
        if result["exit_code"] != 0:
            raise SystemExit(result["output"])
    manifest = {
        "name": name,
        "workspace": str(workspace),
        "prepared_at_epoch": time.time(),
    }
    (workspace.parent / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(workspace)
    return workspace


def changed_protected_files(workspace: Path) -> list[str]:
    if not (workspace / ".git").exists():
        return []
    result = run(["git", "diff", "--name-only", "HEAD"], workspace)
    changed = str(result["output"]).splitlines()
    return sorted(
        path for path in changed if path in PROTECTED or path.startswith("tests/")
    )


def verify_workspace(workspace: Path) -> dict[str, object]:
    codegraph = refresh_codegraph(workspace)
    checks = {
        "codegraph_current": {
            "command": ["codegraph", codegraph["action"], str(workspace)],
            "exit_code": 0 if codegraph["passed"] else 1,
            "duration_seconds": codegraph["refresh"]["duration_seconds"],
            "output": {
                "files": codegraph["files"],
                "nodes": codegraph["nodes"],
                "edges": codegraph["edges"],
            },
        },
        "python_public": run(
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            workspace,
        ),
        "node_public": run(["node", "--test", "tests/singleflight.test.js"], workspace),
        "python_hidden": redact_hidden_check(
            run(
                ["python3", str(HIDDEN / "test_pricing_hidden.py"), str(workspace)],
                ROOT,
            )
        ),
        "node_hidden": redact_hidden_check(
            run(
                ["node", str(HIDDEN / "singleflight.hidden.test.js"), str(workspace)],
                ROOT,
            )
        ),
        "gitleaks": run(
            [
                "gitleaks",
                "detect",
                "--no-git",
                "--redact",
                "--source",
                str(workspace),
            ],
            ROOT,
        ),
    }
    protected = changed_protected_files(workspace)
    if (workspace / ".git").exists():
        diff_lines = str(
            run(["git", "diff", "--numstat", "HEAD"], workspace)["output"]
        ).splitlines()
    else:
        diff_lines = []
    passed = all(check["exit_code"] == 0 for check in checks.values()) and not protected
    return {
        "passed": passed,
        "protected_files_changed": protected,
        "diff_numstat": diff_lines,
        "checks": checks,
    }


def verify(name: str) -> None:
    workspace = workspace_for(name)
    if not workspace.exists():
        raise SystemExit(f"missing run: {workspace.parent}")
    result = verify_workspace(workspace)
    output_path = workspace.parent / "verification.json"
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


def verify_fixture() -> None:
    result = verify_workspace(FIXTURE)
    # The intentionally broken fixture must fail both public suites and hidden suites,
    # while integrity and secret scanning remain clean.
    expected_failures = {
        "python_public",
        "node_public",
        "python_hidden",
        "node_hidden",
    }
    actual_failures = {
        name for name, check in result["checks"].items() if check["exit_code"] != 0
    }
    valid = expected_failures.issubset(actual_failures)
    print(json.dumps({"fixture_is_discriminating": valid, **result}, indent=2))
    raise SystemExit(0 if valid else 1)


def doctor() -> None:
    commands = [
        "git",
        "gh",
        "codex",
        "agy",
        "claude",
        "python3",
        "node",
        "just",
        "hyperfine",
        "actionlint",
        "gitleaks",
        "pre-commit",
        "tmux",
        "claude-squad",
        "codegraph",
        "obsidian",
    ]
    status = {name: shutil.which(name) for name in commands}
    print(json.dumps(status, indent=2))
    raise SystemExit(0 if all(status.values()) else 1)


def clean(name: str) -> None:
    run_dir = workspace_for(name).parent
    if not run_dir.exists():
        raise SystemExit(f"missing run: {run_dir}")
    shutil.rmtree(run_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    subparsers.add_parser("verify-fixture")
    for command in ("prepare", "verify", "clean"):
        child = subparsers.add_parser(command)
        child.add_argument("name")
    args = parser.parse_args()
    if args.command == "doctor":
        doctor()
    elif args.command == "verify-fixture":
        verify_fixture()
    elif args.command == "prepare":
        prepare(args.name)
    elif args.command == "verify":
        verify(args.name)
    elif args.command == "clean":
        clean(args.name)


if __name__ == "__main__":
    main()
