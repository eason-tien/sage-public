#!/usr/bin/env python3
"""Run capability, knowledge, version, and CodeGraph preflight without dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.codegraph import refresh_codegraph
from workflow.knowledge import KnowledgeVault
from workflow.run import ensure_repo, git_stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--route", choices=("fast", "standard", "high"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--knowledge-vault", type=Path, required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--stitch-design", type=Path)
    args = parser.parse_args()
    repo = ensure_repo(args.repo.resolve())
    spec = args.spec.resolve()
    if not spec.is_file():
        raise SystemExit(f"missing spec: {spec}")
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
        stitch_design=args.stitch_design,
    )
    codegraph = refresh_codegraph(repo)
    preflight["codegraph"] = {
        "status": "current" if codegraph["passed"] else "failed",
        "action": codegraph["action"],
        "files": codegraph["files"],
        "nodes": codegraph["nodes"],
        "edges": codegraph["edges"],
    }
    preflight["ready"] = bool(preflight["ready"] and codegraph["passed"])
    print(
        json.dumps(
            {key: value for key, value in preflight.items() if key != "briefing"},
            indent=2,
        )
    )
    raise SystemExit(0 if preflight["ready"] else 1)


if __name__ == "__main__":
    main()
