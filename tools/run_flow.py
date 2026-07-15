#!/usr/bin/env python3
"""Execute reproducible Codex/Agy/Claude workflow candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import lab  # noqa: E402
from workflow.codegraph import refresh_codegraph  # noqa: E402
from workflow.knowledge import KnowledgeVault, MemorySession  # noqa: E402
from workflow.run import shared_prompt  # noqa: E402


ACTIVE_BENCHMARK_MEMORY: MemorySession | None = None


IMPLEMENT_PROMPT = """\
Work directly in this benchmark workspace. Read TASK.md, AGENTS.md, the source, and
the public tests. Implement every requirement in TASK.md without adding dependencies.
Do not modify TASK.md, AGENTS.md, or tests/. Run both public test commands before
finishing. This is an implementation task: make the edits, do not only describe them.
"""

PLAN_PROMPT = """\
Act as a read-only senior engineer. Read TASK.md, AGENTS.md, source, and public tests.
Produce a concrete implementation plan covering validation, rounding, Promise identity,
rejection cleanup, likely hidden edge cases, and exact verification commands. Do not edit
files. Separate requirements from optional suggestions.
"""

REVIEW_PROMPT = """\
Act as an adversarial read-only reviewer. Read TASK.md and inspect the current git diff.
Run public tests if useful, but do not edit files. Identify only concrete violations,
missing edge cases, test tampering, or unnecessary changes. Rank findings by severity and
cite the affected file/function. A blocking finding must include both (a) the exact TASK.md
sentence it violates and (b) a minimal reproducible input or failing command. Findings
without both are advisory and must not trigger rework. End with exactly `DECISION: PASS`
when there is no blocking finding. Otherwise end with exactly
`DECISION: CHANGES_REQUIRED`.
"""


def command_for(agent: str, mode: str, workspace: Path) -> list[str]:
    if agent == "codex":
        return [
            "codex",
            "exec",
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
            "text",
            "--permission-mode",
            "acceptEdits" if mode == "write" else "plan",
            "--model",
            "sonnet",
            "--effort",
            "high",
        ]
    if agent == "agy":
        return [
            "agy",
            "--print",
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
    raise ValueError(f"unknown agent: {agent}")


def run_stage(
    run_dir: Path,
    workspace: Path,
    index: int,
    label: str,
    agent: str,
    mode: str,
    prompt: str,
) -> dict[str, object]:
    stage_dir = run_dir / "stages" / f"{index:02d}-{label}"
    stage_dir.mkdir(parents=True)
    (stage_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    codegraph = refresh_codegraph(workspace)
    if not codegraph["passed"]:
        raise SystemExit("CodeGraph refresh failed before benchmark Agent stage")
    command = command_for(agent, mode, workspace)
    started = time.monotonic()
    if agent == "codex":
        result = subprocess.run(
            command,
            cwd=workspace,
            input=prompt,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
    elif agent == "agy":
        # Agy's --print flag consumes the immediately following argument as the
        # prompt. Appending the prompt at the end makes the next option name the
        # prompt and can misleadingly exit zero without touching the workspace.
        result = subprocess.run(
            [command[0], command[1], prompt, *command[2:]],
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
    else:
        result = subprocess.run(
            [*command, prompt],
            cwd=workspace,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
            check=False,
        )
    duration = round(time.monotonic() - started, 3)
    output = result.stdout
    (stage_dir / "output.txt").write_text(output, encoding="utf-8")
    diff = subprocess.run(
        ["git", "diff", "--no-ext-diff", "HEAD"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).stdout
    (stage_dir / "workspace.diff").write_text(diff, encoding="utf-8")
    metadata = {
        "label": label,
        "agent": agent,
        "mode": mode,
        "command": [part for part in command if part != prompt],
        "exit_code": result.returncode,
        "duration_seconds": duration,
        "output_file": str(stage_dir / "output.txt"),
        "codegraph": {
            "files": codegraph["files"],
            "nodes": codegraph["nodes"],
            "edges": codegraph["edges"],
        },
    }
    (stage_dir / "stage.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"stage={index} label={label} agent={agent} mode={mode} "
        f"exit={result.returncode} seconds={duration}",
        flush=True,
    )
    return {**metadata, "output": output}


def apply_review_prompt(review: str) -> str:
    return f"""\
