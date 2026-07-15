"""Obsidian-compatible shared memory, capability preflight, and version ledger."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Iterator
import unicodedata

from workflow.gates import detect_languages
from workflow.version_snapshot import (
    VersionSnapshotError,
    worktree_snapshot_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
LANGUAGE_CATALOG = ROOT / "workflow" / "language-gates.json"
ROUTE_AGENTS = {
    "fast": ("agy",),
    "standard": ("claude",),
    "high": ("agy", "codex", "claude"),
}
VERSION_COMMANDS = {
    "agy": ("agy", "--version"),
    "claude": ("claude", "--version"),
    "codex": ("codex", "--version"),
    "codegraph": ("codegraph", "version"),
    "git": ("git", "--version"),
    "gitleaks": ("gitleaks", "version"),
}
STITCH_TARGETS = (
    r"\bwpf\b",
    r"\bxaml\b",
    r"\bweb(?:site)?\s+(?:ui|design|layout)\b",
    r"\bfrontend\s+(?:ui|design|layout)\b",
    r"\bdesktop\s+(?:ui|visual\s+(?:ui|design))\b",
    r"\bui/ux\b",
    r"\blanding\s+page\b",
    r"\bvisual\s+design\b",
    r"網頁",
    r"網站(?:介面|界面|設計)",
    r"(?:介面|界面|視覺)設計",
)
STITCH_ACTIONS = (
    r"\b(?:design|build|create|implement|redesign|revamp|prototype|style|"
    r"update|restyle|rework)\b"
)


class KnowledgeError(RuntimeError):
    """The shared knowledge or version record could not be made durable."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip("-.")
    return slug or "project"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _atomic_write(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _json_write(path: Path, value: Any) -> None:
    _atomic_write(path, json.dumps(value, indent=2) + "\n")


def _json_read(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise KnowledgeError(f"invalid knowledge state: {path}") from error


def _normalized_repository_path(value: str) -> str:
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or re.match(r"^[A-Za-z]:", value)
    ):
        raise KnowledgeError(f"invalid repository knowledge path: {value!r}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise KnowledgeError("repository knowledge path is not valid UTF-8") from error
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise KnowledgeError(f"non-normalized repository knowledge path: {value!r}")
    return value


def _assert_unambiguous_paths(paths: list[str]) -> None:
    aliases: dict[str, str] = {}
    for path in paths:
        alias = unicodedata.normalize("NFC", path).casefold()
        previous = aliases.setdefault(alias, path)
        if previous != path:
            raise KnowledgeError(
                f"ambiguous repository knowledge paths: {previous!r} and {path!r}"
            )


def _pending_vault_paths(repo: Path, vault_path: str) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignored=no",
            "--",
            vault_path,
        ],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        raise KnowledgeError(f"cannot discover pending knowledge files: {detail}")

    entries = completed.stdout.split(b"\0")
    pending: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            raise KnowledgeError("git returned malformed pending knowledge status")
        status = entry[:2].decode("ascii", errors="strict")
        path = _normalized_repository_path(os.fsdecode(entry[3:]))
        if "D" in status or "R" in status:
            raise KnowledgeError(f"pending knowledge deletion is forbidden: {path}")
        if "U" in status or status in {"AA", "DD"}:
            raise KnowledgeError(f"conflicted pending knowledge file: {path}")
        if "C" in status:
            if index >= len(entries) or not entries[index]:
                raise KnowledgeError("git returned malformed copied knowledge status")
            index += 1
        if path != vault_path and not path.startswith(f"{vault_path}/"):
            raise KnowledgeError(f"pending knowledge file is outside its vault: {path}")
        pending.append(path)

    if len(pending) != len(set(pending)):
        raise KnowledgeError("duplicate pending repository knowledge path")
    _assert_unambiguous_paths(pending)
    return sorted(pending)


def _assert_regular_repository_file(repo: Path, relative: str) -> Path:
    path = repo
    for part in relative.split("/"):
        path /= part
        if path.is_symlink():
            raise KnowledgeError(
                f"pending knowledge path contains a symlink: {relative}"
            )
    if not path.exists():
        raise KnowledgeError(f"pending knowledge file is missing: {relative}")
    if not path.is_file():
        raise KnowledgeError(
            f"pending knowledge path is not a regular file: {relative}"
        )
    return path


def _repository_vault_path(repo: Path, vault: Path) -> str | None:
    try:
        relative = vault.relative_to(repo).as_posix()
    except ValueError:
        return None
    return _normalized_repository_path(relative)


def _validated_pending_repository_files(
    repo: Path, vault: Path
) -> tuple[str | None, list[tuple[str, Path]]]:
    vault_path = _repository_vault_path(repo, vault)
    if vault_path is None:
        return None, []
    pending = [
        (relative, _assert_regular_repository_file(repo, relative))
        for relative in _pending_vault_paths(repo, vault_path)
    ]
    return vault_path, pending


def _snapshot_repository_files(
    *, repo: Path, vault: Path, snapshots: Path
) -> tuple[dict[str, Any], dict[str, str]]:
    repository_tree = snapshots / "repository"
    if repository_tree.exists() or repository_tree.is_symlink():
        raise KnowledgeError("repository knowledge snapshot tree already exists")
    repository_tree.mkdir()

    vault_relative, pending = _validated_pending_repository_files(repo, vault)
    files: dict[str, str] = {}
    artifact_hashes: dict[str, str] = {}
    for relative, source in pending:
        content = source.read_bytes()
        destination = repository_tree.joinpath(*relative.split("/"))
        _atomic_write_bytes(destination, content)
        digest = _sha256_bytes(content)
        files[relative] = digest
        artifact_hashes[f"repository/{relative}"] = digest

    metadata = {
        "schema_version": 1,
        "vault_path": vault_relative,
        "files": files,
    }
    metadata_path = snapshots / "repository-files.json"
    _json_write(metadata_path, metadata)
    artifact_hashes["repository-files.json"] = _sha256_file(metadata_path)
    return metadata, artifact_hashes


def _next_version(current: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current)
    if not match:
        raise KnowledgeError(f"invalid semantic version in knowledge state: {current}")
    major, minor, patch = (int(part) for part in match.groups())
    if (major, minor, patch) == (0, 0, 0):
        return "0.1.0"
    return f"{major}.{minor}.{patch + 1}"


def _command_version(name: str, cwd: Path) -> dict[str, Any]:
    command = list(VERSION_COMMANDS[name])
    executable = shutil.which(command[0])
    if executable is None:
        return {
            "available": False,
            "exit_code": 127,
            "version": None,
            "command": command,
        }
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [executable, *command[1:]],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
        version = completed.stdout.strip().splitlines()
        return {
            "available": completed.returncode == 0,
            "exit_code": completed.returncode,
            "version": version[0][:240] if version else None,
            "command": command,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "exit_code": 124,
            "version": None,
            "command": command,
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def task_requires_stitch(task_name: str, spec_text: str) -> bool:
    """Return whether a task includes Web, desktop, or WPF visual design work."""

    explicit = re.search(
        r"(?:stitch_required\s*:\s*true|\[stitch-ui\])",
        f"{task_name}\n{spec_text}",
        flags=re.IGNORECASE,
    )
    if explicit:
        return True
    target = "(?:" + "|".join(STITCH_TARGETS) + ")"
    name = task_name.lower().replace("-", " ").replace("_", " ")
    if re.search(target, name, flags=re.IGNORECASE) and re.search(
        STITCH_ACTIONS, name, flags=re.IGNORECASE
    ):
        return True
    strong_action = (
        r"\b(?:design|build|create|implement|redesign|revamp|prototype|style|update|"
        r"restyle|rework)\b"
    )
    reverse_strong_action = (
        r"\b(?:build|create|implement|redesign|revamp|prototype|style|update|"
        r"restyle|rework)\b"
    )
    if re.search(
        rf"{strong_action}[^.\n]{{0,80}}{target}"
        rf"|{target}[^.\n]{{0,40}}{reverse_strong_action}",
        spec_text,
        flags=re.IGNORECASE,
    ):
        return True
    english = (
        rf"{STITCH_ACTIONS}[^.\n]{{0,80}}{target}"
        rf"|{target}[^.\n]{{0,40}}{STITCH_ACTIONS}"
    )
    chinese = (
        r"(?:設計|建立|製作|新增|開發|重做|改版)[^。\n]{0,40}"
        r"(?:網頁|網站(?:介面|界面)|WPF|XAML)"
        r"|(?:網頁|網站(?:介面|界面)|WPF|XAML)[^。\n]{0,40}"
        r"(?:設計|建立|製作|新增|開發|重做|改版)"
    )
    policy_task = re.search(
        r"\b(?:policy|governance|rules?|documentation|docs?)\b",
        name,
        flags=re.IGNORECASE,
    )
    policy_line = re.compile(
        r"^\s*(?=[^\n]*\bstitch\b)(?=[^\n]*\b(?:policy|rule|dispatch|export|lock)\w*\b)"
        r"(?:require|mandate|enforce|document|update)\b",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if policy_task and policy_line.search(spec_text):
        non_policy_spec = "\n".join(
            line for line in spec_text.splitlines() if not policy_line.search(line)
        )
        if not (
            re.search(english, non_policy_spec, flags=re.IGNORECASE)
            or re.search(chinese, non_policy_spec, flags=re.IGNORECASE)
        ):
            return False
    return bool(
        re.search(english, spec_text, flags=re.IGNORECASE)
        or re.search(chinese, spec_text, flags=re.IGNORECASE)
    )


def _stitch_mcp_probe(client: str, cwd: Path) -> dict[str, Any]:
    """Inspect Stitch MCP health without reading or printing configured headers."""

    command = [client, "mcp", "list"]
    executable = shutil.which(client)
    if executable is None:
        return {
            "configured": False,
            "authenticated": False,
            "tools_ready": False,
            "status": "client_unavailable",
            "command": command,
        }
    try:
        completed = subprocess.run(
            [executable, "mcp", "list"],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "configured": False,
            "authenticated": False,
            "tools_ready": False,
            "status": "probe_timeout",
            "command": command,
        }

    lines = [line.strip() for line in completed.stdout.splitlines()]
    stitch_lines = [line for line in lines if line.lower().startswith("stitch:")]
    if client == "codex":
        stitch_lines.extend(
            line
            for line in lines
            if line.lower().startswith("stitch ") and line not in stitch_lines
        )
    configured = bool(stitch_lines)
    status_text = " ".join(stitch_lines).lower()
    authenticated = (
        configured
        and "connected" in status_text
        and not any(
            marker in status_text
            for marker in ("needs authentication", "not connected", "unauthorized")
        )
    )
    unhealthy = any(
        marker in status_text
        for marker in ("tools fetch failed", "needs authentication", "not connected")
    )
    tools_ready = (
        completed.returncode == 0
        and authenticated
        and not unhealthy
        and "✔ connected" in status_text
    )
    if tools_ready:
        status = "ready"
    elif authenticated:
        status = "authenticated_tools_unavailable"
    elif configured:
        status = "configured_unhealthy"
    elif completed.returncode != 0:
        status = "probe_failed"
    else:
        status = "not_configured"
    return {
        "configured": configured,
        "authenticated": authenticated,
        "tools_ready": tools_ready,
        "status": status,
        "command": command,
    }


def stitch_capability(
    stitch_design: Path | None, *, cwd: Path | None = None
) -> dict[str, Any]:
    """Assess Stitch design and auth paths without exposing credential values."""

    cwd = (cwd or ROOT).resolve()
    artifact = (
        stitch_design.expanduser().resolve() if stitch_design is not None else None
    )
    artifact_ready = bool(artifact and artifact.is_file())
    api_key_ready = bool(os.environ.get("STITCH_API_KEY"))
    oauth_ready = bool(
        os.environ.get("STITCH_ACCESS_TOKEN") and os.environ.get("GOOGLE_CLOUD_PROJECT")
    )
    mcp_clients: dict[str, Any] = {}
    if not (artifact_ready or api_key_ready or oauth_ready):
        mcp_clients = {
            client: _stitch_mcp_probe(client, cwd) for client in ("claude", "codex")
        }
    mcp_ready = any(client["tools_ready"] for client in mcp_clients.values())
    mcp_authenticated = any(client["authenticated"] for client in mcp_clients.values())
    available = artifact_ready or api_key_ready or oauth_ready or mcp_ready
    if artifact_ready:
        version = "Stitch DESIGN.md export present"
        auth_mode = "design_artifact"
    elif api_key_ready:
        version = "Stitch MCP/SDK API-key authentication configured"
        auth_mode = "api_key"
    elif oauth_ready:
        version = "Stitch MCP/SDK OAuth authentication configured"
        auth_mode = "oauth"
    elif mcp_ready:
        version = "Stitch MCP authenticated and tools available"
        auth_mode = "mcp_client"
    else:
        version = None
        auth_mode = None
    if available:
        status = "ready"
    elif mcp_authenticated:
        status = "authenticated_tools_unavailable"
    elif any(client["configured"] for client in mcp_clients.values()):
        status = "configured_unhealthy"
    else:
        status = "authentication_required"
    return {
        "available": available,
        "exit_code": 0 if available else 1,
        "version": version,
        "status": status,
        "auth_mode": auth_mode,
        "command": ["stitch", "safe-capability-check"],
        "artifact": str(artifact) if artifact_ready else None,
        "mcp_clients": mcp_clients,
    }


def assess_capabilities(
    route: str,
    repo: Path,
    *,
    signing_key: Path | None = None,
    require_stitch: bool = False,
    stitch_design: Path | None = None,
) -> dict[str, Any]:
    if route not in ROUTE_AGENTS:
        raise KnowledgeError(f"unknown workflow route: {route}")
    required = [*ROUTE_AGENTS[route], "git", "gitleaks", "codegraph"]
    tools = {name: _command_version(name, repo) for name in required}
    obsidian = shutil.which("obsidian")
    tools["obsidian"] = {
        "available": obsidian is not None,
        "exit_code": 0 if obsidian else 127,
        "version": "Obsidian desktop CLI available" if obsidian else None,
        "command": ["obsidian"],
    }
    if require_stitch:
        required.append("stitch")
        tools["stitch"] = stitch_capability(stitch_design, cwd=repo)
    if signing_key is not None:
        key = signing_key.expanduser().resolve()
        public_key = Path(f"{key}.pub")
        tools["evidence_signing_key"] = {
            "available": key.is_file() and public_key.is_file(),
            "exit_code": 0 if key.is_file() and public_key.is_file() else 1,
            "version": "private and public key present"
            if key.is_file() and public_key.is_file()
            else None,
            "command": ["filesystem", "signing-key-pair"],
        }
    return {
        "route": route,
        "required": required,
        "tools": tools,
        "passed": all(tool["available"] for tool in tools.values()),
    }


def _git_files(repo: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise KnowledgeError(f"cannot inspect project files: {completed.stderr}")
    return completed.stdout.splitlines()


def _repository_identity(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    remote = completed.stdout.strip()
    return remote if completed.returncode == 0 and remote else repo.name


def default_project_id(repo: Path) -> str:
    identity = _repository_identity(repo)
    identity = re.sub(r"^(?:https?://|ssh://|git@)", "", identity)
    identity = identity.removesuffix(".git")
    return _slug(identity)


@dataclass
class MemorySession:
    vault: "KnowledgeVault"
    preflight: dict[str, Any]
    run_dir: Path
    finalized: bool = False

    def complete(
        self,
        *,
        passed: bool,
        checks: dict[str, Any],
        stages: list[dict[str, Any]],
        changed_files: list[str],
        source_head: str,
    ) -> dict[str, Any]:
        result = self.vault.finalize_task(
            self.preflight,
            run_dir=self.run_dir,
            passed=passed,
            checks=checks,
            stages=stages,
            changed_files=changed_files,
            source_head=source_head,
        )
        self.finalized = True
        return result

    def fail(
        self,
        error: BaseException,
        *,
        checks: dict[str, Any] | None = None,
        stages: list[dict[str, Any]] | None = None,
        changed_files: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if self.finalized:
            return None
        result = self.vault.finalize_task(
            self.preflight,
            run_dir=self.run_dir,
            passed=False,
            checks=checks
            or {
                "workflow_exception": {
                    "exit_code": 1,
                    "output": f"{type(error).__name__}: {error}",
                }
            },
            stages=stages or [],
            changed_files=changed_files or [],
            source_head=self.preflight["source_head"],
        )
        self.finalized = True
        return result


class KnowledgeVault:
    """A single-writer Obsidian vault shared with agents through snapshots."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self._ensure_vault()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock_path = self.root / ".sage-memory.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _ensure_vault(self) -> None:
        for relative in (
            ".obsidian",
            "Projects",
            "Tasks",
            "Topics/Languages",
            "Topics/Tools",
            "System",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        app = self.root / ".obsidian" / "app.json"
        if not app.is_file():
            _json_write(
                app, {"newFileLocation": "folder", "newFileFolderPath": "Inbox"}
            )
        policy = self.root / "System" / "Memory Policy.md"
        if not policy.is_file():
            _atomic_write(
                policy,
                "# SAGE Memory Policy\n\n"
                "- The orchestrator is the only writer.\n"
                "- Agents receive the same immutable `SAGE_KNOWLEDGE.md` snapshot.\n"
                "- Preflight must pass before dispatch.\n"
                "- Failed tasks are remembered but do not advance project version.\n"
                "- Successful code changes require a CodeGraph refresh and `Ver.md` entry.\n"
                "- Web UI, website UI, and WPF visual design must use Stitch before coding.\n",
            )
        self._render_home()

    def _render_home(self) -> None:
        projects = sorted(
            path.name for path in (self.root / "Projects").iterdir() if path.is_dir()
        )
        lines = [
            "# SAGE Knowledge Vault",
            "",
            "Obsidian-compatible persistent memory owned by the unattended orchestrator.",
            "",
            "## Projects",
            "",
        ]
        lines.extend(
            f"- [[Projects/{project}/Memory|{project}]] · [[Projects/{project}/Ver|versions]]"
            for project in projects
        )
        lines.extend(["", "## Policy", "", "- [[System/Memory Policy]]", ""])
        tools = sorted((self.root / "Topics" / "Tools").glob("*.md"))
        if tools:
            lines.extend(
                [
                    "## Required design tools",
                    "",
                    *[f"- [[Topics/Tools/{path.stem}|{path.stem}]]" for path in tools],
                    "",
                ]
            )
        _atomic_write(self.root / "Home.md", "\n".join(lines))

    def _project_paths(self, project_id: str) -> dict[str, Path]:
        base = self.root / "Projects" / project_id
        base.mkdir(parents=True, exist_ok=True)
        return {
            "base": base,
            "state": base / "State.json",
            "memory": base / "Memory.md",
            "versions": base / "Ver.md",
        }

    def _state(self, project_id: str, repo: Path) -> dict[str, Any]:
        paths = self._project_paths(project_id)
        return _json_read(
            paths["state"],
            {
                "schema_version": 1,
                "project_id": project_id,
                "repository": _repository_identity(repo),
                "current_version": "0.0.0",
                "history": [],
            },
        )

    def _language_knowledge(
        self, languages: list[str], *, project_id: str, observed_at: str
    ) -> tuple[list[str], list[str]]:
        catalog = json.loads(LANGUAGE_CATALOG.read_text(encoding="utf-8"))["languages"]
        missing = sorted(set(languages) - set(catalog))
        notes: list[str] = []
        for language in languages:
            if language not in catalog:
                continue
            candidate = catalog[language]
            path = self.root / "Topics" / "Languages" / f"{language}.md"
            _atomic_write(
                path,
                "\n".join(
                    [
                        "---",
                        f"language: {language}",
                        f"last_observed: {observed_at}",
                        f"last_project: {project_id}",
                        "---",
                        f"# {language}",
                        "",
                        f"- Gate candidate: `{candidate['gate']}`",
                        f"- Required tool: `{candidate['tool']}`",
                        "- Example argv: `" + " ".join(candidate["example_argv"]) + "`",
                        "- Commands remain opt-in until the project declares a trusted gate.",
                        "",
                    ]
                ),
            )
            notes.append(str(path.relative_to(self.root)))
        return notes, missing

    def prepare_task(
        self,
        *,
        repo: Path,
        route: str,
        task_name: str,
        spec: Path,
        acceptance: list[str],
        source_head: str,
        project_id: str | None = None,
        signing_key: Path | None = None,
        stitch_design: Path | None = None,
        require_stitch: bool = False,
    ) -> dict[str, Any]:
        repo = repo.resolve()
        spec = spec.resolve()
        project_id = _slug(project_id) if project_id else default_project_id(repo)
        observed_at = _utc_now()
        spec_text = spec.read_text(encoding="utf-8", errors="replace")
        stitch_required = require_stitch or task_requires_stitch(task_name, spec_text)
        stitch_design = (
            stitch_design.expanduser().resolve() if stitch_design is not None else None
        )
        stitch_design_ready = bool(stitch_design and stitch_design.is_file())
        capability = assess_capabilities(
            route,
            repo,
            signing_key=signing_key,
            require_stitch=stitch_required,
            stitch_design=stitch_design,
        )
        languages = detect_languages(_git_files(repo))
        with self._lock():
            state = self._state(project_id, repo)
            notes, missing = self._language_knowledge(
                languages, project_id=project_id, observed_at=observed_at
            )
            if stitch_required:
                notes.append("Topics/Tools/stitch.md")
                if not stitch_design_ready:
                    missing.append("Stitch DESIGN.md export")
            current_version = state["current_version"]
            planned_version = _next_version(current_version)
            task_id = (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                + "-"
                + _slug(task_name)
            )
            task_note = Path("Tasks") / project_id / f"{task_id}.md"
            ready = capability["passed"] and not missing
            task_text = self._task_note(
                task_id=task_id,
                task_name=task_name,
                project_id=project_id,
                status="preflight_ready" if ready else "preflight_blocked",
                observed_at=observed_at,
                route=route,
                source_head=source_head,
                spec_sha256=_sha256_file(spec),
                acceptance=acceptance,
                languages=languages,
                capability=capability,
                current_version=current_version,
                planned_version=planned_version,
                codegraph=None,
                changed_files=[],
                failing_checks=[],
                distilled_lesson="Capability and relevant language knowledge assessed before dispatch.",
            )
            _atomic_write(self.root / task_note, task_text)
            memory_path = self._project_paths(project_id)["memory"]
            prior_memory = (
                memory_path.read_text(encoding="utf-8")[-6000:]
                if memory_path.is_file()
                else "No prior project memory has been distilled yet."
            )
            briefing = self._briefing(
                project_id=project_id,
                task_name=task_name,
                route=route,
                source_head=source_head,
                languages=languages,
                current_version=current_version,
                planned_version=planned_version,
                prior_memory=prior_memory,
                language_notes=notes,
                stitch={
                    "required": stitch_required,
                    "design_path": str(stitch_design) if stitch_design_ready else None,
                    "design_sha256": _sha256_file(stitch_design)
                    if stitch_design_ready and stitch_design is not None
                    else None,
                },
            )
            self._render_home()

        return {
            "schema_version": 1,
            "prepared_at": observed_at,
            "ready": ready,
            "project_id": project_id,
            "task_id": task_id,
            "task_name": task_name,
            "task_note": str(task_note),
            "route": route,
            "repository": str(repo),
            "source_head": source_head,
            "spec_sha256": _sha256_file(spec),
            "acceptance_sha256": _sha256_bytes(
                (json.dumps(acceptance, sort_keys=True) + "\n").encode()
            ),
            "acceptance_count": len(acceptance),
            "languages": languages,
            "language_notes": notes,
            "missing_knowledge": missing,
            "stitch": {
                "required": stitch_required,
                "design_path": str(stitch_design) if stitch_design_ready else None,
                "design_sha256": _sha256_file(stitch_design)
                if stitch_design_ready and stitch_design is not None
                else None,
            },
            "capability": capability,
            "current_version": current_version,
            "planned_version": planned_version,
            "briefing": briefing,
            "briefing_sha256": _sha256_bytes(briefing.encode()),
            "codegraph": {"status": "required_before_dispatch"},
        }

    def record_dispatch(
        self,
        preflight: dict[str, Any],
        *,
        run_dir: Path,
        codegraph: dict[str, Any],
    ) -> None:
        if not codegraph.get("passed"):
            raise KnowledgeError("CodeGraph must be current before agent dispatch")
        preflight["codegraph"] = {
            "status": "current",
            "action": codegraph.get("action"),
            "files": codegraph.get("files"),
            "nodes": codegraph.get("nodes"),
            "edges": codegraph.get("edges"),
        }
        public = {key: value for key, value in preflight.items() if key != "briefing"}
        _json_write(run_dir / "preflight.json", public)
        knowledge_dir = run_dir / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(knowledge_dir / "briefing.md", preflight["briefing"])
        with self._lock():
            note_path = self.root / preflight["task_note"]
            content = note_path.read_text(encoding="utf-8")
            content += (
                "\n## Dispatch\n\n"
                f"- CodeGraph: current ({codegraph.get('files')} files, "
                f"{codegraph.get('nodes')} nodes, {codegraph.get('edges')} edges)\n"
                f"- Shared briefing SHA-256: `{preflight['briefing_sha256']}`\n"
                "- The same read-only briefing is supplied to every CLI stage.\n"
            )
            _atomic_write(note_path, content)

    def session(self, preflight: dict[str, Any], run_dir: Path) -> MemorySession:
        return MemorySession(self, preflight, run_dir.resolve())

    def finalize_task(
        self,
        preflight: dict[str, Any],
        *,
        run_dir: Path,
        passed: bool,
        checks: dict[str, Any],
        stages: list[dict[str, Any]],
        changed_files: list[str],
        source_head: str,
    ) -> dict[str, Any]:
        completed_at = _utc_now()
        stage_failures = [
            str(stage.get("label") or stage.get("agent") or "unknown")
            for stage in stages
            if stage.get("exit_code") != 0
        ]
        success_rejected = bool(
            passed
            and (
                not changed_files
                or not stages
                or stage_failures
                or any(
                    not isinstance(check, dict) or check.get("exit_code") != 0
                    for check in checks.values()
                )
            )
        )
        if success_rejected:
            checks = dict(checks)
            checks["knowledge_success_invariants"] = {
                "exit_code": 1,
                "output": {
                    "changed_files_nonempty": bool(changed_files),
                    "stages_nonempty": bool(stages),
                    "failed_stages": stage_failures,
                },
            }
            passed = False
        failing = sorted(
            name
            for name, check in checks.items()
            if not isinstance(check, dict) or check.get("exit_code") != 0
        )
        distilled = (
            "Automated gates passed with an immutable candidate, current CodeGraph, "
            "and a shared knowledge briefing. Reuse this route and gate set."
            if passed
            else "Task failed closed. Investigate these checks before retrying: "
            + (", ".join(failing) if failing else "workflow exception")
        )
        project_id = preflight["project_id"]
        repo = Path(preflight["repository"]).resolve()
        snapshots = run_dir / "knowledge"
        repository_tree = snapshots / "repository"
        if repository_tree.exists() or repository_tree.is_symlink():
            raise KnowledgeError("repository knowledge snapshot tree already exists")
        with self._lock():
            # Validate pre-existing pending state before a successful run advances
            # the version. The snapshot pass repeats this after finalization so the
            # exact records just written are the ones copied and hashed.
            _validated_pending_repository_files(repo, self.root)
            paths = self._project_paths(project_id)
            state = self._state(project_id, Path(preflight["repository"]))
            if state["current_version"] != preflight["current_version"]:
                raise KnowledgeError(
                    "project version changed concurrently after task preflight"
                )
            version = (
                preflight["planned_version"] if passed else state["current_version"]
            )
            candidate_tree_sha256 = None
            if passed:
                try:
                    first_tree = worktree_snapshot_sha256(repo)
                    second_tree = worktree_snapshot_sha256(repo)
                except VersionSnapshotError as error:
                    raise KnowledgeError(
                        f"cannot bind successful version to candidate tree: {error}"
                    ) from error
                if first_tree != second_tree:
                    raise KnowledgeError(
                        "candidate tree changed while the version record was finalized"
                    )
                candidate_tree_sha256 = first_tree
            record = {
                "task_id": preflight["task_id"],
                "task_name": preflight["task_name"],
                "completed_at": completed_at,
                "status": "automated_gates_passed" if passed else "failed",
                "route": preflight["route"],
                "source_head": source_head,
                "version": version if passed else None,
                "version_bumped": passed,
                "languages": preflight["languages"],
                "changed_files": changed_files,
                "failing_checks": failing,
                "stage_agents": [stage.get("agent") for stage in stages],
                "distilled_lesson": distilled,
                "task_note": preflight["task_note"],
                "briefing_sha256": preflight["briefing_sha256"],
                "candidate_tree_sha256": candidate_tree_sha256,
                "codegraph": preflight["codegraph"],
                "stitch": {
                    "required": bool(preflight.get("stitch", {}).get("required")),
                    "design_sha256": preflight.get("stitch", {}).get("design_sha256"),
                    "artifact_name": "STITCH_DESIGN.md"
                    if preflight.get("stitch", {}).get("required")
                    else None,
                },
            }
            state["history"].append(record)
            if passed:
                state["schema_version"] = 2
                state["current_version"] = version
            _json_write(paths["state"], state)
            memory = self._render_memory(state)
            versions = self._render_versions(state)
            _atomic_write(paths["memory"], memory)
            _atomic_write(paths["versions"], versions)
            task = self._task_note(
                task_id=preflight["task_id"],
                task_name=preflight["task_name"],
                project_id=project_id,
                status=record["status"],
                observed_at=completed_at,
                route=preflight["route"],
                source_head=source_head,
                spec_sha256=preflight["spec_sha256"],
                acceptance=["recorded-by-hash"]
                * int(preflight.get("acceptance_count", 0)),
                languages=preflight["languages"],
                capability=preflight["capability"],
                current_version=preflight["current_version"],
                planned_version=preflight["planned_version"],
                codegraph=preflight["codegraph"],
                changed_files=changed_files,
                failing_checks=failing,
                distilled_lesson=distilled,
            )
            _atomic_write(self.root / preflight["task_note"], task)
            self._render_home()

            snapshots.mkdir(parents=True, exist_ok=True)
            snapshot_contents = {
                "briefing.md": preflight["briefing"],
                "task-note.md": task,
                "Memory.md": memory,
                "Ver.md": versions,
            }
            for name, content in snapshot_contents.items():
                _atomic_write(snapshots / name, content)
            state_snapshot = snapshots / "State.json"
            _atomic_write_bytes(state_snapshot, paths["state"].read_bytes())
            artifact_hashes = {
                name: _sha256_file(snapshots / name) for name in snapshot_contents
            }
            artifact_hashes["State.json"] = _sha256_file(state_snapshot)
            repository_metadata, repository_hashes = _snapshot_repository_files(
                repo=repo,
                vault=self.root,
                snapshots=snapshots,
            )
            artifact_hashes.update(repository_hashes)
            summary = {
                "schema_version": 1,
                "project_id": project_id,
                "task_id": preflight["task_id"],
                "completed_at": completed_at,
                "version": version,
                "version_bumped": passed,
                "memory_distilled": True,
                "codegraph_current": preflight["codegraph"].get("status") == "current",
                "shared_briefing_sha256": preflight["briefing_sha256"],
                "repository_vault": repository_metadata["vault_path"],
                "repository_file_count": len(repository_metadata["files"]),
                "artifacts": artifact_hashes,
            }
            _json_write(snapshots / "post-task.json", summary)
            summary["post_task_sha256"] = _sha256_file(snapshots / "post-task.json")
            return summary

    def _briefing(
        self,
        *,
        project_id: str,
        task_name: str,
        route: str,
        source_head: str,
        languages: list[str],
        current_version: str,
        planned_version: str,
        prior_memory: str,
        language_notes: list[str],
        stitch: dict[str, Any],
    ) -> str:
        return "\n".join(
            [
                "# SAGE Shared Knowledge — Read Only",
                "",
                f"- Project: `{project_id}`",
                f"- Task: `{task_name}`",
                f"- Route: `{route}`",
                f"- Source HEAD: `{source_head}`",
                f"- Detected languages: {', '.join(languages) or 'documentation-only'}",
                f"- Version: `{current_version}` → planned `{planned_version}`",
                "",
                "## Mandatory workflow knowledge",
                "",
                "1. Read `WORKFLOW_TASK.md` and this briefing before acting.",
                "2. Use `codegraph explore` before grep/find when locating or understanding code.",
                "3. Do not edit `SAGE_KNOWLEDGE.md`, task contracts, protected tests, or gate configs.",
                "4. Machine green never means human R5 or merge authorization.",
                "5. The orchestrator alone writes memory and `Ver.md` after the task.",
                "6. Web UI, website UI, desktop visual UI, and WPF/XAML design require Stitch first; use the locked `STITCH_DESIGN.md` as the visual source of truth.",
                "",
                "## Stitch design gate",
                "",
                f"- Required: {str(bool(stitch.get('required'))).lower()}",
                f"- Design SHA-256: `{stitch.get('design_sha256') or 'not-required'}`",
                "",
                "## Relevant knowledge notes",
                "",
                *[f"- `[[{note.removesuffix('.md')}]]`" for note in language_notes],
                "",
                "## Distilled project memory",
                "",
                prior_memory,
                "",
            ]
        )

    def _task_note(
        self,
        *,
        task_id: str,
        task_name: str,
        project_id: str,
        status: str,
        observed_at: str,
        route: str,
        source_head: str,
        spec_sha256: str,
        acceptance: list[str],
        languages: list[str],
        capability: dict[str, Any],
        current_version: str,
        planned_version: str,
        codegraph: dict[str, Any] | None,
        changed_files: list[str],
        failing_checks: list[str],
        distilled_lesson: str,
    ) -> str:
        tools = capability.get("tools", {})
        lines = [
            "---",
            f"task_id: {task_id}",
            f"project: {project_id}",
            f"status: {status}",
            f"observed_at: {observed_at}",
            f"route: {route}",
            "---",
            f"# {task_name}",
            "",
            f"Project memory: [[Projects/{project_id}/Memory]]",
            f"Version ledger: [[Projects/{project_id}/Ver]]",
            "",
            "## Contract",
            "",
            f"- Source HEAD: `{source_head}`",
            f"- Spec SHA-256: `{spec_sha256}`",
            f"- Acceptance commands: {len(acceptance)} recorded by hash in preflight",
            f"- Languages: {', '.join(languages) or 'documentation-only'}",
            f"- Version: `{current_version}` → `{planned_version}` on success",
            "",
            "## Capability preflight",
            "",
        ]
        lines.extend(
            f"- {name}: {'ready' if tool.get('available') else 'missing'}"
            + (f" — `{tool.get('version')}`" if tool.get("version") else "")
            for name, tool in tools.items()
        )
        lines.extend(
            [
                "",
                "## CodeGraph",
                "",
                "- "
                + (json.dumps(codegraph, sort_keys=True) if codegraph else "pending"),
                "",
                "## Result",
                "",
                f"- Changed files: {', '.join(changed_files) or 'none yet'}",
                f"- Failing checks: {', '.join(failing_checks) or 'none'}",
                "",
                "## Distilled lesson",
                "",
                distilled_lesson,
                "",
            ]
        )
        return "\n".join(lines)

    def _render_memory(self, state: dict[str, Any]) -> str:
        # Memory is part of the append-only ledger context, so retain every task
        # entry. Truncation made older State records unverifiable and deletable.
        history = state["history"]
        lines = [
            "---",
            f"project: {state['project_id']}",
            f"current_version: {state['current_version']}",
            "---",
            f"# {state['project_id']} Memory",
            "",
            f"Repository: `{state['repository']}`",
            "",
            "## Distilled task knowledge",
            "",
        ]
        for record in reversed(history):
            lines.extend(
                [
                    f"### {record['completed_at']} — {record['task_name']}",
                    "",
                    f"- Status: `{record['status']}`",
                    f"- Route: `{record['route']}`",
                    f"- Version: `{record['version'] or 'unchanged'}`",
                    f"- Lesson: {record['distilled_lesson']}",
                    f"- Detail: [[{record['task_note'].removesuffix('.md')}]]",
                    "",
                ]
            )
        return "\n".join(lines)

    def _render_versions(self, state: dict[str, Any]) -> str:
        successful = [record for record in state["history"] if record["version_bumped"]]
        lines = [
            "---",
            f"project: {state['project_id']}",
            f"current_version: {state['current_version']}",
            "version_policy: automatic_patch_after_successful_task",
            "---",
            f"# {state['project_id']} Versions",
            "",
            "Every successful project update must appear here; failed tasks never advance version.",
            "",
        ]
        for record in reversed(successful):
            entry = [
                f"## {record['version']} — {record['completed_at']}",
                "",
                f"- Task: [[{record['task_note'].removesuffix('.md')}|{record['task_name']}]]",
                f"- Source HEAD: `{record['source_head']}`",
                f"- Route: `{record['route']}`",
                f"- Changed: {', '.join(record['changed_files']) or 'no repository files'}",
                f"- Knowledge briefing: `{record['briefing_sha256']}`",
            ]
            if record.get("candidate_tree_sha256"):
                entry.append(f"- Candidate tree: `{record['candidate_tree_sha256']}`")
            stitch = record.get("stitch", {})
            if stitch.get("required"):
                entry.append(
                    f"- Stitch design: `{stitch.get('design_sha256') or 'missing'}`"
                )
            entry.extend(
                [
                    "- CodeGraph was current before dispatch and refreshed by gates.",
                    "",
                ]
            )
            lines.extend(entry)
        return "\n".join(lines)
