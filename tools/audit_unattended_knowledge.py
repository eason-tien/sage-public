#!/usr/bin/env python3
"""Create a real local audit of the unattended knowledge and version loop."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.codegraph import refresh_codegraph
from workflow.knowledge import KnowledgeVault
from workflow.run import git_stdout, shared_prompt


ROOT = Path(__file__).resolve().parents[1]
AUDIT_TASK_NAME = "unattended-governance-upgrade"


def audit_task_spec() -> str:
    """Bind the audit task to the governance objective without posing as UI work."""

    objective = ROOT / "docs" / "unattended-knowledge-objective.md"
    digest = hashlib.sha256(objective.read_bytes()).hexdigest()
    return (
        "# Unattended governance audit\n\n"
        "Validate repository automation, evidence, the knowledge/version ledger, and "
        "the frozen objective document `docs/unattended-knowledge-objective.md` at "
        f"SHA256 `{digest}`. This task changes governance automation only.\n"
    )


def portable(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(str(ROOT), "$PROJECT_ROOT")
    if isinstance(value, list):
        return [portable(item) for item in value]
    if isinstance(value, dict):
        return {key: portable(item) for key, item in value.items()}
    return value


def run(command: list[str], timeout: int = 300) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
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


def version_record_check(expected_version: str) -> dict[str, Any]:
    """Require the version gate to report the ledger version just materialized."""

    command = [
        "python3",
        "tools/check_version_record.py",
        "--project-id",
        "multi-cli-workflow-lab",
    ]
    result: dict[str, Any] = {}
    reported_version = None
    for attempt in range(1, 3):
        result = run(command)
        try:
            payload = json.loads(str(result.get("output", "")))
        except (json.JSONDecodeError, TypeError, ValueError):
            payload = None
        reported_version = (
            payload.get("current_version") if isinstance(payload, dict) else None
        )
        result["expected_current_version"] = expected_version
        result["reported_current_version"] = reported_version
        result["attempts"] = attempt
        if (
            result.get("exit_code") == 0
            and isinstance(payload, dict)
            and payload.get("passed") is True
            and reported_version == expected_version
        ):
            return result
    result["underlying_exit_code"] = result.get("exit_code")
    result["exit_code"] = 1
    result["output"] = (
        str(result.get("output", ""))
        + f"\nversion record mismatch: expected {expected_version}, "
        f"reported {reported_version}\n"
    )
    return result


def changed_files() -> list[str]:
    changed = [
        path
        for path in git_stdout(
            [
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                "--diff-filter=ACDMRTUXB",
                "HEAD",
            ],
            ROOT,
        ).split("\0")
        if path
    ]
    untracked = git_stdout(
        ["ls-files", "--others", "--exclude-standard"], ROOT
    ).splitlines()
    return sorted(
        set(changed + untracked + ["reports/unattended-knowledge-audit.json"])
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=ROOT / "runs" / "audits" / "unattended-knowledge-loop",
    )
    parser.add_argument("--vault", type=Path, default=ROOT / "knowledge")
    parser.add_argument(
        "--signing-key",
        type=Path,
        default=Path("~/.config/sage/evidence_ed25519").expanduser(),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "unattended-knowledge-audit.json",
    )
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if run_dir.exists():
        raise SystemExit(f"audit run already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    task_spec = run_dir / "TASK.md"
    task_spec.write_text(audit_task_spec(), encoding="utf-8")
    source_head = git_stdout(["rev-parse", "HEAD"], ROOT).strip()
    vault = KnowledgeVault(args.vault)
    preflight = vault.prepare_task(
        repo=ROOT,
        route="high",
        task_name=AUDIT_TASK_NAME,
        spec=task_spec,
        acceptance=[
            "python3 -m unittest discover -s tests -p 'test_*.py'",
            "python3 tools/check_codegraph.py .",
            "ruff check . && ruff format --check .",
        ],
        source_head=source_head,
        project_id="multi-cli-workflow-lab",
        signing_key=args.signing_key,
    )
    codegraph = refresh_codegraph(ROOT)
    if preflight["ready"] and codegraph["passed"]:
        vault.record_dispatch(preflight, run_dir=run_dir, codegraph=codegraph)

    shared = shared_prompt("audit")
    checks = {
        "capability_preflight": {
            "command": ["sage", "preflight"],
            "exit_code": 0 if preflight["ready"] else 1,
            "duration_seconds": 0,
            "output": preflight["capability"],
        },
        "relevant_knowledge": {
            "command": ["knowledge", "retrieve"],
            "exit_code": 0 if not preflight["missing_knowledge"] else 1,
            "duration_seconds": 0,
            "output": {
                "languages": preflight["languages"],
                "notes": preflight["language_notes"],
            },
        },
        "codegraph_current": {
            "command": ["codegraph", codegraph["action"], "."],
            "exit_code": 0 if codegraph["passed"] else 1,
            "duration_seconds": codegraph["refresh"]["duration_seconds"],
            "output": {
                "files": codegraph["files"],
                "nodes": codegraph["nodes"],
                "edges": codegraph["edges"],
            },
        },
        "shared_cli_briefing": {
            "command": ["orchestrator", "build-shared-briefing"],
            "exit_code": 0
            if all(
                marker in shared
                for marker in ("SAGE_KNOWLEDGE.md", "CodeGraph", "Never edit")
            )
            else 1,
            "duration_seconds": 0,
            "output": {
                "agents": ["agy", "codex", "claude"],
                "sha256": preflight["briefing_sha256"],
            },
        },
        "unit_tests": run(
            ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
        ),
        "ruff": run(["ruff", "check", "."]),
        "ruff_format": run(["ruff", "format", "--check", "."]),
        "diff_check": run(["git", "diff", "--check"]),
        "gitleaks": run(
            ["gitleaks", "detect", "--no-git", "--redact", "--source", "."]
        ),
    }
    passed = all(check["exit_code"] == 0 for check in checks.values())
    session = vault.session(preflight, run_dir)
    knowledge = session.complete(
        passed=passed,
        checks=checks,
        stages=[{"agent": "orchestrator", "exit_code": 0}],
        changed_files=changed_files(),
        source_head=source_head,
    )
    version_check = version_record_check(str(knowledge["version"]))
    checks["version_record"] = version_check
    passed = bool(passed and version_check["exit_code"] == 0)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "automated_gates_passed": passed,
        "r5_human_verification": "pending",
        "merge_authorized": False,
        "source_head": source_head,
        "preflight": {
            key: value for key, value in preflight.items() if key != "briefing"
        },
        "knowledge": knowledge,
        "checks": checks,
    }
    args.output.write_text(
        json.dumps(portable(report), indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "automated_gates_passed": passed,
                "version": knowledge["version"],
                "memory_distilled": knowledge["memory_distilled"],
                "codegraph_current": knowledge["codegraph_current"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
