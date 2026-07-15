#!/usr/bin/env python3
"""Benchmark safe SAGE gate discovery against pinned real repositories."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.gates import detect_languages


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path, timeout: int = 300) -> dict[str, Any]:
    started = time.monotonic()
    recorded_command = [part.replace(str(ROOT), "$PROJECT_ROOT") for part in command]
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
            env=environment,
        )
        return {
            "command": recorded_command,
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": completed.stdout,
        }
    except subprocess.TimeoutExpired as error:
        return {
            "command": recorded_command,
            "exit_code": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "output": str(error),
        }


def checkout(entry: dict[str, str], destination: Path) -> dict[str, Any]:
    repo = entry["repo"]
    sha = entry["sha"]
    if destination.exists():
        shutil.rmtree(destination)
    clone = run(
        [
            "git",
            "clone",
            "--quiet",
            "--filter=blob:none",
            "--no-checkout",
            f"https://github.com/{repo}.git",
            str(destination),
        ],
        destination.parent,
    )
    if clone["exit_code"] != 0:
        return {"passed": False, "clone": clone, "error": "clone failed"}
    fetched = run(["git", "fetch", "--quiet", "--depth=1", "origin", sha], destination)
    checked = run(["git", "checkout", "--quiet", "--detach", sha], destination)
    return {"clone": clone, "fetch": fetched, "checkout": checked}


def benchmark_one(
    entry: dict[str, str], destination: Path, gate_catalog: dict[str, Any]
) -> dict[str, Any]:
    started = time.monotonic()
    setup = checkout(entry, destination)
    if setup.get("error"):
        return {
            **entry,
            **setup,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    head = run(["git", "rev-parse", "HEAD"], destination)
    files_result = run(["git", "ls-files"], destination)
    files = (
        files_result["output"].splitlines() if files_result["exit_code"] == 0 else []
    )
    languages = detect_languages(files)
    clean = run(["git", "status", "--porcelain"], destination)
    diff_check = run(["git", "diff", "--check"], destination)
    gitleaks_report = destination.parent / f"{destination.name}-gitleaks.json"
    gitleaks_report.unlink(missing_ok=True)
    gitleaks = run(
        [
            "gitleaks",
            "detect",
            "--no-git",
            "--redact",
            "--source",
            str(destination),
            "--report-format",
            "json",
            "--report-path",
            str(gitleaks_report),
        ],
        destination,
    )
    language_gate = gate_catalog.get(entry["language"])
    benchmark_valid = all(
        [
            head["exit_code"] == 0,
            head["output"].strip() == entry["sha"],
            entry["language"] in languages,
            clean["exit_code"] == 0 and not clean["output"].strip(),
            diff_check["exit_code"] == 0,
            language_gate is not None,
        ]
    )
    findings = []
    if gitleaks_report.is_file():

        def relative_finding_path(value: Any) -> str | None:
            if not isinstance(value, str):
                return None
            path = Path(value)
            try:
                return str(path.resolve().relative_to(destination.resolve()))
            except ValueError:
                return value

        findings = [
            {
                "rule_id": finding.get("RuleID"),
                "file": relative_finding_path(finding.get("File")),
                "line": finding.get("StartLine"),
                "description": finding.get("Description"),
            }
            for finding in json.loads(gitleaks_report.read_text(encoding="utf-8"))
        ]
    strict_gates_passed = benchmark_valid and gitleaks["exit_code"] == 0
    return {
        **entry,
        "url": f"https://github.com/{entry['repo']}/commit/{entry['sha']}",
        "passed": benchmark_valid,
        "benchmark_valid": benchmark_valid,
        "strict_gates_passed": strict_gates_passed,
        "gitleaks_findings": findings,
        "file_count": len(files),
        "detected_languages": languages,
        "gate_candidate": language_gate,
        "external_code_executed": False,
        "checks": {
            "head": head,
            "clean": clean,
            "diff_check": diff_check,
            "gitleaks": gitleaks,
        },
        "setup": setup,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Real-Repository Gate Portability Benchmark",
        "",
        f"Generated: {result['generated_at']}",
        "",
        "External repository contents were treated as untrusted data. No build, test, hook, or repository script was executed.",
        "",
        "| Language | Repository | Commit | Files | Gate candidate | Benchmark | Strict gates |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for item in result["repositories"]:
        gate = (item.get("gate_candidate") or {}).get("gate", "missing")
        status = "PASS" if item.get("benchmark_valid") else "FAIL"
        strict = "PASS" if item.get("strict_gates_passed") else "FINDINGS"
        lines.append(
            f"| {item['language']} | [{item['repo']}]({item.get('url', 'https://github.com/' + item['repo'])}) | "
            f"`{item['sha'][:12]}` | {item.get('file_count', 0)} | {gate} | {status} | {strict} |"
        )
    lines.extend(
        [
            "",
            f"Overall: **{'PASS' if result['passed'] else 'FAIL'}** — "
            f"{result['valid_count']}/{result['repository_count']} pinned repositories were valid; "
            f"{result['strict_pass_count']} passed every strict gate.",
            "",
        ]
    )
    findings = [item for item in result["repositories"] if item["gitleaks_findings"]]
    if findings:
        lines.extend(
            [
                "## Strict-gate findings",
                "",
                "These are compatibility findings, not suppressed failures:",
                "",
            ]
        )
        for item in findings:
            locations = ", ".join(
                sorted(
                    {
                        f"`{finding['file']}:{finding['line']}`"
                        for finding in item["gitleaks_findings"]
                    }
                )
            )
            lines.append(
                f"- **{item['repo']}**: {len(item['gitleaks_findings'])} redacted "
                f"Gitleaks findings at {locations}."
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest", type=Path, default=ROOT / "benchmarks" / "real-repos.json"
    )
    parser.add_argument("--workdir", type=Path, default=ROOT / "runs" / "real-repos")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "reports" / "real-repo-benchmark.json",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "reports" / "real-repo-benchmark.md",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    catalog = json.loads(
        (ROOT / "workflow" / "language-gates.json").read_text(encoding="utf-8")
    )["languages"]
    args.workdir.mkdir(parents=True, exist_ok=True)
    repositories = []
    for entry in manifest["repositories"]:
        destination = args.workdir / entry["repo"].replace("/", "--")
        repositories.append(benchmark_one(entry, destination, catalog))
        print(
            f"{entry['language']}: {entry['repo']} -> "
            f"{'PASS' if repositories[-1].get('passed') else 'FAIL'}",
            flush=True,
        )
    valid_count = sum(item.get("benchmark_valid") is True for item in repositories)
    strict_pass_count = sum(
        item.get("strict_gates_passed") is True for item in repositories
    )
    result = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": manifest["policy"],
        "repository_count": len(repositories),
        "language_count": len({item["language"] for item in repositories}),
        "valid_count": valid_count,
        "strict_pass_count": strict_pass_count,
        "passed": valid_count == len(repositories) and len(repositories) >= 10,
        "repositories": repositories,
    }
    args.output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.output_md.write_text(markdown_report(result), encoding="utf-8")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
