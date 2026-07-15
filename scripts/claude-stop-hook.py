#!/usr/bin/env python3
"""Fail-closed Claude Stop hook with recursion-safe human escalation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[1]


def _stop_for_human(reason: str) -> int:
    print(
        json.dumps(
            {
                "continue": False,
                "stopReason": reason,
                "r5_human_verification": "pending",
                "merge_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _payload() -> dict[str, Any] | None:
    try:
        value = json.load(sys.stdin)
    except (OSError, RecursionError, UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _acceptance_path() -> Path | None:
    raw = os.environ.get("SAGE_ACCEPTANCE_FILE", "acceptance.txt")
    try:
        candidate = Path(raw)
        unsafe = (
            candidate.is_absolute()
            or not candidate.parts
            or any(part in {"", ".", ".."} for part in candidate.parts)
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if unsafe:
        return None
    return candidate


def _check(root: Path, cwd: Path, acceptance: Path) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell is None:
            return subprocess.CompletedProcess([], 127, "", "PowerShell not found")
        command = [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "scripts" / "acceptance-lock.ps1"),
            "check",
            str(acceptance),
        ]
    else:
        shell = shutil.which("bash")
        if shell is None:
            return subprocess.CompletedProcess([], 127, "", "bash not found")
        command = [
            shell,
            str(root / "scripts" / "acceptance-lock.sh"),
            "check",
            str(acceptance),
        ]
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )


def main() -> int:
    payload = _payload()
    if payload is None:
        return _stop_for_human(
            "Claude Stop hook input was malformed. Human inspection is required; "
            "R5 remains pending and merge is not authorized."
        )
    if payload.get("hook_event_name") != "Stop" or not isinstance(
        payload.get("stop_hook_active"), bool
    ):
        return _stop_for_human(
            "Claude Stop hook input lacked the required Stop/stop_hook_active contract. "
            "Human inspection is required; R5 remains pending."
        )
    cwd_raw = payload.get("cwd")
    if not isinstance(cwd_raw, str) or not cwd_raw.strip():
        return _stop_for_human(
            "Claude Stop hook received no valid cwd. Human inspection is required; "
            "R5 remains pending."
        )
    try:
        cwd = Path(cwd_raw).expanduser().resolve()
        cwd_valid = cwd.is_dir()
    except (OSError, RuntimeError, ValueError):
        cwd_valid = False
        cwd = SCRIPT_ROOT
    acceptance = _acceptance_path()
    if not cwd_valid or acceptance is None:
        return _stop_for_human(
            "Claude Stop hook cwd or SAGE_ACCEPTANCE_FILE was unsafe. Human inspection "
            "is required; R5 remains pending."
        )
    configured_root = os.environ.get("SAGE_ROOT")
    try:
        root = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else SCRIPT_ROOT
        )
        root_valid = root.is_dir()
    except (OSError, RuntimeError, ValueError):
        root_valid = False
        root = SCRIPT_ROOT
    if not root_valid:
        return _stop_for_human(
            "SAGE_ROOT is invalid. Human inspection is required; R5 remains pending."
        )
    try:
        checked = _check(root, cwd, acceptance)
    except (OSError, subprocess.TimeoutExpired) as error:
        checked = subprocess.CompletedProcess([], 124, "", str(error))
    if checked.returncode == 0:
        return 0

    detail = (
        checked.stdout or checked.stderr or "acceptance lock check failed"
    ).strip()
    detail = detail[:4000]
    if payload["stop_hook_active"]:
        return _stop_for_human(
            "Acceptance lock remains invalid after one Stop-hook continuation. "
            "The hook stopped retrying to prevent an infinite loop. Human intervention "
            "is required; R5 remains pending and merge_authorized=false. "
            f"Check output: {detail}"
        )
    print(detail, file=sys.stderr)
    print(
        "Acceptance lock is not trustworthy. Fix or explicitly relock it before stopping; "
        "R5 remains pending and merge_authorized=false.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
