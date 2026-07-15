"""Single-source SAGE task configuration for execution and promotion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TaskConfigError(ValueError):
    """The unified task configuration violates SAGE invariants."""


def _resolve_path(base: Path, value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return str(path.resolve())


def load_task_config(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise TaskConfigError(f"invalid JSON: {path}") from error
    if not isinstance(config, dict):
        raise TaskConfigError("task config root must be an object")
    if config.get("version") != 2:
        raise TaskConfigError("task config version must be 2")
    execution = config.get("execution")
    scope = config.get("scope", {})
    budget = config.get("budget")
    evidence = config.get("evidence")
    knowledge = config.get("knowledge")
    promotion = config.get("promotion")
    if (
        not isinstance(execution, dict)
        or not isinstance(scope, dict)
        or not isinstance(budget, dict)
    ):
        raise TaskConfigError("execution, scope, and budget objects are required")
    if (
        not isinstance(evidence, dict)
        or not isinstance(knowledge, dict)
        or not isinstance(promotion, dict)
    ):
        raise TaskConfigError("evidence, knowledge, and promotion objects are required")
    required_execution = {"repo", "route", "name", "run_dir", "spec", "acceptance"}
    if not required_execution.issubset(execution):
        raise TaskConfigError("execution is missing required fields")
    for field in ("repo", "name", "run_dir", "spec"):
        if not isinstance(execution[field], str) or not execution[field]:
            raise TaskConfigError(f"execution.{field} must be non-empty text")
    if not isinstance(execution["route"], str) or execution["route"] not in {
        "fast",
        "standard",
        "high",
    }:
        raise TaskConfigError("execution.route must be fast, standard, or high")
    if (
        not isinstance(execution["acceptance"], list)
        or not execution["acceptance"]
        or not all(
            isinstance(command, str) and command for command in execution["acceptance"]
        )
    ):
        raise TaskConfigError("at least one acceptance command is required")
    for field in ("max_turns", "token_budget", "total_timeout_seconds"):
        if (
            isinstance(budget.get(field), bool)
            or not isinstance(budget.get(field), int)
            or budget[field] < 1
        ):
            raise TaskConfigError(f"budget.{field} must be a positive integer")
    for field in ("stage_idle_timeout_seconds", "heartbeat_interval_seconds"):
        if field in budget:
            if (
                isinstance(budget[field], bool)
                or not isinstance(budget[field], int)
                or budget[field] < 1
            ):
                raise TaskConfigError(
                    f"budget.{field} must be a positive integer when present"
                )
    if (
        isinstance(budget.get("cost_budget_usd"), bool)
        or not isinstance(budget.get("cost_budget_usd"), (int, float))
        or budget["cost_budget_usd"] <= 0
    ):
        raise TaskConfigError("budget.cost_budget_usd must be positive")
    required_evidence = {"signing_key", "signer_identity", "allowed_signers"}
    if not required_evidence.issubset(evidence) or not all(
        isinstance(evidence[field], str) and evidence[field]
        for field in required_evidence
    ):
        raise TaskConfigError("evidence signing fields must be non-empty text")
    if not isinstance(knowledge.get("vault"), str) or not knowledge["vault"]:
        raise TaskConfigError("knowledge.vault must be non-empty text")
    if knowledge.get("require_codegraph") is not True:
        raise TaskConfigError("knowledge.require_codegraph must be true")
    if knowledge.get("require_version_record") is not True:
        raise TaskConfigError("knowledge.require_version_record must be true")
    if knowledge.get("shared_read_only") is not True:
        raise TaskConfigError("knowledge.shared_read_only must be true")
    if knowledge.get("require_stitch_for_ui") is not True:
        raise TaskConfigError("knowledge.require_stitch_for_ui must be true")
    if knowledge.get("stitch_design") is not None and (
        not isinstance(knowledge["stitch_design"], str)
        or not knowledge["stitch_design"]
    ):
        raise TaskConfigError(
            "knowledge.stitch_design must be non-empty text when present"
        )
    if knowledge.get("project_id") is not None and (
        not isinstance(knowledge["project_id"], str) or not knowledge["project_id"]
    ):
        raise TaskConfigError(
            "knowledge.project_id must be non-empty text when present"
        )
    if not isinstance(promotion.get("branch"), str) or not promotion["branch"]:
        raise TaskConfigError("promotion.branch must be non-empty text")
    if promotion.get("base") is not None and (
        not isinstance(promotion["base"], str) or not promotion["base"]
    ):
        raise TaskConfigError("promotion.base must be non-empty text when present")
    for field, default in (
        ("wait_timeout_seconds", 1800),
        ("poll_interval_seconds", 10),
    ):
        value = promotion.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise TaskConfigError(f"promotion.{field} must be a positive integer")
    if promotion.get("draft_only") is not True:
        raise TaskConfigError("promotion.draft_only must be true")
    if promotion.get("automatic_merge") is not False:
        raise TaskConfigError("promotion.automatic_merge must be false")
    if promotion.get("r5_human_verification") != "pending":
        raise TaskConfigError("promotion must leave R5 human verification pending")
    if promotion.get("merge_authorized") is not False:
        raise TaskConfigError("agent-produced task config must not authorize merge")
    for key in ("allow_new", "allow_change", "allow_test_change"):
        values = scope.get(key, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise TaskConfigError(f"scope.{key} must be an array")
    base = path.parent
    config["_config_path"] = str(path)
    config["_resolved"] = {
        "repo": _resolve_path(base, execution["repo"]),
        "spec": _resolve_path(base, execution["spec"]),
        "run_dir": _resolve_path(base, execution["run_dir"]),
        "signing_key": _resolve_path(base, evidence["signing_key"]),
        "allowed_signers": _resolve_path(base, evidence["allowed_signers"]),
        "knowledge_vault": _resolve_path(base, knowledge["vault"]),
    }
    if knowledge.get("stitch_design"):
        config["_resolved"]["stitch_design"] = _resolve_path(
            base, knowledge["stitch_design"]
        )
    return config


def run_argv(config: dict[str, Any], *, runner: Path) -> list[str]:
    execution = config["execution"]
    scope = config.get("scope", {})
    budget = config["budget"]
    evidence = config["evidence"]
    knowledge = config["knowledge"]
    resolved = config["_resolved"]
    command = [
        "python3",
        str(runner),
        "--repo",
        resolved["repo"],
        "--route",
        execution["route"],
        "--name",
        execution["name"],
        "--run-dir",
        resolved["run_dir"],
        "--spec",
        resolved["spec"],
        "--max-turns",
        str(budget["max_turns"]),
        "--token-budget",
        str(budget["token_budget"]),
        "--cost-budget-usd",
        str(budget["cost_budget_usd"]),
        "--total-timeout",
        str(budget["total_timeout_seconds"]),
    ]
    if "stage_idle_timeout_seconds" in budget:
        command.extend(["--idle-timeout", str(budget["stage_idle_timeout_seconds"])])
    if "heartbeat_interval_seconds" in budget:
        command.extend(
            ["--heartbeat-interval", str(budget["heartbeat_interval_seconds"])]
        )
    command.extend(
        [
            "--signing-key",
            resolved["signing_key"],
            "--signer-identity",
            evidence["signer_identity"],
            "--knowledge-vault",
            resolved["knowledge_vault"],
        ]
    )
    if knowledge.get("project_id"):
        command.extend(["--project-id", knowledge["project_id"]])
    if resolved.get("stitch_design"):
        command.extend(["--stitch-design", resolved["stitch_design"]])
    for acceptance in execution["acceptance"]:
        command.extend(["--acceptance", acceptance])
    for config_key, flag in (
        ("allow_new", "--allow-new"),
        ("allow_change", "--allow-change"),
        ("allow_test_change", "--allow-test-change"),
    ):
        for pattern in scope.get(config_key, []):
            command.extend([flag, pattern])
    return command


def preflight_argv(config: dict[str, Any], *, preflight: Path) -> list[str]:
    execution = config["execution"]
    knowledge = config["knowledge"]
    resolved = config["_resolved"]
    command = [
        "python3",
        str(preflight),
        "--repo",
        resolved["repo"],
        "--route",
        execution["route"],
        "--name",
        execution["name"],
        "--spec",
        resolved["spec"],
        "--knowledge-vault",
        resolved["knowledge_vault"],
    ]
    if knowledge.get("project_id"):
        command.extend(["--project-id", knowledge["project_id"]])
    if resolved.get("stitch_design"):
        command.extend(["--stitch-design", resolved["stitch_design"]])
    for acceptance in execution["acceptance"]:
        command.extend(["--acceptance", acceptance])
    return command


def promote_argv(
    config: dict[str, Any], *, promoter: Path, resume: bool = False
) -> list[str]:
    promotion = config["promotion"]
    resolved = config["_resolved"]
    command = [
        "python3",
        str(promoter),
        "--run",
        resolved["run_dir"],
        "--repo",
        resolved["repo"],
        "--branch",
        promotion["branch"],
        "--allowed-signers",
        resolved["allowed_signers"],
        "--wait-timeout",
        str(promotion.get("wait_timeout_seconds", 1800)),
        "--poll-interval",
        str(promotion.get("poll_interval_seconds", 10)),
    ]
    if promotion.get("base"):
        command.extend(["--base", promotion["base"]])
    if resume:
        command.append("--resume")
    return command
