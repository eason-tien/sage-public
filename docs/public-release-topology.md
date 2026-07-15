# History-free public release topology

The full `eason-tien/sage` repository stays private because its tree and history contain benchmark
oracles. GitHub Copilot Pro does not unlock protected branches for a private personal repository,
so the no-upgrade route uses a separate public repository, `eason-tien/sage-public`, for
server-enforced required checks. Making the existing repository public is not an acceptable
shortcut.

## Trust boundary

The private repository remains the source of truth and runs the public and private acceptance
gates. A successful exact-head attestation is only eligible for export when it explicitly ran both
private oracle commands and retained:

- `automated_gates_passed=true`;
- `r5_human_verification=pending`;
- `merge_authorized=false`.

`tools/public_export.py` then reads one committed Git tree, not the worktree, and creates a new
repository without copying `.git` or any parent commit. It removes the oracle directories and the
private CI/policy, rejects symlinks, gitlinks, case-fold collisions, unsafe paths, and any public
file whose Git blob is byte-identical to an excluded oracle blob. A redacted Gitleaks scan must
pass before signing.

The exporter creates exactly two commits:

1. `master`: the trusted verifier, signer allowlist, and inert public workflows;
2. `codex/public-v0.13.2`: the sanitized candidate plus a detached SSH-signed certificate.

The certificate binds the private source commit and tree digest, sanitized public tree digest,
private attestation manifest and signer, export signer, repository identities, and the safe
automation state. `.sage-public-export/certificate.json` and its signature are the only files
excluded from the public tree digest.

## GitHub checks

The public PR runs ordinary tests in `SAGE Public CI`. A separate `pull_request_target` workflow,
`SAGE Private Oracle`, checks out the base revision's trusted verifier and treats the PR head only
as data. It does not execute scripts or workflows from the candidate. Branch protection must
require this oracle check and every public CI check named in
`templates/github/sage-public-merge-policy.json`.

The signed certificate proves that the private gates passed for the exact exported source; it does
not reveal or execute the private oracle files in the public repository. Any source change must
return to the private repository, produce a new exact-head attestation, and be exported again.

## Local preparation

Only use an attestation that contains the two explicit oracle commands and the private-tree
version-ledger gate:

```bash
python3 tools/lab.py verify-fixture
python3 tools/audit_sprite_game.py --no-write
python3 tools/check_version_record.py
```

Then prepare and independently verify a local candidate:

```bash
python3 tools/public_export.py \
  --repo . \
  --source-ref HEAD \
  --destination /outside/source/sage-public-v0.13.2 \
  --source-repository eason-tien/sage \
  --public-repository eason-tien/sage-public \
  --branch codex/public-v0.13.2 \
  --attestation-run /outside/source/attestation \
  --attestation-allowed-signers ~/.config/sage/automated_allowed_signers \
  --signing-key ~/.config/sage/evidence_ed25519 \
  --signer-identity eason-tien-sage

python3 tools/verify_public_export.py \
  --repo /outside/source/sage-public-v0.13.2 \
  --allowed-signers /outside/source/sage-public-v0.13.2/workflow/trusted_signers \
  --expected-repository eason-tien/sage-public \
  --expected-source-repository eason-tien/sage
```

Do not create or push the public repository until local tests, secret scanning, the two-commit
history check, and signed export verification all pass. Do not mark the PR ready, merge it, or tag a
release until a human completes commit-bound R5. Automated and GitHub results may report only
`automated_gates_passed` or `ci_passed`.
