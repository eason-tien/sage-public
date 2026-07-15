#!/usr/bin/env python3
"""Aggregate functional, timing, diff, and maintainability evidence."""

from __future__ import annotations

import json
from pathlib import Path
import statistics
import subprocess


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
REPORTS = ROOT / "reports"
EXCLUDED = {
    "solo-agy-1": "invalid adapter invocation: --print consumed an option name as the prompt"
}


def command_ok(command: list[str], cwd: Path) -> bool:
    return (
        subprocess.run(
            command,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def diff_metrics(workspace: Path) -> tuple[int, int, int]:
    output = subprocess.run(
        ["git", "diff", "--numstat", "HEAD"],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout
    files = added = deleted = 0
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        files += 1
        added += int(parts[0])
        deleted += int(parts[1])
    return files, added, deleted


def collect() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for summary_path in sorted(RUNS.glob("*/summary.json")):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        name = str(summary["name"])
        workspace = summary_path.parent / "workspace"
        files, added, deleted = diff_metrics(workspace)
        ruff_lint = command_ok(["ruff", "check", "src/pricing.py"], workspace)
        python_format = command_ok(
            ["ruff", "format", "--check", "src/pricing.py"], workspace
        )
        js_quality = command_ok(
            [
                "biome",
                "check",
                "--config-path",
                str(ROOT / "biome.json"),
                "src/singleflight.js",
            ],
            workspace,
        )
        excluded_reason = EXCLUDED.get(name)
        rows.append(
            {
                "name": name,
                "flow": summary["flow"],
                "functional_score": summary["quality_score"],
                "functional_passed": summary["passed"],
                "agent_seconds": summary["total_agent_seconds"],
                "model_stages": len(summary["stages"]),
                "files_changed": files,
                "lines_added": added,
                "lines_deleted": deleted,
                "ruff_lint": ruff_lint,
                "python_format": python_format,
                "js_quality": js_quality,
                "maintainability_gate": ruff_lint and python_format and js_quality,
                "excluded": excluded_reason is not None,
                "excluded_reason": excluded_reason,
            }
        )

    valid_rows = [row for row in rows if not row["excluded"]]
    by_flow: dict[str, list[dict[str, object]]] = {}
    for row in valid_rows:
        by_flow.setdefault(str(row["flow"]), []).append(row)
    aggregates = []
    for flow, flow_rows in sorted(by_flow.items()):
        aggregates.append(
            {
                "flow": flow,
                "runs": len(flow_rows),
                "all_functional_passed": all(
                    bool(row["functional_passed"]) for row in flow_rows
                ),
                "median_agent_seconds": round(
                    statistics.median(float(row["agent_seconds"]) for row in flow_rows),
                    3,
                ),
                "maintainability_pass_rate": round(
                    sum(bool(row["maintainability_gate"]) for row in flow_rows)
                    / len(flow_rows),
                    3,
                ),
            }
        )
    return {"runs": rows, "flow_aggregates": aggregates}


def markdown(data: dict[str, object]) -> str:
    lines = [
        "# Multi-CLI Benchmark Results",
        "",
        "Generated from the raw run summaries and fresh local quality checks.",
        "",
        "| Run | Flow | Functional | Seconds | Stages | Diff +/− | Ruff | Format | Biome | Excluded |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in sorted(data["runs"], key=lambda item: float(item["agent_seconds"])):
        excluded = str(row["excluded_reason"] or "")
        lines.append(
            "| {name} | {flow} | {functional_score} | {agent_seconds:.1f} | "
            "{model_stages} | +{lines_added}/-{lines_deleted} | {ruff} | {fmt} | "
            "{biome} | {excluded_text} |".format(
                **row,
                ruff="pass" if row["ruff_lint"] else "fail",
                fmt="pass" if row["python_format"] else "fail",
                biome="pass" if row["js_quality"] else "fail",
                excluded_text=excluded.replace("|", "\\|"),
            )
        )
    lines.extend(
        [
            "",
            "## Flow aggregates",
            "",
            "| Flow | Runs | All functional | Median seconds | Maintainability pass rate |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in data["flow_aggregates"]:
        lines.append(
            "| {flow} | {runs} | {all_functional_passed} | "
            "{median_agent_seconds:.1f} | {maintainability_pass_rate:.0%} |".format(
                **row
            )
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    data = collect()
    (REPORTS / "benchmark-results.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    (REPORTS / "benchmark-results.md").write_text(markdown(data), encoding="utf-8")
    print(REPORTS / "benchmark-results.md")


if __name__ == "__main__":
    main()
