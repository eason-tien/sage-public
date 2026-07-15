"""Fail-closed CodeGraph lifecycle for every SAGE project workspace."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any


class CodeGraphError(RuntimeError):
    """CodeGraph is unavailable, stale, or failed to index the workspace."""


def _run(command: list[str], cwd: Path, timeout: int = 120) -> dict[str, Any]:
    started = time.monotonic()
    recorded = [
        "codegraph" if index == 0 else part for index, part in enumerate(command)
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        return {
            "command": recorded,
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": completed.stdout,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError) as error:
        return {
            "command": recorded,
            "exit_code": 124 if isinstance(error, subprocess.TimeoutExpired) else 127,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": str(error),
        }


def _integer(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1).replace(",", "")) if match else None


def _exclude_local_metadata(project: Path) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=project,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return
    exclude = Path(completed.stdout.strip())
    if not exclude.is_absolute():
        exclude = project / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if ".codegraph/" not in existing.splitlines():
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(".codegraph/\n")


def refresh_codegraph(project: Path) -> dict[str, Any]:
    """Initialize or synchronize CodeGraph and prove the resulting index is current."""
    project = project.resolve()
    _exclude_local_metadata(project)
    executable = shutil.which("codegraph")
    if executable is None:
        return {
            "passed": False,
            "action": "missing",
            "refresh": {
                "command": ["codegraph", "sync", str(project)],
                "exit_code": 127,
                "duration_seconds": 0,
                "output": "codegraph executable is required",
            },
            "status": None,
            "files": None,
            "nodes": None,
            "edges": None,
        }

    database = project / ".codegraph" / "codegraph.db"
    action = "sync" if database.is_file() else "init"
    refresh = _run([executable, action, str(project)], project)
    status = _run([executable, "status", str(project)], project)
    output = str(status["output"])
    passed = bool(
        refresh["exit_code"] == 0
        and status["exit_code"] == 0
        and "Index is up to date" in output
    )
    return {
        "passed": passed,
        "action": action,
        "refresh": refresh,
        "status": status,
        "files": _integer(r"Files:\s+([\d,]+)", output),
        "nodes": _integer(r"Nodes:\s+([\d,]+)", output),
        "edges": _integer(r"Edges:\s+([\d,]+)", output),
    }


def require_fresh_codegraph(project: Path) -> dict[str, Any]:
    result = refresh_codegraph(project)
    if not result["passed"]:
        detail = result.get("status") or result.get("refresh")
        raise CodeGraphError(f"CodeGraph refresh failed: {detail}")
    return result