Re-read TASK.md and the current implementation. An independent reviewer returned the
report below. Validate every finding against the contract, fix all valid findings, reject
false positives, and run both public test commands. Do not modify TASK.md, AGENTS.md, or
tests/.

--- reviewer report ---
{review}
--- end report ---
"""


def implement_with_plans(agy_plan: str, claude_plan: str) -> str:
    return f"""\
Work directly in this benchmark workspace. Read TASK.md, AGENTS.md, source, and tests.
Two independent read-only engineers supplied plans below. Synthesize them, verify each
claim against TASK.md, implement every contractual requirement, and run both public test
commands. Do not add dependencies or modify TASK.md, AGENTS.md, or tests/.

--- Agy plan ---
{agy_plan}
--- Claude plan ---
{claude_plan}
--- end plans ---
"""


def score(verification: dict[str, object]) -> int:
    checks = verification["checks"]
    weights = {
        "python_public": 10,
        "node_public": 10,
        "python_hidden": 25,
        "node_hidden": 25,
        "gitleaks": 10,
    }
    value = sum(
        weight for name, weight in weights.items() if checks[name]["exit_code"] == 0
    )
    if not verification["protected_files_changed"]:
        value += 20
    return value


def execute_flow(flow: str, name: str) -> None:
    global ACTIVE_BENCHMARK_MEMORY
    workspace = lab.prepare(name)
    run_dir = workspace.parent
    route = (
        "fast"
        if flow == "solo-agy"
        else "standard"
        if flow == "solo-claude"
        else "high"
    )
    source_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    vault = KnowledgeVault(ROOT / "knowledge")
    preflight = vault.prepare_task(
        repo=workspace,
        route=route,
        task_name=f"benchmark-{name}",
        spec=workspace / "TASK.md",
        acceptance=[
            "python3 -m unittest discover -s tests -p 'test_*.py'",
            "node --test tests/singleflight.test.js",
        ],
        source_head=source_head,
        project_id="workflow-benchmark-fixture",
    )
    memory_session = vault.session(preflight, run_dir)
    ACTIVE_BENCHMARK_MEMORY = memory_session
    if not preflight["ready"]:
        memory_session.complete(
            passed=False,
            checks={"preflight": {"exit_code": 1}},
            stages=[],
            changed_files=[],
            source_head=source_head,
        )
        raise SystemExit("benchmark capability or knowledge preflight failed")
    (workspace / "SAGE_KNOWLEDGE.md").write_text(
        preflight["briefing"], encoding="utf-8"
    )
    subprocess.run(["git", "add", "SAGE_KNOWLEDGE.md"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "chore: lock shared SAGE knowledge"],
        cwd=workspace,
        check=True,
    )
    source_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    preflight["source_head"] = source_head
    codegraph = refresh_codegraph(workspace)
    vault.record_dispatch(preflight, run_dir=run_dir, codegraph=codegraph)
    stages: list[dict[str, object]] = []

    def stage(label: str, agent: str, mode: str, prompt: str) -> dict[str, object]:
        result = run_stage(
            run_dir,
            workspace,
            len(stages) + 1,
            label,
            agent,
            mode,
            shared_prompt(prompt),
        )
        stages.append(result)
        return result

    if flow == "solo-codex":
        stage("implement", "codex", "write", IMPLEMENT_PROMPT)
    elif flow == "solo-claude":
        stage("implement", "claude", "write", IMPLEMENT_PROMPT)
    elif flow == "solo-agy":
        stage("implement", "agy", "write", IMPLEMENT_PROMPT)
    elif flow == "codex-claude-review":
        stage("implement", "codex", "write", IMPLEMENT_PROMPT)
        review = stage("review", "claude", "read", REVIEW_PROMPT)
        stage(
            "apply-review", "codex", "write", apply_review_prompt(str(review["output"]))
        )
    elif flow == "claude-agy-review":
        stage("implement", "claude", "write", IMPLEMENT_PROMPT)
        review = stage("review", "agy", "read", REVIEW_PROMPT)
        stage(
            "apply-review",
            "claude",
            "write",
            apply_review_prompt(str(review["output"])),
        )
    elif flow == "claude-agy-gated":
        stage("implement", "claude", "write", IMPLEMENT_PROMPT)
        interim = lab.verify_workspace(workspace)
        (run_dir / "interim-verification.json").write_text(
            json.dumps(interim, indent=2) + "\n", encoding="utf-8"
        )
        review = stage("review", "agy", "read", REVIEW_PROMPT)
        review_passed = "DECISION: PASS" in str(review["output"])
        if not (interim["passed"] and review_passed):
            stage(
                "apply-review",
                "claude",
                "write",
                apply_review_prompt(str(review["output"])),
            )
    elif flow == "tri-model-contract":
        agy_plan = stage("agy-plan", "agy", "read", PLAN_PROMPT)
        claude_plan = stage("claude-plan", "claude", "read", PLAN_PROMPT)
        stage(
            "codex-implement",
            "codex",
            "write",
            implement_with_plans(str(agy_plan["output"]), str(claude_plan["output"])),
        )
        interim = lab.verify_workspace(workspace)
        (run_dir / "interim-verification.json").write_text(
            json.dumps(interim, indent=2) + "\n", encoding="utf-8"
        )
        review = stage("claude-audit", "claude", "read", REVIEW_PROMPT)
        review_passed = "DECISION: PASS" in str(review["output"])
        if not (interim["passed"] and review_passed):
            stage(
                "codex-correct",
                "codex",
                "write",
                apply_review_prompt(str(review["output"])),
            )
    elif flow == "agy-codex-claude-gated":
        agy_plan = stage("agy-plan", "agy", "read", PLAN_PROMPT)
        stage(
            "codex-implement",
            "codex",
            "write",
            implement_with_plans(str(agy_plan["output"]), "No second plan by design."),
        )
        interim = lab.verify_workspace(workspace)
        (run_dir / "interim-verification.json").write_text(
            json.dumps(interim, indent=2) + "\n", encoding="utf-8"
        )
        review = stage("claude-audit", "claude", "read", REVIEW_PROMPT)
        review_passed = "DECISION: PASS" in str(review["output"])
        if not (interim["passed"] and review_passed):
            stage(
                "codex-correct",
                "codex",
                "write",
                apply_review_prompt(str(review["output"])),
            )
    else:
        raise SystemExit(f"unknown flow: {flow}")

    verification = lab.verify_workspace(workspace)
    (run_dir / "verification.json").write_text(
        json.dumps(verification, indent=2) + "\n", encoding="utf-8"
    )
    public_stages = [
        {k: v for k, v in item.items() if k != "output"} for item in stages
    ]
    changed_files = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.splitlines()
    knowledge = memory_session.complete(
        passed=bool(verification["passed"]),
        checks=verification["checks"],
        stages=public_stages,
        changed_files=changed_files,
        source_head=source_head,
    )
    summary = {
        "flow": flow,
        "name": name,
        "quality_score": score(verification),
        "passed": verification["passed"],
        "total_agent_seconds": round(
            sum(float(item["duration_seconds"]) for item in stages), 3
        ),
        "all_agent_stages_exited_zero": all(item["exit_code"] == 0 for item in stages),
        "stages": public_stages,
        "verification_file": str(run_dir / "verification.json"),
        "knowledge": knowledge,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


def main() -> None:
    flows = [
        "solo-codex",
        "solo-claude",
        "solo-agy",
        "codex-claude-review",
        "claude-agy-review",
        "claude-agy-gated",
        "tri-model-contract",
        "agy-codex-claude-gated",
    ]
    parser = argparse.ArgumentParser()
    parser.add_argument("flow", nargs="?", choices=flows)
    parser.add_argument("name", nargs="?")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        print("\n".join(flows))
        return
    if not args.flow or not args.name:
        parser.error("flow and name are required unless --list is used")
    execute_flow(args.flow, args.name)


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        if (
            ACTIVE_BENCHMARK_MEMORY is not None
            and not ACTIVE_BENCHMARK_MEMORY.finalized
        ):
            try:
                failure_memory = ACTIVE_BENCHMARK_MEMORY.fail(error)
                (ACTIVE_BENCHMARK_MEMORY.run_dir / "failure-memory.json").write_text(
                    json.dumps(failure_memory, indent=2) + "\n", encoding="utf-8"
                )
            except Exception as memory_error:
                print(
                    f"knowledge finalization also failed: {memory_error}",
                    file=sys.stderr,
                )
        raise
