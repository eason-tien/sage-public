#!/usr/bin/env python3
"""Prepare a signed, history-free public SAGE repository candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow.public_export import PublicExportError, prepare_public_repository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--public-repository", required=True)
    parser.add_argument("--branch", default="codex/public-v0.13.2")
    parser.add_argument("--attestation-run", type=Path, required=True)
    parser.add_argument("--attestation-allowed-signers", type=Path, required=True)
    parser.add_argument("--signing-key", type=Path, required=True)
    parser.add_argument("--signer-identity", required=True)
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    try:
        result = prepare_public_repository(
            args.repo,
            args.source_ref,
            args.destination,
            source_repository=args.source_repository,
            public_repository=args.public_repository,
            branch=args.branch,
            attestation_run=args.attestation_run,
            attestation_allowed_signers=args.attestation_allowed_signers,
            signing_key=args.signing_key,
            signer_identity=args.signer_identity,
        )
    except PublicExportError as error:
        print(f"public export blocked: {error}", file=sys.stderr)
        return 2
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result is not None:
        result_path = args.result.expanduser().resolve()
        if result_path.exists():
            print(f"public export result exists: {result_path}", file=sys.stderr)
            return 2
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
