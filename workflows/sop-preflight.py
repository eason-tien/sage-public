#!/usr/bin/env python3
"""Build a verified, content-addressed input bundle for sop-run.js."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workflow.codegraph import refresh_codegraph  # noqa: E402
from workflow.knowledge import task_requires_stitch  # noqa: E402


REQUIRED_MATERIALS = {
    "rules": "SAGE_RULES.md",
    "design": "DESIGN.md",
    "planPrompt": "prompts/03-plan.md",
    "reviewPrompt": "prompts/04-review-crosscheck.md",
    "goalPrompt": "prompts/05-goal.md",
    "goalChecklist": "checklists/goal-gates.md",
}


def _regular_text(path: Path, *, label: str) -> str:
    path = path.expanduser()
    path = path if path.is_absolute() else path.absolute()
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"{label} must be a regular file: {path}")
    path = path.resolve()
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise SystemExit(f"{label} must be valid UTF-8: {path}") from error
    if not content.strip():
        raise SystemExit(f"{label} must be nonempty: {path}")
    return content


def _material(path: Path, *, label: str) -> dict[str, str]:
    content = _regular_text(path, label=label)
    return {
        "path": str(path.expanduser().resolve()),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def _git_root(path: Path) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"sageRoot is not a git repository: {path}")
    return Path(completed.stdout.strip()).resolve()


def _git_head(path: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    head = completed.stdout.strip().lower()
    if completed.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise SystemExit(f"cannot resolve a SHA-1 source HEAD for sageRoot: {path}")
    return head


def build_bundle(
    *,
    sage_root: Path,
    task: str,
    spec: Path,
    knowledge: Path,
    reviewers: int,
    stitch_design: Path | None,
) -> dict[str, Any]:
    sage_root = sage_root.expanduser().resolve()
    if _git_root(sage_root) != sage_root:
        raise SystemExit("sageRoot must be the repository root")
    source_head = _git_head(sage_root)
    task = task.strip()
    if not task:
        raise SystemExit("task must be nonempty")
    if reviewers not in {2, 3, 4}:
        raise SystemExit("reviewers must be an integer from 2 through 4")

    materials = {
        name: _material(sage_root / relative, label=name)
        for name, relative in REQUIRED_MATERIALS.items()
    }
    materials["spec"] = _material(spec, label="spec")
    materials["knowledge"] = _material(knowledge, label="SAGE_KNOWLEDGE")
    spec_text = materials["spec"]["content"]
    stitch_required = task_requires_stitch(task, spec_text)
    if stitch_required:
        if stitch_design is None:
            raise SystemExit(
                "UI/WPF task requires --stitch-design with a locked Stitch export"
            )
        materials["stitchDesign"] = _material(stitch_design, label="STITCH_DESIGN")

    codegraph = refresh_codegraph(sage_root)
    if not codegraph.get("passed"):
        raise SystemExit("CodeGraph must be current before SOP workflow dispatch")
    return {
        "schemaVersion": 2,
        "generatedBy": "sop-preflight.py/v2",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "sageRoot": str(sage_root),
        "sourceHead": source_head,
        "reviewers": reviewers,
        "materials": materials,
        "codegraph": {
            "status": "current",
            "action": codegraph.get("action"),
            "files": codegraph.get("files"),
            "nodes": codegraph.get("nodes"),
            "edges": codegraph.get("edges"),
        },
        "stitchRequired": stitch_required,
        "r5_human_verification": "pending",
        "merge_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sage-root", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path, required=True)
    parser.add_argument("--reviewers", type=int, default=3)
    parser.add_argument("--stitch-design", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    bundle = build_bundle(
        sage_root=args.sage_root,
        task=args.task,
        spec=args.spec,
        knowledge=args.knowledge,
        reviewers=args.reviewers,
        stitch_design=args.stitch_design,
    )
    rendered = json.dumps(bundle, indent=2) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
