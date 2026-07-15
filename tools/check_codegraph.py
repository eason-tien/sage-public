#!/usr/bin/env python3
"""Refresh CodeGraph and fail unless the index is current."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.codegraph import refresh_codegraph


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path, nargs="?", default=Path.cwd())
    args = parser.parse_args()
    result = refresh_codegraph(args.project)
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "action": result["action"],
                "files": result["files"],
                "nodes": result["nodes"],
                "edges": result["edges"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
