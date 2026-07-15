#!/usr/bin/env python3
"""Verify a committed public SAGE export using a trusted base-revision keyring."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.public_export import PublicExportError, verify_public_export


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--allowed-signers", type=Path, required=True)
    parser.add_argument("--expected-repository")
    parser.add_argument("--expected-source-repository")
    args = parser.parse_args()
    try:
        result = verify_public_export(
            args.repo,
            allowed_signers=args.allowed_signers,
            expected_repository=args.expected_repository,
            expected_source_repository=args.expected_source_repository,
        )
    except PublicExportError as error:
        print(f"public export verification failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
