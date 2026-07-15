#!/usr/bin/env python3
"""Unified SAGE task entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.task_config import (
    load_task_config,
    preflight_argv,
    promote_argv,
    run_argv,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SAGE from one task config.")
    parser.add_argument(
        "command", choices=("preflight", "run", "promote", "resume-promotion")
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = load_task_config(args.config)
    if args.command == "preflight":
        command = preflight_argv(config, preflight=ROOT / "workflow" / "preflight.py")
    elif args.command == "run":
        command = run_argv(config, runner=ROOT / "workflow" / "run.py")
    else:
        command = promote_argv(
            config,
            promoter=ROOT / "workflow" / "promote.py",
            resume=args.command == "resume-promotion",
        )
    if args.dry_run:
        print(json.dumps({"command": command}, indent=2))
        return
    completed = subprocess.run(command, cwd=ROOT, check=False)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
