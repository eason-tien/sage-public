# Governance recovery audit for v0.13.2

Audit date: 2026-07-14
Recovery base: `master@4037388865b87bcdcdfb806a28e2655509f5dbc5`
Recovery branch: `codex/governance-recovery-v0.13.2`

## Decision

The repository history proves that PR #7 through #10 were merged, but it does not prove that those merges were authorized by a valid human R5. Every one of those PRs had at least one failing GitHub Actions check at merge time; none has an `APPROVED` review decision. Therefore this recovery records the historical merge as an observation only:

- `merge_observed=true`
- `r5_human_verification=pending`
- `merge_authorized=false`

No previous tag is silently rewritten. A new v0.13.2 candidate must pass the repaired gates and be verified by a human against its exact final commit SHA before release.

## GitHub PR #7–#10 immutable trace

The following values were read back from GitHub PR metadata and check rollups. Commit OIDs and Actions run links are immutable anchors.

| PR | Base → head → merge | Merged at (UTC) | Review evidence | Head check rollup (listed failure completed before merge) |
|---|---|---|---|---|
| [#7](https://github.com/eason-tien/sage/pull/7) | `53f21ea7f9cf8a257368bea8472a2e55cd74d49e` → `fa82d17b9c44dc2226a1bbdd90d8769e5b2439af` → `d8ea8c7fb0e3105823d36ce814c5231e84893d7a` | `2026-07-14T12:31:55Z` | Codex `COMMENTED` on the final head before merge; no approval | [run 29332495920](https://github.com/eason-tien/sage/actions/runs/29332495920): `test=FAILURE`, macOS selftest `FAILURE` |
| [#8](https://github.com/eason-tien/sage/pull/8) | `d8ea8c7fb0e3105823d36ce814c5231e84893d7a` → `2ae3b375dc1df5af3d0afa673b0feba614843c7b` → `e6b7b4d5c754aeeb4590e7a962c5e23dcf69b33f` | `2026-07-14T12:46:48Z` | Codex `COMMENTED` on the final head before merge; no approval | [run 29333524511](https://github.com/eason-tien/sage/actions/runs/29333524511): `test=FAILURE` |
| [#9](https://github.com/eason-tien/sage/pull/9) | `e6b7b4d5c754aeeb4590e7a962c5e23dcf69b33f` → `bd7736f51e201d57844ab1998718727986b9722d` → `2d3954193825b56b83900213588b4a4fd3d72808` | `2026-07-14T13:26:22Z` | Codex `COMMENTED` on `0751fc98e7e3257482942993b6aa3f6b86b2d134`, not the final head; no approval | [run 29336265275](https://github.com/eason-tien/sage/actions/runs/29336265275): `test=FAILURE` |
| [#10](https://github.com/eason-tien/sage/pull/10) | `2d3954193825b56b83900213588b4a4fd3d72808` → `1cd4d67f4ab6755a95cb9b60df0df199c628d293` → `4037388865b87bcdcdfb806a28e2655509f5dbc5` | `2026-07-14T13:32:34Z` | Codex `COMMENTED` at `2026-07-14T13:34:18Z`, after merge; no approval | [run 29336786194](https://github.com/eason-tien/sage/actions/runs/29336786194): `test=FAILURE` |

The absence of an approval is not automatically a defect in a single-owner repository. The defect is that merge observation, automated green, review comments, and human R5 were not mechanically separated. The new local merge wrapper supplies a fail-closed operating path, but it remains voluntarily bypassable and is not a substitute for server-side required checks.

## Local ledger 0.1.18–0.1.21 recovery trace

The ignored run evidence was re-read and both v0.1.21 signatures were replayed with `ssh-keygen -Y verify`. The trusted evidence identity was `eason-tien-sage`, fingerprint `SHA256:3Pa2VT9bpQDBeYL+dCD3mS8zOW/CTteXMcF6Ws1gguE`. Every automated evidence state remains `r5_human_verification=pending` and `merge_authorized=false`.

| Ledger version | Signed source head | Original code / knowledge source | Recovery commit | Recovery verification |
|---|---|---|---|---|
| `0.1.18` | `5937fe95a14b38b5b4c46ad9197d0d598724c54a` | code `f85c490`; records `ec07f11` | code `9b74ab5`; records `af44feb` | stable code patch-id equal: `c6973443996622335ec04e02a9ac02e5ce85fbb0` |
| `0.1.19` | `5937fe95a14b38b5b4c46ad9197d0d598724c54a` | `ec07f11` | `af44feb` | stable patch-id equal: `f6cbc80863c50c606d07a29a45d656d652dcb79a` |
| `0.1.20` | `5937fe95a14b38b5b4c46ad9197d0d598724c54a` | `ec07f11` | `af44feb` | same signed knowledge-promotion commit as 0.1.19 |
| `0.1.21` | `ec07f113f2435317fff197610176e771bb33d955` | code `016fef0`; records `d8b0cd4` | code `143b0f8`; records `86e3571` | record patch-id equal; code was semantically conflict-resolved to preserve the stronger master behavior and add cwd coverage |

The v0.1.21 record-repair manifest binds `head_before_repair=016fef010a1be5ae8893207b47cce35b5a7ab76e`, PR #6, the upstream evidence hashes, and the materialized knowledge-file hashes. Its detached `sage-evidence` signature and the upstream run signature both verify with the trusted key above.

## Repaired controls in this candidate

- Version ledger validation covers the full base-to-head range and reads the candidate ledger from the named head, preventing a reports-only tip or merge commit from hiding unversioned project changes.
- Candidate-tree digests use a temporary Git index and object database with the repository's canonical clean filters, literal NUL-delimited paths, deletions, symlinks, gitlinks, ignored-path exclusion, and unborn-repository handling. The live index and object database remain untouched.
- Runner and post-implementation attestation gates use an immutable clone baseline, remove its source remote, and compare an exact reconstructed patch that includes new files through intent-to-add. They make nonzero/moved-HEAD stages fatal, reject absolute or out-of-root symlinks before and after gates, and reject empty candidates throughout gates, knowledge finalization, and evidence signing.
- Acceptance, quality, and promotion replay gates receive a credential-minimized allowlisted environment. Signed results disclose `filesystem_sandbox=false` and `network_sandbox=false`: static symlink escapes are blocked, but hostile candidate execution still requires an external container or VM for OS-level isolation.
- Crosscheck requires two successful nonempty reviewers by default; failed or empty reviewer output cannot count toward quorum.
- SOP execution recomputes every preflight content hash, binds source HEAD and freshness, checks Stitch/spec consistency, enforces semantic schemas and reviewer quorum, and stops before the human gate on invalid input. Bundle authenticity still depends on the trusted launcher; the runtime guarantee is content integrity, not an unforgeable external attestation.
- Acceptance locking now checks the complete digest pipeline under `pipefail`; the Claude Stop hook handles `stop_hook_active` without an infinite retry loop.
- `.github/sage-merge-policy.json` plus `tools/merge_pr.py` require every reported check to pass, require the five named CI jobs, verify immutable snapshots of separate signed automated and human evidence, reject overlapping signer keys, bind the human log and policy hashes, recheck GitHub state, and merge only with an exact head match. This is a local operating control; the private repository currently cannot enable protection/rulesets under its GitHub plan (HTTP 403), so it is not yet server-enforced.
- The no-upgrade route keeps the oracle-bearing repository private and prepares a separate two-commit, history-free `eason-tien/sage-public` candidate. Its signed export certificate binds the exact private attestation and sanitized public tree; the public `pull_request_target` oracle uses only the base revision's trusted verifier and treats candidate contents as data. This control remains local and unprovisioned until the sanitized repository is independently verified, created, and its required checks are enabled.

## Still pending

This report is an automated audit, not a human acceptance artifact. Before v0.13.2 is released, the exact final candidate SHA still needs:

1. full local gates and signed automated attestation;
2. a Draft PR whose five configured GitHub checks all pass;
3. human review of Files changed, the verification log, known traps, and an unannounced manual check;
4. a fresh human `SAGE Human R5` artifact signed under the separate `sage-r5` namespace;
5. human-operated `tools/merge_pr.py --execute`, followed by release from the resulting `master` commit.

Server-side merge enforcement remains an explicit release blocker: either upgrade the GitHub plan, or complete the history-free `eason-tien/sage-public` publication and enable its required checks before claiming that the merge policy cannot be bypassed. The private oracle-bearing repository itself must not be made public.

## Final adversarial closure

Three independent adversarial reviewers attacked the ledger, workflow surfaces, runner, evidence signatures, Stitch classifier, and merge wrapper after the first repair pass. Their reproducible findings included frontmatter/body spoofing, incomplete failed-history records, staged-index decoys, forged SOP hashes, Stop-hook path exceptions, PowerShell partial-output false green, stale reviewer files, impossible attestation signing, signature/allowlist TOCTOU, shared human/automation keys, Git index/metadata mechanisms that hid candidate changes, credential inheritance, and mixed policy/UI wording that could bypass Stitch. The candidate now has explicit regression tests for those paths. Their final read-only closure found no reproducible P0/P1 within the declared trusted-gate-runtime threat model.

Final local evidence on the dirty candidate:

- Python: 119 tests passed in the final knowledge audit.
- SOP runtime: 33 Node tests passed.
- Bash selftest: 93 passed, 0 failed.
- PowerShell selftest: 75 passed, 0 failed.
- Fixture discrimination and sprite audit passed while keeping R5 pending and merge unauthorized.
- Ruff, Ruff format, Biome, Gitleaks, ShellCheck, Actionlint, diff check, and CodeGraph passed; CodeGraph indexed 45 files / 1003 nodes / 3011 edges in the final knowledge run.
- Obsidian project ledger reached schema 2 version `0.1.28`; the final audit report independently parsed the version gate and matched expected/reported `0.1.28`.

One material assurance gap remains explicit rather than hidden: this repository does not create an OS filesystem or network sandbox for arbitrary gate commands. The signed `runtime_boundary` records that limitation. Treat unknown or hostile candidates as requiring an external locked-down container or VM; the in-repository controls are appropriate only for a trusted gate runtime.

These results mean the automated candidate is ready for commit, Draft PR, and CI—not that R5 passed or release is authorized.
