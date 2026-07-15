"""Declarative, argv-only quality gate plugins and language discovery."""

from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
import re
from typing import Any


class GateConfigurationError(ValueError):
    """A gate plugin is ambiguous or unsafe to execute."""


LANGUAGE_PATTERNS: dict[str, tuple[str, ...]] = {
    "python": ("*.py",),
    "javascript": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "typescript": ("*.ts", "*.tsx"),
    "go": ("*.go",),
    "rust": ("*.rs",),
    "java": ("*.java",),
    "kotlin": ("*.kt", "*.kts"),
    "ruby": ("*.rb",),
    "php": ("*.php",),
    "csharp": ("*.cs",),
    "swift": ("*.swift",),
    "c": ("*.c", "*.h"),
    "cpp": ("*.cc", "*.cpp", "*.cxx", "*.hpp"),
    "lua": ("*.lua",),
    "shell": ("*.sh", "*.bash"),
}


@dataclass(frozen=True)
class GatePlugin:
    id: str
    globs: tuple[str, ...]
    command: tuple[str, ...]
    append_files: bool = True
    always: bool = False
    required_files: tuple[str, ...] = ()
    config_contains: str | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "GatePlugin":
        if not isinstance(raw, dict):
            raise GateConfigurationError("each gate plugin must be an object")
        allowed = {
            "id",
            "globs",
            "command",
            "append_files",
            "always",
            "required_files",
            "config_contains",
        }
        extra = set(raw) - allowed
        if extra:
            raise GateConfigurationError(f"unknown gate plugin fields: {sorted(extra)}")
        plugin_id = raw.get("id")
        globs = raw.get("globs", [])
        command = raw.get("command")
        if not isinstance(plugin_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]*", plugin_id
        ):
            raise GateConfigurationError("gate id must be lowercase and argv-safe")
        if not isinstance(globs, list) or not all(
            isinstance(pattern, str) and pattern for pattern in globs
        ):
            raise GateConfigurationError(f"gate {plugin_id} has invalid globs")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise GateConfigurationError(
                f"gate {plugin_id} command must be a non-empty argv array"
            )
        if any("{files}" in part and part != "{files}" for part in command):
            raise GateConfigurationError(
                f"gate {plugin_id} must use {{files}} as a standalone argv item"
            )
        shell_launchers = {
            "bash",
            "cmd",
            "cmd.exe",
            "fish",
            "powershell",
            "powershell.exe",
            "pwsh",
            "sh",
            "zsh",
        }
        if Path(command[0]).name.lower() in shell_launchers:
            raise GateConfigurationError(
                f"gate {plugin_id} must not invoke a shell interpreter"
            )
        for field in ("append_files", "always"):
            if field in raw and not isinstance(raw[field], bool):
                raise GateConfigurationError(
                    f"gate {plugin_id} {field} must be boolean"
                )
        required = raw.get("required_files", [])
        if not isinstance(required, list) or not all(
            isinstance(pattern, str) and pattern for pattern in required
        ):
            raise GateConfigurationError(f"gate {plugin_id} has invalid required_files")
        contains = raw.get("config_contains")
        if contains is not None and not isinstance(contains, str):
            raise GateConfigurationError(
                f"gate {plugin_id} config_contains must be text"
            )
        return cls(
            id=plugin_id,
            globs=tuple(globs),
            command=tuple(command),
            append_files=bool(raw.get("append_files", True)),
            always=bool(raw.get("always", False)),
            required_files=tuple(required),
            config_contains=contains,
        )


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern)
        for pattern in patterns
    )


def detect_languages(paths: list[str]) -> list[str]:
    return sorted(
        language
        for language, patterns in LANGUAGE_PATTERNS.items()
        if any(_matches(path, patterns) for path in paths)
    )


def builtin_plugins(workspace: Path) -> list[GatePlugin]:
    plugins = [
        GatePlugin(
            id="diff_check",
            globs=(),
            command=("git", "diff", "--check"),
            append_files=False,
            always=True,
        ),
        GatePlugin(
            id="gitleaks",
            globs=(),
            command=(
                "gitleaks",
                "detect",
                "--no-git",
                "--redact",
                "--source",
                "{workspace}",
            ),
            append_files=False,
            always=True,
        ),
    ]
    pyproject = workspace / "pyproject.toml"
    if pyproject.is_file() and "ruff" in pyproject.read_text(
        encoding="utf-8", errors="replace"
    ):
        plugins.extend(
            [
                GatePlugin(
                    id="ruff_lint",
                    globs=("*.py",),
                    command=("ruff", "check", "{files}"),
                ),
                GatePlugin(
                    id="ruff_format",
                    globs=("*.py",),
                    command=("ruff", "format", "--check", "{files}"),
                ),
            ]
        )
    if next(iter(workspace.glob("biome.json*")), None) is not None:
        plugins.append(
            GatePlugin(
                id="biome",
                globs=("*.js", "*.jsx", "*.ts", "*.tsx", "*.json", "*.css"),
                command=("biome", "check", "{files}"),
            )
        )
    plugins.extend(
        [
            GatePlugin(
                id="actionlint",
                globs=(".github/workflows/*.yml", ".github/workflows/*.yaml"),
                command=("actionlint", "{files}"),
            ),
            GatePlugin(
                id="shellcheck",
                globs=("*.sh", "*.bash"),
                command=("shellcheck", "{files}"),
            ),
        ]
    )
    return plugins


def _required_files_match(workspace: Path, plugin: GatePlugin) -> bool:
    if not plugin.required_files:
        return True
    matched: list[Path] = []
    for pattern in plugin.required_files:
        matched.extend(workspace.glob(pattern))
    if not matched:
        return False
    if plugin.config_contains is None:
        return True
    return any(
        path.is_file()
        and plugin.config_contains in path.read_text(encoding="utf-8", errors="replace")
        for path in matched
    )


def load_plugins(workspace: Path) -> list[GatePlugin]:
    plugins = builtin_plugins(workspace)
    config_candidates = [
        workspace / ".sage" / "gates.json",
        workspace / ".sage-gates.json",
    ]
    for config_path in config_candidates:
        if not config_path.is_file():
            continue
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise GateConfigurationError(f"invalid JSON: {config_path}") from error
        if payload.get("version") != 1 or not isinstance(payload.get("gates"), list):
            raise GateConfigurationError(
                f"{config_path} must contain version=1 and a gates array"
            )
        plugins.extend(GatePlugin.from_json(raw) for raw in payload["gates"])
    ids: set[str] = set()
    for plugin in plugins:
        if plugin.id in ids:
            raise GateConfigurationError(f"duplicate gate id: {plugin.id}")
        ids.add(plugin.id)
    return plugins


def select_plugin_commands(
    workspace: Path, changed_files: list[str]
) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    for plugin in load_plugins(workspace):
        matching = [path for path in changed_files if _matches(path, plugin.globs)]
        if not plugin.always and not matching:
            continue
        if not _required_files_match(workspace, plugin):
            continue
        command: list[str] = []
        files_expanded = False
        for part in plugin.command:
            if part == "{files}":
                command.extend(matching)
                files_expanded = True
            else:
                command.append(part.replace("{workspace}", str(workspace)))
        if plugin.append_files and not files_expanded:
            command.extend(matching)
        commands.append((plugin.id, command))
    return commands
