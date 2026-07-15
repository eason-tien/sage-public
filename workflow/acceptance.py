"""Portable shell policy for contractual acceptance commands."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any


ACCEPTANCE_SHELLS = ("bash", "zsh", "sh")
ACCEPTANCE_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "TERM",
    "COLORTERM",
    "CI",
    "JAVA_HOME",
    "GOPATH",
    "GOROOT",
    "DOTNET_ROOT",
    "CARGO_HOME",
    "RUSTUP_HOME",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
)


def acceptance_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Return a credential-minimized environment for candidate gate processes."""

    source = os.environ.copy()
    if overrides:
        source.update(overrides)
    environment = {
        name: source[name] for name in ACCEPTANCE_ENV_ALLOWLIST if name in source
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def acceptance_argv(command: str) -> list[str] | None:
    shell = next(
        (path for name in ACCEPTANCE_SHELLS if (path := shutil.which(name))),
        None,
    )
    return [shell, "-lc", command] if shell is not None else None


def missing_acceptance_shell(command: str) -> dict[str, Any]:
    return {
        "command": ["<posix-shell>", "-lc", command],
        "exit_code": 127,
        "timed_out": False,
        "duration_seconds": 0,
        "output": "no supported acceptance shell found (tried bash, zsh, sh)",
    }


def recorded_acceptance_script(command: object) -> str | None:
    if not isinstance(command, list) or len(command) != 3:
        return None
    shell, option, script = command
    if (
        not isinstance(shell, str)
        or Path(shell).name not in ACCEPTANCE_SHELLS
        or option != "-lc"
        or not isinstance(script, str)
    ):
        return None
    return script
