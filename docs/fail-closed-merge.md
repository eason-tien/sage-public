# Fail-closed PR merge

`tools/merge_pr.py` is the supported local merge entrypoint. It does not turn automated green into human approval. When operators use it, it merges only when all of the following bind to one exact PR head SHA:

- the committed `.github/sage-merge-policy.json` and every named GitHub check;
- a valid signed automated evidence run that still says R5 pending and merge unauthorized;
- a human-run acceptance log;
- a fresh, separately signed `SAGE Human R5` JSON artifact;
- the authenticated GitHub actor, clean local branch, open non-draft PR, mergeable state, and no auto-merge request.

The final `gh pr merge` call always uses `--match-head-commit`. It never uses `--admin`, `--auto`, or branch deletion. `--execute` additionally requires an interactive terminal and an exact PR/SHA confirmation; validation-only is the default. Because the interactive wait is unbounded, R5 freshness is checked again after the operator enters the exact phrase and before the final GitHub snapshot.

This wrapper is a fail-closed local operating control, not a GitHub authorization boundary. A user with repository merge permission can bypass it through the web UI or a direct `gh pr merge`, and a check can change state after the wrapper's final snapshot while the head SHA remains unchanged. Keep R5 and release blocked until GitHub required checks/rulesets enforce the same policy server-side. On the current private repository those APIs return HTTP 403 without a qualifying GitHub plan; the available remedies are upgrading the plan or making the repository public before enabling the rules.

## Human R5 artifact

Keep the artifact, its signature, the acceptance log, and both allowed-signers files outside tracked source (for example under an ignored run directory). The human artifact has this exact schema:

```json
{
  "schema_version": 1,
  "kind": "SAGE Human R5",
  "repository": "eason-tien/sage",
  "pr_number": 0,
  "head_sha": "0000000000000000000000000000000000000000",
  "human_identity": "human-r5@example.com",
  "human_signer_fingerprint": "SHA256:0000000000000000000000000000000000000000000",
  "github_actor": "eason-tien",
  "verified_at_utc": "2026-07-14T00:00:00+00:00",
  "policy_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "automated_evidence_manifest_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "acceptance_log_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "files_changed_reviewed": true,
  "spontaneous_check": "Describe the unannounced manual check and its observed result.",
  "r5_human_verification": "passed",
  "merge_authorized": true
}
```

Only the human performing R5 may replace the placeholders, set the human-owned fields, and sign the final immutable bytes. `human_signer_fingerprint` must be the OpenSSH SHA-256 fingerprint of the key that signs the artifact. Use a human key and a human-only allowed-signers file whose key set has no overlap with the automated evidence trust store:

```bash
ssh-keygen -lf ~/.ssh/id_ed25519.pub -E sha256
ssh-keygen -Y sign -f ~/.ssh/id_ed25519 -n sage-r5 /outside/repo/r5.json
```

After the signature is created, do not edit the JSON. First validate without merging:

```bash
python3 tools/merge_pr.py \
  --repo . \
  --r5-artifact /outside/repo/r5.json \
  --r5-allowed-signers ~/.config/sage/r5_allowed_signers \
  --automated-run-dir /outside/repo/attestation \
  --automated-allowed-signers ~/.config/sage/automated_allowed_signers \
  --acceptance-log /outside/repo/verify.log
```

The human may append `--execute` only after inspecting the validation result. Any missing check, skipped or failed check, stale evidence, branch movement, signature mismatch, dirty worktree, draft state, conflict, or noninteractive invocation blocks the merge with exit 2.
