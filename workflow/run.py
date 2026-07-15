#!/usr/bin/env python3
"""Run the evidence-gated workflow against an isolated local clone."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable
import threading
import queue
import codecs
import signal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.budget import BudgetLedger, BudgetLimits
from workflow.acceptance import (
    acceptance_argv,
    acceptance_environment,
    missing_acceptance_shell,
)
from workflow.codegraph import refresh_codegraph
from workflow.evidence import write_signed_manifest
from workflow.gates import select_plugin_commands
from workflow.knowledge import KnowledgeVault, MemorySession


LAB_ROOT = Path(__file__).resolve().parents[1]
PROMPTS = Path(__file__).resolve().parent / "prompts"
RUNS = LAB_ROOT / "runs" / "pilots"
CONFIG = Path(__file__).resolve().parent / "config.json"
DEFAULT_KNOWLEDGE_VAULT = LAB_ROOT / "knowledge"
ACTIVE_MEMORY_SESSION: MemorySession | None = None
CRITICAL_GIT_METADATA = (
    "HEAD",
    "config",
    "config.worktree",
    "info/attributes",
    "info/exclude",
    "info/grafts",
    "objects/info/alternates",
    "shallow",
)
ALLOWED_IGNORED_PREFIXES = (".codegraph/",)
GATE_RUNTIME_BOUNDARY = {
    "assurance": "trusted-gate-runtime",
    "filesystem_sandbox": False,
    "network_sandbox": False,
    "credential_environment_minimized": True,
    "source_remote_removed": True,
    "static_symlink_escape_rejected": True,
    "hostile_candidate_requires_external_container_or_vm": True,
}


class StageExecutionError(RuntimeError):
    """A mandatory CLI stage failed after its evidence was durably recorded."""

    def __init__(
        self,
        message: str,
        *,
        checks: dict[str, dict[str, object]],
        stages: list[dict[str, object]],
        changed_files: list[str],
    ):
        super().__init__(message)
        self.checks = checks
        self.stages = stages
        self.changed_files = changed_files


def execute(
    command: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    timeout: int = 900,
    env: dict[str, str] | None = None,
    idle_timeout: float | None = None,
    heartbeat_interval: float | None = None,
    termination_grace_seconds: float = 5.0,
    event_callback: Callable[[dict[str, object]], None] | None = None,
    output_path: Path | None = None,
    max_capture_bytes: int = 4 * 1024 * 1024,
) -> dict[str, object]:
    if idle_timeout is not None and idle_timeout <= 0:
        raise ValueError("idle_timeout must be positive")
    if heartbeat_interval is not None and heartbeat_interval <= 0:
        raise ValueError("heartbeat_interval must be positive")
    if termination_grace_seconds <= 0:
        raise ValueError("termination_grace_seconds must be positive")
    if max_capture_bytes <= 0:
        raise ValueError("max_capture_bytes must be positive")

    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        preexec_fn = None
    else:
        creationflags = 0
        preexec_fn = os.setsid

    started = time.monotonic()

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=creationflags,
            preexec_fn=preexec_fn,
        )
    except FileNotFoundError as error:
        return {
            "command": command,
            "exit_code": 127,
            "timed_out": False,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": str(error),
            "timeout_reason": None,
            "first_output_seconds": None,
            "last_output_seconds": None,
            "output_truncated": False,
            "termination_description": "not found",
        }

    q = queue.Queue()

    def reader_thread():
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            while True:
                data = os.read(process.stdout.fileno(), 4096)
                if not data:
                    text = decoder.decode(b"", final=True)
                    if text:
                        q.put(("output", text))
                    break
                text = decoder.decode(data)
                if text:
                    q.put(("output", text))
        except Exception:
            pass
        finally:
            q.put(("eof", None))

    def writer_thread():
        try:
            if input_text is not None and process.stdin is not None:
                process.stdin.write(input_text.encode("utf-8"))
        except Exception:
            pass
        finally:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except Exception:
                    pass

    t_reader = threading.Thread(target=reader_thread, daemon=True)
    t_reader.start()

    if input_text is not None:
        t_writer = threading.Thread(target=writer_thread, daemon=True)
        t_writer.start()

    timed_out = False
    timeout_reason = None
    first_output_seconds = None
    last_output_seconds = None
    output_truncated = False
    captured_output = []
    captured_bytes = 0
    interrupted = False

    if output_path is not None:
        output_file = open(output_path, "a", encoding="utf-8")
    else:
        output_file = None

    last_heartbeat = started
    last_output = started

    try:
        while True:
            now = time.monotonic()
            elapsed = now - started

            if timeout is not None and elapsed >= timeout:
                timed_out = True
                timeout_reason = "hard"
                break

            idle = now - last_output
            if idle_timeout is not None and idle >= idle_timeout:
                timed_out = True
                timeout_reason = "idle"
                break

            wakeup_in = 0.5
            if timeout is not None:
                wakeup_in = min(wakeup_in, timeout - elapsed)
            if idle_timeout is not None:
                wakeup_in = min(wakeup_in, idle_timeout - idle)
            if heartbeat_interval is not None:
                wakeup_in = min(wakeup_in, heartbeat_interval - (now - last_heartbeat))

            wakeup_in = max(0.01, wakeup_in)

            try:
                msg_type, msg_data = q.get(timeout=wakeup_in)
                if msg_type == "eof":
                    break
                elif msg_type == "output":
                    text = msg_data
                    now_output = time.monotonic()
                    last_output = now_output
                    if first_output_seconds is None:
                        first_output_seconds = round(now_output - started, 3)
                    last_output_seconds = round(now_output - started, 3)

                    if event_callback is not None:
                        event_callback(
                            {
                                "type": "output",
                                "elapsed_seconds": round(now_output - started, 3),
                                "text": text,
                            }
                        )

                    if output_file is not None:
                        output_file.write(text)
                        output_file.flush()

                    text_bytes = text.encode("utf-8")
                    captured_output.append(text_bytes)
                    captured_bytes += len(text_bytes)

                    while captured_bytes > max_capture_bytes and captured_output:
                        output_truncated = True
                        removed = captured_output.pop(0)
                        captured_bytes -= len(removed)
                        if (
                            captured_bytes < max_capture_bytes
                            and captured_bytes + len(removed) > max_capture_bytes
                        ):
                            remove_len = (
                                captured_bytes + len(removed)
                            ) - max_capture_bytes
                            if remove_len < len(removed):
                                suffix = removed[remove_len:]
                                captured_output.insert(0, suffix)
                                captured_bytes += len(suffix)
            except queue.Empty:
                pass

            now = time.monotonic()
            if (
                heartbeat_interval is not None
                and now - last_heartbeat >= heartbeat_interval
            ):
                last_heartbeat = now
                if event_callback is not None:
                    event_callback(
                        {
                            "type": "heartbeat",
                            "elapsed_seconds": round(now - started, 3),
                            "idle_seconds": round(now - last_output, 3),
                        }
                    )
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if output_file is not None:
            output_file.close()

    termination_description = "normal"
    if timed_out:
        if event_callback is not None:
            event_callback(
                {
                    "type": "timeout",
                    "reason": timeout_reason,
                }
            )

    if process.poll() is None:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                termination_description = "force-killed process tree"
            else:
                os.killpg(process.pid, signal.SIGTERM)
                termination_description = "terminated process tree"
        except OSError:
            pass

        try:
            process.wait(timeout=termination_grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                termination_description = "force-killed process tree"
            except OSError:
                pass
            process.wait()

    if interrupted:
        raise KeyboardInterrupt()

    if process.stdout is not None:
        try:
            process.stdout.close()
        except Exception:
            pass
    if process.stdin is not None:
        try:
            process.stdin.close()
        except Exception:
            pass

    return {
        "command": command,
        "exit_code": 124 if timed_out else process.returncode,
        "timed_out": timed_out,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output": b"".join(captured_output).decode("utf-8", errors="replace"),
        "timeout_reason": timeout_reason,
        "first_output_seconds": first_output_seconds,
        "last_output_seconds": last_output_seconds,
        "output_truncated": output_truncated,
        "termination_description": termination_description,
    }


def execute_acceptance(command: str, cwd: Path) -> dict[str, object]:
    argv = acceptance_argv(command)
    return (
        missing_acceptance_shell(command)
        if argv is None
        else execute(
            argv,
            cwd,
            env=acceptance_environment(isolated_git_environment()),
        )
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_stdout(arguments: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=isolated_git_environment(),
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout


def isolated_git_environment() -> dict[str, str]:
    """Keep candidate discovery independent from mutable user Git config."""

    environment = os.environ.copy()
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_CONFIG_SYSTEM"] = os.devnull
    return environment


def _resolved_git_path(workspace: Path, relative: str) -> Path:
    path = Path(git_stdout(["rev-parse", "--git-path", relative], workspace).strip())
    return path if path.is_absolute() else workspace / path


def _git_metadata_digest(path: Path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        return "unsafe-non-regular"
    return sha256(path)


def git_metadata_snapshot(workspace: Path) -> dict[str, str | None]:
    """Hash Git metadata that can change candidate discovery or object meaning."""

    return {
        relative: _git_metadata_digest(_resolved_git_path(workspace, relative))
        for relative in CRITICAL_GIT_METADATA
    }


def git_integrity_check(
    workspace: Path,
    expected_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """Reject Git state that can hide candidate files or rewrite diff semantics."""

    issues: dict[str, object] = {}
    index_lock = _resolved_git_path(workspace, "index.lock")
    if index_lock.exists() or index_lock.is_symlink():
        issues["index_lock"] = str(index_lock)

    flagged_paths = []
    for entry in git_stdout(["ls-files", "-v", "-z"], workspace).split("\0"):
        if not entry:
            continue
        marker, _, relative = entry.partition(" ")
        if marker == "S" or marker.islower():
            flagged_paths.append({"marker": marker, "path": relative})
    if flagged_paths:
        issues["index_flags"] = flagged_paths

    replace_refs = git_stdout(
        ["for-each-ref", "--format=%(refname)", "refs/replace"], workspace
    ).splitlines()
    if replace_refs:
        issues["replace_refs"] = replace_refs

    ignored = git_stdout(
        ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
        workspace,
    ).split("\0")
    unexpected_ignored = sorted(
        relative
        for relative in ignored
        if relative
        and not any(
            relative == prefix.removesuffix("/") or relative.startswith(prefix)
            for prefix in ALLOWED_IGNORED_PREFIXES
        )
    )
    if unexpected_ignored:
        issues["ignored_files"] = unexpected_ignored

    current_metadata = git_metadata_snapshot(workspace)
    unsafe_metadata = [
        relative
        for relative, digest in current_metadata.items()
        if digest == "unsafe-non-regular"
    ]
    if unsafe_metadata:
        issues["unsafe_metadata"] = unsafe_metadata

    if expected_metadata is not None:
        metadata_drift = {
            relative: {
                "expected": expected_metadata.get(relative),
                "actual": current_metadata.get(relative),
            }
            for relative in CRITICAL_GIT_METADATA
            if current_metadata.get(relative) != expected_metadata.get(relative)
        }
        if metadata_drift:
            issues["metadata_drift"] = metadata_drift

    return {
        "command": ["git", "candidate-integrity-check"],
        "exit_code": 1 if issues else 0,
        "output": issues if issues else "clean",
    }


def require_git_integrity(
    workspace: Path,
    expected_metadata: dict[str, object] | None = None,
) -> None:
    check = git_integrity_check(workspace, expected_metadata)
    if check["exit_code"] != 0:
        raise RuntimeError(
            "unsafe Git candidate state: " + json.dumps(check["output"], sort_keys=True)
        )


def protected_test_hashes(workspace: Path) -> dict[str, str]:
    protected: dict[str, str] = {}
    for relative in git_stdout(["ls-files"], workspace).splitlines():
        path = Path(relative)
        parts = set(path.parts)
        is_test = bool(parts & {"test", "tests", "__tests__"}) or (
            path.name.startswith("test_")
            or path.name.startswith("selftest")
            or ".test." in path.name
            or ".spec." in path.name
        )
        full_path = workspace / path
        if is_test and full_path.is_file():
            protected[relative] = sha256(full_path)
    return protected


def gate_config_hashes(workspace: Path) -> dict[str, str | None]:
    protected: dict[str, str | None] = {}
    for relative in (".sage/gates.json", ".sage-gates.json"):
        path = workspace / relative
        protected[relative] = sha256(path) if path.is_file() else None
    return protected


def policy_file_hashes(workspace: Path) -> dict[str, str | None]:
    return {
        relative: sha256(workspace / relative)
        if (workspace / relative).is_file()
        else None
        for relative in ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
    }


def capture_diff(
    workspace: Path,
    baseline_head: str,
    *,
    expected_git_metadata: dict[str, object] | None = None,
) -> str:
    # Intent-to-add makes new, non-ignored files visible in the patch without
    # staging their contents as accepted changes.
    require_git_integrity(workspace, expected_git_metadata)
    staged = git_stdout(
        [
            "diff",
            "--cached",
            "--no-renames",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            "HEAD",
        ],
        workspace,
    ).splitlines()
    if staged:
        raise RuntimeError(
            "candidate index contains staged changes; agent work must remain unstaged: "
            + ", ".join(staged)
        )
    intent_to_add = subprocess.run(
        ["git", "add", "-N", "."],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=isolated_git_environment(),
        check=False,
    )
    if intent_to_add.returncode != 0:
        detail = (intent_to_add.stderr or intent_to_add.stdout).strip()
        raise RuntimeError(f"git add -N failed: {detail or 'unknown error'}")
    patch = git_stdout(
        [
            "diff",
            "--binary",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            baseline_head,
        ],
        workspace,
    )
    require_git_integrity(workspace, expected_git_metadata)
    return patch


@contextmanager
def materialized_candidate(
    workspace: Path, baseline_head: str, patch: str
) -> Iterator[Path]:
    """Rebuild exactly the visible patch in a fresh clone for gate execution."""

    with tempfile.TemporaryDirectory(prefix="sage-gate-candidate-") as temporary:
        candidate = Path(temporary) / "repository"
        cloned = execute(
            [
                "git",
                "clone",
                "--quiet",
                "--no-local",
                "--no-checkout",
                str(workspace),
                str(candidate),
            ],
            Path(temporary),
            env=isolated_git_environment(),
        )
        if cloned["exit_code"] != 0:
            raise RuntimeError(
                f"candidate materialization clone failed: {cloned['output']}"
            )
        checked_out = execute(
            ["git", "checkout", "--quiet", "--detach", baseline_head],
            candidate,
            env=isolated_git_environment(),
        )
        if checked_out["exit_code"] != 0:
            raise RuntimeError(
                f"candidate materialization checkout failed: {checked_out['output']}"
            )
        remote_removed = execute(
            ["git", "remote", "remove", "origin"],
            candidate,
            env=isolated_git_environment(),
        )
        if remote_removed["exit_code"] != 0:
            raise RuntimeError(
                "candidate source remote cannot be removed before gate execution: "
                + str(remote_removed["output"])
            )
        if patch.strip():
            applied = subprocess.run(
                ["git", "apply", "--binary", "--whitespace=nowarn", "-"],
                cwd=candidate,
                input=patch,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=isolated_git_environment(),
                check=False,
            )
            if applied.returncode != 0:
                raise RuntimeError(
                    "candidate patch cannot be reconstructed in a clean clone: "
                    + (applied.stderr.strip() or applied.stdout.strip())
                )
        yield candidate


def candidate_symlink_boundary_check(workspace: Path) -> dict[str, object]:
    """Reject candidate symlinks that resolve outside the reconstructed root."""

    root = workspace.resolve()
    unsafe: list[dict[str, str]] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        if Path(current) == root:
            directory_names[:] = [name for name in directory_names if name != ".git"]
        for name in [*directory_names, *file_names]:
            path = Path(current) / name
            if not path.is_symlink():
                continue
            try:
                target = os.readlink(path)
                if Path(target).is_absolute():
                    reason = "absolute target"
                else:
                    resolved = path.resolve(strict=False)
                    try:
                        resolved.relative_to(root)
                        continue
                    except ValueError:
                        reason = "target escapes candidate root"
            except (OSError, RuntimeError, ValueError) as error:
                target = "<unreadable>"
                reason = f"unresolvable target: {error}"
            unsafe.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "target": target,
                    "reason": reason,
                }
            )
    return {
        "command": ["candidate-symlink-boundary-check"],
        "exit_code": 1 if unsafe else 0,
        "output": unsafe if unsafe else "all symlinks remain inside candidate root",
    }


def changed_files_from_baseline(
    workspace: Path,
    baseline_head: str,
    *,
    expected_git_metadata: dict[str, object] | None = None,
) -> list[str]:
    capture_diff(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    return git_stdout(
        [
            "diff",
            "--no-renames",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            baseline_head,
        ],
        workspace,
    ).splitlines()


def ensure_repo(path: Path) -> Path:
    result = execute(["git", "rev-parse", "--show-toplevel"], path)
    if result["exit_code"] != 0:
        raise SystemExit(f"not a git repository: {path}")
    root = Path(str(result["output"]).strip()).resolve()
    head = execute(["git", "rev-parse", "--verify", "HEAD"], root)
    if head["exit_code"] != 0:
        raise SystemExit("source repository must have at least one commit")
    return root


def prepare_clone(
    repo: Path,
    run_dir: Path,
    spec: Path,
    *,
    shared_briefing: str = "# Test briefing\n",
    stitch_design: Path | None = None,
    stitch_required: bool = False,
    expected_source_head: str | None = None,
) -> Path:
    if run_dir.exists() and (run_dir / "workspace").exists():
        raise SystemExit(f"run already contains a workspace: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace = run_dir / "workspace"
    result = execute(
        ["git", "clone", "--quiet", "--no-hardlinks", str(repo), str(workspace)],
        LAB_ROOT,
    )
    if result["exit_code"] != 0:
        raise SystemExit(str(result["output"]))
    expected_source_head = (
        expected_source_head or git_stdout(["rev-parse", "HEAD"], repo).strip()
    )
    cloned_source_head = git_stdout(["rev-parse", "HEAD"], workspace).strip()
    if cloned_source_head != expected_source_head:
        raise SystemExit(
            "source HEAD changed after preflight: "
            f"expected {expected_source_head}, cloned {cloned_source_head}"
        )
    shutil.copy2(spec, workspace / "WORKFLOW_TASK.md")
    (workspace / "SAGE_KNOWLEDGE.md").write_text(shared_briefing, encoding="utf-8")
    stitch_target = workspace / "STITCH_DESIGN.md"
    if stitch_required:
        if stitch_design is None or not stitch_design.is_file():
            raise SystemExit(
                "UI/WPF tasks require a Stitch-exported DESIGN.md before dispatch"
            )
        shutil.copy2(stitch_design, stitch_target)
    codegraph = refresh_codegraph(workspace)
    (run_dir / "codegraph.json").write_text(
        json.dumps(codegraph, indent=2) + "\n", encoding="utf-8"
    )
    if not codegraph["passed"]:
        raise SystemExit("CodeGraph initialization failed before agent dispatch")
    git_env = isolated_git_environment()
    execute(
        ["git", "config", "user.name", "Evidence Workflow"],
        workspace,
        env=git_env,
    )
    execute(
        ["git", "config", "user.email", "evidence-workflow@example.invalid"],
        workspace,
        env=git_env,
    )
    baseline_files = ["WORKFLOW_TASK.md", "SAGE_KNOWLEDGE.md"]
    if stitch_required:
        baseline_files.append("STITCH_DESIGN.md")
    execute(["git", "add", *baseline_files], workspace, env=git_env)
    committed = execute(
        ["git", "commit", "-qm", "chore: lock workflow task contract"],
        workspace,
        env=git_env,
    )
    if committed["exit_code"] != 0:
        raise SystemExit(str(committed["output"]))
    workspace_baseline_head = git_stdout(["rev-parse", "HEAD"], workspace).strip()
    git_metadata = git_metadata_snapshot(workspace)
    require_git_integrity(workspace, git_metadata)
    contract = {
        "source_repo": str(repo),
        "source_head": expected_source_head,
        "workspace_baseline_head": workspace_baseline_head,
        "task_sha256": sha256(workspace / "WORKFLOW_TASK.md"),
        "knowledge_briefing_sha256": sha256(workspace / "SAGE_KNOWLEDGE.md"),
        "stitch_required": stitch_required,
        "stitch_design_sha256": sha256(stitch_target) if stitch_required else None,
        "codegraph_required": True,
        "protected_tests": protected_test_hashes(workspace),
        "gate_configs": gate_config_hashes(workspace),
        "policy_files": policy_file_hashes(workspace),
        "git_metadata": git_metadata,
    }
    (run_dir / "contract.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )
    return workspace


def extract_agent_output(agent: str, raw_output: str) -> str:
    if not raw_output:
        return raw_output
    if agent == "agy":
        return raw_output
    if agent == "codex":
        final_text = None
        for line in raw_output.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "item.completed":
                    item = data.get("item", {})
                    if item.get("type") == "agent_message" and "text" in item:
                        final_text = item["text"]
                elif "msg" in data:
                    msg = data["msg"]
                    if (
                        isinstance(msg, dict)
                        and msg.get("type") == "agent_message"
                        and "text" in msg
                    ):
                        final_text = msg["text"]
            except Exception:
                pass
        if final_text is not None:
            return final_text
        return raw_output
    if agent == "claude":
        final_text = None
        for line in raw_output.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
                if "result" in data and isinstance(data["result"], str):
                    final_text = data["result"]
            except Exception:
                pass
        if final_text is not None:
            return final_text
        return raw_output
    return raw_output


def agent_command(agent: str, mode: str, workspace: Path) -> list[str]:
    if agent == "agy":
        return [
            "agy",
            "--print",
            "__PROMPT__",
            "--print-timeout",
            "15m",
            "--mode",
            "accept-edits" if mode == "write" else "plan",
            "--sandbox",
            "--model",
            "Gemini 3.1 Pro (High)",
            "--add-dir",
            str(workspace),
        ]
    if agent == "codex":
        return [
            "codex",
            "exec",
            "--json",
            "--ephemeral",
            "--sandbox",
            "workspace-write" if mode == "write" else "read-only",
            "--color",
            "never",
            "-C",
            str(workspace),
            "-",
        ]
    if agent == "claude":
        return [
            "claude",
            "-p",
            "--no-session-persistence",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode",
            "acceptEdits" if mode == "write" else "plan",
            "--model",
            "sonnet",
            "--effort",
            "high",
        ]
    raise ValueError(agent)


def run_agent(
    run_dir: Path,
    workspace: Path,
    stages: list[dict[str, object]],
    budget: BudgetLedger,
    label: str,
    agent: str,
    mode: str,
    prompt: str,
    *,
    baseline_head: str,
    expected_git_metadata: dict[str, object],
    idle_timeout: int = 300,
    heartbeat_interval: int = 5,
    termination_grace_seconds: int = 5,
    max_capture_bytes: int = 4194304,
) -> dict[str, object]:
    stage_dir = run_dir / "stages" / f"{len(stages) + 1:02d}-{label}"
    stage_dir.mkdir(parents=True)
    (stage_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    budget_stage, timeout = budget.reserve(label=label, agent=agent, prompt=prompt)
    command = agent_command(agent, mode, workspace)

    events_file = stage_dir / "events.jsonl"
    events_fd = open(events_file, "a", encoding="utf-8")
    raw_output_file = stage_dir / "raw-output.txt"

    def event_callback(event: dict[str, object]) -> None:
        events_fd.write(json.dumps(event) + "\n")
        events_fd.flush()

        sys.stdout.write(f"\r\033[Kstage={label} agent={agent}")
        if event["type"] == "heartbeat":
            sys.stdout.write(
                f" elapsed={event.get('elapsed_seconds', 0):.1f}s idle={event.get('idle_seconds', 0):.1f}s [running]"
            )
        elif event["type"] == "timeout":
            sys.stdout.write(f" timeout={event.get('reason')}")
        elif event["type"] == "output":
            sys.stdout.write(
                f" elapsed={event.get('elapsed_seconds', 0):.1f}s [output]"
            )
        sys.stdout.flush()

    result: dict[str, object] = {
        "exit_code": 1,
        "duration_seconds": 0,
        "output": "stage execution did not start",
    }
    try:
        if agent == "agy":
            command = [prompt if part == "__PROMPT__" else part for part in command]
            result = execute(
                command,
                workspace,
                timeout=timeout,
                idle_timeout=idle_timeout,
                heartbeat_interval=heartbeat_interval,
                termination_grace_seconds=termination_grace_seconds,
                event_callback=event_callback,
                output_path=raw_output_file,
                max_capture_bytes=max_capture_bytes,
            )
        elif agent == "codex":
            result = execute(
                command,
                workspace,
                input_text=prompt,
                timeout=timeout,
                idle_timeout=idle_timeout,
                heartbeat_interval=heartbeat_interval,
                termination_grace_seconds=termination_grace_seconds,
                event_callback=event_callback,
                output_path=raw_output_file,
                max_capture_bytes=max_capture_bytes,
            )
        else:
            result = execute(
                [*command, prompt],
                workspace,
                timeout=timeout,
                idle_timeout=idle_timeout,
                heartbeat_interval=heartbeat_interval,
                termination_grace_seconds=termination_grace_seconds,
                event_callback=event_callback,
                output_path=raw_output_file,
                max_capture_bytes=max_capture_bytes,
            )
    finally:
        events_fd.close()
        sys.stdout.write(
            f"\r\033[Kstage={label} agent={agent} exit={result.get('exit_code', 'unknown')} seconds={result.get('duration_seconds', 'unknown')}\n"
        )
        sys.stdout.flush()

    extracted_output = extract_agent_output(agent, str(result.get("output", "")))
    (stage_dir / "output.txt").write_text(extracted_output, encoding="utf-8")
    candidate_error = None
    try:
        candidate_patch = capture_diff(
            workspace,
            baseline_head,
            expected_git_metadata=expected_git_metadata,
        )
    except RuntimeError as error:
        candidate_patch = ""
        candidate_error = str(error)
    (stage_dir / "workspace.diff").write_text(candidate_patch, encoding="utf-8")
    workspace_head = git_stdout(["rev-parse", "HEAD"], workspace).strip()

    public = {
        "label": label,
        "agent": agent,
        "mode": mode,
        "exit_code": result.get("exit_code"),
        "duration_seconds": result.get("duration_seconds"),
        "output_file": str(stage_dir / "output.txt"),
        "timed_out": result.get("timed_out", False),
        "timeout_reason": result.get("timeout_reason"),
        "first_output_seconds": result.get("first_output_seconds"),
        "last_output_seconds": result.get("last_output_seconds"),
        "output_truncated": result.get("output_truncated", False),
        "raw_output_file": str(raw_output_file),
        "event_file": str(events_file),
        "workspace_head": workspace_head,
        "workspace_head_locked": workspace_head == baseline_head,
        "git_candidate_integrity": {
            "exit_code": 1 if candidate_error else 0,
            "output": candidate_error or "clean",
        },
    }
    stages.append(public)
    budget.settle(
        budget_stage,
        output=extracted_output,
        exit_code=int(result.get("exit_code", 1)),
    )
    exit_code = int(result.get("exit_code", 1))
    if exit_code != 0 or workspace_head != baseline_head or candidate_error:
        checks = {
            "mandatory_agent_stages": {
                "exit_code": 0 if exit_code == 0 else 1,
                "output": f"{label}: exit {exit_code}",
            },
            "workspace_head_locked": {
                "exit_code": 0 if workspace_head == baseline_head else 1,
                "output": {"expected": baseline_head, "actual": workspace_head},
            },
            "git_candidate_integrity": {
                "exit_code": 1 if candidate_error else 0,
                "output": candidate_error or "clean",
            },
        }
        reason = (
            f"mandatory stage {label!r} exited {exit_code}"
            if exit_code != 0
            else (
                f"mandatory stage {label!r} moved workspace HEAD"
                if workspace_head != baseline_head
                else f"mandatory stage {label!r} left unsafe Git candidate state"
            )
        )
        raise StageExecutionError(
            reason,
            checks=checks,
            stages=list(stages),
            changed_files=(
                []
                if candidate_error
                else changed_files_from_baseline(
                    workspace,
                    baseline_head,
                    expected_git_metadata=expected_git_metadata,
                )
            ),
        )
    return {**public, "output": extracted_output}


def project_quality_commands(
    workspace: Path, baseline_head: str = "HEAD"
) -> list[tuple[str, list[str]]]:
    changed = git_stdout(
        [
            "diff",
            "--no-renames",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            baseline_head,
        ],
        workspace,
    ).splitlines()
    return select_plugin_commands(workspace, changed)


def normalize_changed_files(
    workspace: Path,
    baseline_head: str,
    *,
    expected_git_metadata: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    capture_diff(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    changed = git_stdout(
        [
            "diff",
            "--no-renames",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            baseline_head,
        ],
        workspace,
    ).splitlines()
    results: list[dict[str, object]] = []
    pyproject = workspace / "pyproject.toml"
    python_files = [path for path in changed if path.endswith(".py")]
    if (
        python_files
        and pyproject.exists()
        and "ruff" in pyproject.read_text(encoding="utf-8")
    ):
        results.append(execute(["ruff", "format", *python_files], workspace))
    biome_config = next(iter(workspace.glob("biome.json*")), None)
    web_files = [
        path
        for path in changed
        if Path(path).suffix in {".js", ".jsx", ".ts", ".tsx", ".json", ".css"}
        and path != "WORKFLOW_TASK.md"
    ]
    if web_files and biome_config is not None:
        results.append(execute(["biome", "format", "--write", *web_files], workspace))
    return results


def run_gates(
    workspace: Path,
    contract: dict[str, object],
    acceptance: list[str],
    allowed_new: list[str],
    allowed_test_changes: list[str],
    allowed_changes: list[str],
    *,
    stages: list[dict[str, object]] | None = None,
    require_nonempty_candidate: bool = False,
    _materialized_source: Path | None = None,
    _source_patch: str | None = None,
) -> dict[str, object]:
    baseline_head = str(contract["workspace_baseline_head"])
    if _materialized_source is None:
        expected_source_metadata = dict(contract.get("git_metadata", {}))
        source_integrity = git_integrity_check(workspace, expected_source_metadata)
        if source_integrity["exit_code"] != 0:
            return {
                "passed": False,
                "checks": {"git_candidate_integrity": source_integrity},
            }
        source_head = git_stdout(["rev-parse", "HEAD"], workspace).strip()
        if source_head != baseline_head:
            return {
                "passed": False,
                "checks": {
                    "git_candidate_integrity": source_integrity,
                    "workspace_head_locked": {
                        "command": ["git", "rev-parse", "HEAD"],
                        "exit_code": 1,
                        "output": {
                            "expected": baseline_head,
                            "actual": source_head,
                        },
                    },
                },
            }
        try:
            source_patch = capture_diff(
                workspace,
                baseline_head,
                expected_git_metadata=expected_source_metadata,
            )
            with materialized_candidate(
                workspace, baseline_head, source_patch
            ) as candidate:
                result = run_gates(
                    candidate,
                    contract,
                    acceptance,
                    allowed_new,
                    allowed_test_changes,
                    allowed_changes,
                    stages=stages,
                    require_nonempty_candidate=require_nonempty_candidate,
                    _materialized_source=workspace,
                    _source_patch=source_patch,
                )
        except RuntimeError as error:
            return {
                "passed": False,
                "checks": {
                    "candidate_materialization": {
                        "command": ["git", "clone", "+", "git", "apply"],
                        "exit_code": 1,
                        "output": str(error),
                    }
                },
            }
        final_source_integrity = git_integrity_check(
            workspace, expected_source_metadata
        )
        final_source_patch = (
            capture_diff(
                workspace,
                baseline_head,
                expected_git_metadata=expected_source_metadata,
            )
            if final_source_integrity["exit_code"] == 0
            else ""
        )
        result["checks"]["source_workspace_immutability"] = {
            "command": ["git", "diff", "--binary", baseline_head],
            "exit_code": 0
            if final_source_integrity["exit_code"] == 0
            and final_source_patch == source_patch
            else 1,
            "output": "unchanged"
            if final_source_integrity["exit_code"] == 0
            and final_source_patch == source_patch
            else {
                "git_integrity": final_source_integrity["output"],
                "patch_unchanged": final_source_patch == source_patch,
            },
        }
        result["passed"] = all(
            check.get("exit_code") == 0 for check in result["checks"].values()
        )
        return result

    checks: dict[str, dict[str, object]] = {}
    checks["candidate_symlink_boundary"] = candidate_symlink_boundary_check(workspace)
    if checks["candidate_symlink_boundary"]["exit_code"] != 0:
        return {"passed": False, "checks": checks}
    codegraph = refresh_codegraph(workspace)
    expected_git_metadata = git_metadata_snapshot(workspace)
    checks["codegraph_current"] = {
        "command": ["codegraph", codegraph["action"], str(workspace)],
        "exit_code": 0 if codegraph["passed"] else 1,
        "output": {
            "action": codegraph["action"],
            "refresh_exit_code": codegraph["refresh"]["exit_code"],
            "status_exit_code": (
                codegraph["status"]["exit_code"] if codegraph["status"] else None
            ),
            "files": codegraph["files"],
            "nodes": codegraph["nodes"],
            "edges": codegraph["edges"],
        },
    }
    integrity = git_integrity_check(workspace, expected_git_metadata)
    checks["git_candidate_integrity"] = integrity
    if integrity["exit_code"] != 0:
        return {"passed": False, "checks": checks}
    gated_patch = capture_diff(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    if _source_patch is None or gated_patch != _source_patch:
        checks["candidate_materialization"] = {
            "command": ["git", "apply", "--binary"],
            "exit_code": 1,
            "output": "materialized candidate does not match source patch",
        }
        return {"passed": False, "checks": checks}
    checks["candidate_materialization"] = {
        "command": ["git", "apply", "--binary"],
        "exit_code": 0,
        "output": "clean-clone reconstruction matched source patch",
    }
    quality_commands = project_quality_commands(workspace, baseline_head)
    workspace_head = git_stdout(["rev-parse", "HEAD"], workspace).strip()
    checks["workspace_head_locked"] = {
        "exit_code": 0 if workspace_head == baseline_head else 1,
        "output": {"expected": baseline_head, "actual": workspace_head},
    }
    if stages is not None:
        failed_stages = [
            str(stage.get("label") or stage.get("agent") or "unknown")
            for stage in stages
            if stage.get("exit_code") != 0
        ]
        checks["mandatory_agent_stages"] = {
            "exit_code": 0 if stages and not failed_stages else 1,
            "output": failed_stages if failed_stages else f"{len(stages)} passed",
        }
    candidate_files = changed_files_from_baseline(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    if require_nonempty_candidate:
        candidate_ready = bool(gated_patch.strip()) and bool(candidate_files)
        checks["candidate_nonempty"] = {
            "exit_code": 0 if candidate_ready else 1,
            "output": candidate_files if candidate_ready else "empty candidate patch",
        }
    task_path = workspace / "WORKFLOW_TASK.md"
    task_ok = task_path.exists() and sha256(task_path) == contract["task_sha256"]
    checks["task_contract"] = {"exit_code": 0 if task_ok else 1, "output": "sha256"}
    briefing_path = workspace / "SAGE_KNOWLEDGE.md"
    briefing_ok = briefing_path.is_file() and sha256(briefing_path) == contract.get(
        "knowledge_briefing_sha256"
    )
    checks["shared_knowledge_contract"] = {
        "exit_code": 0 if briefing_ok else 1,
        "output": "sha256",
    }
    stitch_path = workspace / "STITCH_DESIGN.md"
    stitch_required = bool(contract.get("stitch_required"))
    stitch_ok = not stitch_required or (
        stitch_path.is_file()
        and sha256(stitch_path) == contract.get("stitch_design_sha256")
    )
    checks["stitch_design_contract"] = {
        "exit_code": 0 if stitch_ok else 1,
        "output": "not-required"
        if not stitch_required
        else "locked Stitch DESIGN.md sha256",
    }
    changed_tests = []
    for relative, expected_hash in dict(contract["protected_tests"]).items():
        path = workspace / relative
        allowed = any(
            fnmatch.fnmatch(relative, pattern) for pattern in allowed_test_changes
        )
        if not allowed and (not path.is_file() or sha256(path) != expected_hash):
            changed_tests.append(relative)
    checks["protected_tests"] = {
        "exit_code": 1 if changed_tests else 0,
        "output": changed_tests,
    }
    changed_gate_configs = []
    for relative, expected_hash in dict(contract.get("gate_configs", {})).items():
        path = workspace / relative
        actual_hash = sha256(path) if path.is_file() else None
        if actual_hash != expected_hash:
            changed_gate_configs.append(relative)
    checks["protected_gate_configs"] = {
        "exit_code": 1 if changed_gate_configs else 0,
        "output": changed_gate_configs,
    }
    changed_policy_files = []
    for relative, expected_hash in dict(contract.get("policy_files", {})).items():
        path = workspace / relative
        actual_hash = sha256(path) if path.is_file() else None
        if actual_hash != expected_hash:
            changed_policy_files.append(relative)
    checks["protected_agent_policy"] = {
        "exit_code": 1 if changed_policy_files else 0,
        "output": changed_policy_files,
    }
    capture_diff(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    added_files = git_stdout(
        ["diff", "--no-renames", "--name-only", "--diff-filter=A", baseline_head],
        workspace,
    ).splitlines()
    unexpected_files = [
        path
        for path in added_files
        if not any(fnmatch.fnmatch(path, pattern) for pattern in allowed_new)
    ]
    checks["new_file_allowlist"] = {
        "exit_code": 1 if unexpected_files else 0,
        "output": unexpected_files,
    }
    changed_files = changed_files_from_baseline(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    existing_changes = [path for path in changed_files if path not in added_files]
    unexpected_changes = (
        [
            path
            for path in existing_changes
            if not any(fnmatch.fnmatch(path, pattern) for pattern in allowed_changes)
        ]
        if allowed_changes
        else []
    )
    checks["changed_file_allowlist"] = {
        "exit_code": 1 if unexpected_changes else 0,
        "output": unexpected_changes,
    }
    for index, command in enumerate(acceptance, start=1):
        boundary = candidate_symlink_boundary_check(workspace)
        checks[f"acceptance_{index}"] = (
            execute_acceptance(command, workspace)
            if boundary["exit_code"] == 0
            else {
                "command": ["candidate-symlink-boundary-check"],
                "exit_code": 1,
                "output": boundary["output"],
            }
        )
    for name, command in quality_commands:
        checks[name] = execute(
            command,
            workspace,
            env=acceptance_environment(isolated_git_environment()),
        )
    post_integrity = git_integrity_check(workspace, expected_git_metadata)
    checks["gate_git_integrity"] = post_integrity
    checks["candidate_symlink_boundary_post"] = candidate_symlink_boundary_check(
        workspace
    )
    post_gate_patch = (
        capture_diff(
            workspace,
            baseline_head,
            expected_git_metadata=expected_git_metadata,
        )
        if post_integrity["exit_code"] == 0
        else ""
    )
    checks["gate_workspace_immutability"] = {
        "exit_code": 0 if post_gate_patch == gated_patch else 1,
        "output": "unchanged"
        if post_gate_patch == gated_patch
        else "workspace changed",
    }
    passed = all(check["exit_code"] == 0 for check in checks.values())
    if not passed and os.environ.get("SAGE_GATE_DIAGNOSTICS") == "1":
        failures = {
            name: {
                "exit_code": check["exit_code"],
                "timed_out": bool(check.get("timed_out", False)),
            }
            for name, check in checks.items()
            if check["exit_code"] != 0
        }
        print(
            "SAGE_GATE_FAILURES=" + json.dumps(failures, sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
    return {"passed": passed, "checks": checks}


def prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def shared_prompt(content: str) -> str:
    return (
        "MANDATORY PREFLIGHT: read WORKFLOW_TASK.md and SAGE_KNOWLEDGE.md first. "
        "Use CodeGraph before grep/find for code understanding. Never edit either file. "
        "For Web UI, website UI, desktop visual UI, or WPF/XAML design, Stitch is mandatory: "
        "read the locked STITCH_DESIGN.md and stop if it is absent.\n\n" + content
    )


def main() -> None:
    global ACTIVE_MEMORY_SESSION
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--route", choices=("fast", "standard", "high"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--cost-budget-usd", type=float)
    parser.add_argument("--total-timeout", type=int)
    parser.add_argument("--knowledge-vault", type=Path, default=DEFAULT_KNOWLEDGE_VAULT)
    parser.add_argument("--project-id")
    parser.add_argument("--stitch-design", type=Path)
    parser.add_argument(
        "--signing-key",
        type=Path,
        default=(
            Path(os.environ["SAGE_EVIDENCE_SIGNING_KEY"])
            if os.environ.get("SAGE_EVIDENCE_SIGNING_KEY")
            else None
        ),
    )
    parser.add_argument("--signer-identity", default="sage-local")
    parser.add_argument(
        "--allow-new",
        action="append",
        default=[],
        help="Glob for files the task may add; default rejects every new file",
    )
    parser.add_argument(
        "--allow-change",
        action="append",
        default=[],
        help="Glob for existing files the task may modify; omitted means unrestricted",
    )
    parser.add_argument(
        "--allow-test-change",
        action="append",
        default=[],
        help="Glob for existing test files the contract explicitly permits changing",
    )
    parser.add_argument("--idle-timeout", type=int)
    parser.add_argument("--heartbeat-interval", type=int)
    args = parser.parse_args()

    if not args.acceptance:
        parser.error("at least one --acceptance command is required")
    if args.signing_key is None:
        parser.error(
            "--signing-key or SAGE_EVIDENCE_SIGNING_KEY is required for signed evidence"
        )

    repo = ensure_repo(args.repo.resolve())
    spec = args.spec.resolve()
    if not spec.is_file():
        raise SystemExit(f"missing spec: {spec}")
    run_dir = args.run_dir.resolve() if args.run_dir else RUNS / args.name
    if run_dir.exists():
        raise SystemExit(f"run already exists: {run_dir}")
    workflow_config = json.loads(CONFIG.read_text(encoding="utf-8"))
    source_head = git_stdout(["rev-parse", "HEAD"], repo).strip()
    vault = KnowledgeVault(args.knowledge_vault)
    preflight = vault.prepare_task(
        repo=repo,
        route=args.route,
        task_name=args.name,
        spec=spec,
        acceptance=args.acceptance,
        source_head=source_head,
        project_id=args.project_id,
        signing_key=args.signing_key,
        stitch_design=args.stitch_design,
    )
    run_dir.mkdir(parents=True)
    (run_dir / "preflight.json").write_text(
        json.dumps(
            {key: value for key, value in preflight.items() if key != "briefing"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    memory_session = vault.session(preflight, run_dir)
    ACTIVE_MEMORY_SESSION = memory_session
    if not preflight["ready"]:
        checks = {
            f"capability_{name}": {
                "exit_code": 0 if detail["available"] else detail["exit_code"],
                "output": detail.get("version") or "missing",
            }
            for name, detail in preflight["capability"]["tools"].items()
        }
        if preflight["missing_knowledge"]:
            checks["relevant_knowledge"] = {
                "exit_code": 1,
                "output": preflight["missing_knowledge"],
            }
        memory = memory_session.complete(
            passed=False,
            checks=checks,
            stages=[],
            changed_files=[],
            source_head=source_head,
        )
        (run_dir / "preflight-failure.json").write_text(
            json.dumps({"checks": checks, "knowledge": memory}, indent=2) + "\n",
            encoding="utf-8",
        )
        raise SystemExit("capability or knowledge preflight failed before dispatch")

    workspace = prepare_clone(
        repo,
        run_dir,
        spec,
        shared_briefing=preflight["briefing"],
        stitch_design=Path(preflight["stitch"]["design_path"])
        if preflight["stitch"].get("design_path")
        else None,
        stitch_required=bool(preflight["stitch"]["required"]),
        expected_source_head=source_head,
    )
    codegraph = json.loads((run_dir / "codegraph.json").read_text(encoding="utf-8"))
    vault.record_dispatch(preflight, run_dir=run_dir, codegraph=codegraph)
    limits = BudgetLimits.from_config(
        workflow_config,
        max_turns=args.max_turns,
        token_budget=args.token_budget,
        cost_budget_usd=args.cost_budget_usd,
        total_timeout_seconds=args.total_timeout,
    )
    budget = BudgetLedger(limits, run_dir / "budget.json")
    contract = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
    baseline_head = str(contract["workspace_baseline_head"])
    expected_git_metadata = dict(contract["git_metadata"])
    stages: list[dict[str, object]] = []

    idle_timeout = args.idle_timeout or workflow_config.get("budget", {}).get(
        "stage_idle_timeout_seconds", 300
    )
    heartbeat_interval = args.heartbeat_interval or workflow_config.get(
        "budget", {}
    ).get("heartbeat_interval_seconds", 5)
    termination_grace = workflow_config.get("budget", {}).get(
        "termination_grace_seconds", 5
    )
    max_capture_bytes = workflow_config.get("budget", {}).get(
        "max_capture_bytes", 4194304
    )

    def do_run_agent(label, agent, mode, prompt):
        return run_agent(
            run_dir,
            workspace,
            stages,
            budget,
            label,
            agent,
            mode,
            prompt,
            baseline_head=baseline_head,
            expected_git_metadata=expected_git_metadata,
            idle_timeout=idle_timeout,
            heartbeat_interval=heartbeat_interval,
            termination_grace_seconds=termination_grace,
            max_capture_bytes=max_capture_bytes,
        )

    if args.route == "fast":
        do_run_agent("implement", "agy", "write", shared_prompt(prompt("implement.md")))
    elif args.route == "standard":
        do_run_agent(
            "implement", "claude", "write", shared_prompt(prompt("implement.md"))
        )
    else:
        plan = do_run_agent("plan", "agy", "read", shared_prompt(prompt("plan.md")))
        implementation_prompt = shared_prompt(
            prompt("implement.md") + "\n\nIndependent plan:\n" + str(plan["output"])
        )
        do_run_agent("implement", "codex", "write", implementation_prompt)
        interim_normalization = normalize_changed_files(
            workspace,
            baseline_head,
            expected_git_metadata=expected_git_metadata,
        )
        (run_dir / "interim-normalization.json").write_text(
            json.dumps(interim_normalization, indent=2) + "\n", encoding="utf-8"
        )
        interim = run_gates(
            workspace,
            contract,
            args.acceptance,
            args.allow_new,
            args.allow_test_change,
            args.allow_change,
            stages=stages,
            require_nonempty_candidate=True,
        )
        (run_dir / "interim-gates.json").write_text(
            json.dumps(interim, indent=2) + "\n", encoding="utf-8"
        )
        audit = do_run_agent(
            "audit", "claude", "read", shared_prompt(prompt("review.md"))
        )
        if not (interim["passed"] and "DECISION: PASS" in str(audit["output"])):
            correction_prompt = shared_prompt(
                prompt("correct.md") + "\n\nReviewer report:\n" + str(audit["output"])
            )
            do_run_agent("correct", "codex", "write", correction_prompt)

    if args.route in {"fast", "standard"}:
        interim_normalization = normalize_changed_files(
            workspace,
            baseline_head,
            expected_git_metadata=expected_git_metadata,
        )
        (run_dir / "interim-normalization.json").write_text(
            json.dumps(interim_normalization, indent=2) + "\n", encoding="utf-8"
        )
        interim = run_gates(
            workspace,
            contract,
            args.acceptance,
            args.allow_new,
            args.allow_test_change,
            args.allow_change,
            stages=stages,
            require_nonempty_candidate=True,
        )
        (run_dir / "interim-gates.json").write_text(
            json.dumps(interim, indent=2) + "\n", encoding="utf-8"
        )
        if not interim["passed"]:
            correction_prompt = shared_prompt(
                prompt("correct.md")
                + "\n\nMechanical gate report:\n"
                + json.dumps(interim, indent=2)
            )
            do_run_agent(
                "correct",
                "agy" if args.route == "fast" else "claude",
                "write",
                correction_prompt,
            )

    final_normalization = normalize_changed_files(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    (run_dir / "final-normalization.json").write_text(
        json.dumps(final_normalization, indent=2) + "\n", encoding="utf-8"
    )
    final = run_gates(
        workspace,
        contract,
        args.acceptance,
        args.allow_new,
        args.allow_test_change,
        args.allow_change,
        stages=stages,
        require_nonempty_candidate=True,
    )
    final_patch = run_dir / "final.patch"
    final_patch.write_text(
        capture_diff(
            workspace,
            baseline_head,
            expected_git_metadata=expected_git_metadata,
        ),
        encoding="utf-8",
    )
    changed_files = changed_files_from_baseline(
        workspace,
        baseline_head,
        expected_git_metadata=expected_git_metadata,
    )
    knowledge = memory_session.complete(
        passed=final["passed"],
        checks=final["checks"],
        stages=stages,
        changed_files=changed_files,
        source_head=source_head,
    )
    knowledge_persisted = bool(knowledge["version_bumped"]) if final["passed"] else True
    final["checks"]["knowledge_persistence"] = {
        "exit_code": 0 if knowledge_persisted else 1,
        "output": {
            "version": knowledge["version"],
            "version_bumped": knowledge["version_bumped"],
            "memory_distilled": knowledge["memory_distilled"],
        },
    }
    final["passed"] = bool(final["passed"] and knowledge_persisted)
    result = {
        "schema_version": 1,
        "execution_kind": "agent_workflow",
        "route": args.route,
        "name": args.name,
        "automated_gates_passed": final["passed"],
        "r5_human_verification": "pending",
        "merge_authorized": False,
        "runtime_boundary": dict(GATE_RUNTIME_BOUNDARY),
        # Compatibility alias. This means automated gates only; it is never R5.
        "passed": final["passed"],
        "stages": stages,
        "budget": budget.public_state(),
        "knowledge": knowledge,
        "final_gates": final,
        "contract": contract,
        "promotion_manifest": {
            "final_patch_sha256": sha256(final_patch),
            "changed_files": changed_files,
            "acceptance_commands": args.acceptance,
        },
    }
    (run_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    evidence = (
        write_signed_manifest(
            run_dir,
            signing_key=args.signing_key,
            signer_identity=args.signer_identity,
        )
        if result["passed"]
        else None
    )
    print(
        json.dumps(
            {
                "automated_gates_passed": result["automated_gates_passed"],
                "r5_human_verification": "pending",
                "evidence": evidence,
                "run_dir": str(run_dir),
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        if ACTIVE_MEMORY_SESSION is not None and not ACTIVE_MEMORY_SESSION.finalized:
            try:
                failure_memory = ACTIVE_MEMORY_SESSION.fail(
                    error,
                    checks=error.checks
                    if isinstance(error, StageExecutionError)
                    else None,
                    stages=error.stages
                    if isinstance(error, StageExecutionError)
                    else None,
                    changed_files=error.changed_files
                    if isinstance(error, StageExecutionError)
                    else None,
                )
                (ACTIVE_MEMORY_SESSION.run_dir / "failure-memory.json").write_text(
                    json.dumps(failure_memory, indent=2) + "\n", encoding="utf-8"
                )
            except Exception as memory_error:
                print(
                    f"knowledge finalization also failed: {memory_error}",
                    file=sys.stderr,
                )
        raise
