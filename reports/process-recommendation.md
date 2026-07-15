# Recommended Multi-CLI Software Workflow

## Decision

Use a risk-adaptive workflow, not one fixed multi-agent chain for every task.

### Fast route — small, explicit, independently testable

`Agy implement → format changed files → acceptance → scoped lint → Gitleaks → contract/scope gates`

- Evidence: two valid solo Agy runs scored 100/100 with a median of 110.4 seconds.
- Agy produced the smallest diffs, but failed format gates before deterministic formatting.
- The reusable fast runner passed end to end in `benchmark-fast-pilot-3` at 126.2 model seconds,
  including hidden acceptance after the runner completed.
- Default to no new files. A task requiring new files must pass explicit `--allow-new` globs.

### Standard route — ordinary multi-file feature work

`Claude implement → format changed files → acceptance → scoped quality/security gates`

- Evidence: two solo Claude runs scored 100/100 with a median of 143.2 seconds.
- Claude was slower than Agy but produced cleaner Python formatting in one of two runs.
- Do not add a reviewer by default when the contract is explicit and every mechanical gate is
  strong; the tested reviewer chains cost 3–10 times more without improving functional score.

### High route — core logic, security, data, CI, or cross-platform seams

`Agy plan → Codex implement → interim gates → Claude evidence-bound audit → conditional Codex correction → final gates`

- Benchmark evidence: 100/100, all maintainability gates passed, 470.9 model seconds.
- This was 34% faster than the double-plan tri-model flow and 47% faster than the original
  Codex→Claude→Codex chain.
- SAGE GitHub pilot evidence: the final run used 963.8 model seconds and found a real defect that
  local tests missed. Claude proved the Docker actionlint step could produce a false green because
  `--workdir /repo` was missing. Codex corrected it, then every final gate passed.
- A reviewer may request correction only with both an exact contract quote and a reproducible
  failing input/command. Advisory findings never trigger a model round.

## Evidence gates shared by every route

1. Isolated local clone at a known source commit.
2. SHA-256 lock for `WORKFLOW_TASK.md`.
3. Existing-test hashes; changes require explicit `--allow-test-change`.
4. Existing-file and new-file glob allowlists.
5. At least one user-supplied acceptance command; no empty acceptance set.
6. Deterministic formatter limited to files changed by the task.
7. Ruff/Biome/actionlint limited to changed files, preventing unrelated legacy debt from causing
   false failures.
8. Full-repository Gitleaks scan and `git diff --check`.
9. Raw prompts, outputs, timings, stage diffs, final patch, and JSON gate results retained.
10. Generation routes never commit, push, or open a PR. An explicitly invoked Promotion Gate may
    publish only after replaying acceptance, and it can create only a draft PR with auto-merge off.
11. Promotion rechecks patch SHA-256, source ancestry, new-branch absence, staged-tree immutability,
    draft state, auto-merge state, and every reported GitHub CI check.
12. Every promotable run carries an SSH-signed canonical evidence manifest; GitHub receives a
    separate `SAGE Evidence` commit status only after CI and promotion invariants pass.
13. Machine success is always represented separately from `r5_human_verification=pending` and
    `merge_authorized=false`.

## SAGE 0.9 validation expansion

- Promotion can safely resume only the CI-wait phase. It revalidates the signature, patch, source,
  remote branch OID, draft PR, base/head, and auto-merge state before polling again.
- One ledger preauthorizes model turns, token ceilings, USD ceilings, and total/stage time before
  each CLI call. Visible-I/O token estimates are not presented as provider billing data.
- Language gates are argv-only plugins. Gate discovery was tested against 12 pinned public
  repositories in 12 primary languages without executing external repository code.
- All 12 repositories passed benchmark-validity checks. Ten passed strict Gitleaks; findings in a
  vendored PHP PHAR and C test fixtures remain reported and redacted rather than suppressed.
- The lightweight sprite audit game passed six public and five hidden Node tests plus Biome, HTTP,
  UI structure, acceptance-lock, plugin-discovery, and Gitleaks checks.

## What the experiments rejected

| Candidate | Result | Decision |
|---|---:|---|
| Solo Codex | 100 points, 296.0s | Correct but too slow as the default implementer |
| Codex→Claude→Codex | 100 points, 893.5s | Reject as default; reviewer only found low-severity overengineering |
| Claude→Agy→Claude | 100 points, 479.5–590.0s | Reject as default; review often added no contractual correction |
| Double-plan tri-model | 100 points, 715.1s | Reject duplicate Claude plan; Agy plan covered nearly all requirements |
| Agy→Codex→Claude gated | 100 points, 470.9s | Select for high-risk tasks |
| Vibe Kanban | UI-oriented, not benchmarked headlessly | Optional human control plane, not core evidence engine |
| Claude Squad | Installed and usable; interactive tmux TUI | Optional worktree console; never use experimental autoyes in the core flow |
| Spec Kit | Overlaps SAGE specification layer | Borrow concepts only; avoid a second control plane |
| OpenHands / GitHub Agentic Workflows | Not required for the proven core path | Keep optional and read-only; never grant promotion or R5 authority |

## Installed tooling

- just 1.56.0, hyperfine 1.20.0
- actionlint 1.7.12, ShellCheck 0.11.0
- Gitleaks 8.30.1, pre-commit 4.6.0
- Ruff 0.15.21, Biome 2.5.3
- tmux 3.7b, Claude Squad 1.0.19
- PowerShell 7.6.3 and .NET 10.0.301 for cross-platform SAGE verification

Homebrew also upgraded shared OpenSSL/SQLite dependencies while installing these tools.

## GitHub project integration

- [`BloopAI/vibe-kanban`](https://github.com/BloopAI/vibe-kanban): optional visual planning and
  workspace review layer.
- [`smtg-ai/claude-squad`](https://github.com/smtg-ai/claude-squad): installed optional terminal
  session/worktree manager.
- [`github/spec-kit`](https://github.com/github/spec-kit): reference for multi-harness integration;
  SAGE remains the contract and acceptance authority.
- [`rhysd/actionlint`](https://github.com/rhysd/actionlint),
  [`gitleaks/gitleaks`](https://github.com/gitleaks/gitleaks), and
  [`pre-commit/pre-commit`](https://github.com/pre-commit/pre-commit): deterministic gate layer.

## SAGE pilot history and PR2 consolidation

The tested patch is stored at `runs/pilots/sage-high-pilot-2/final.patch`. It adds:

- macOS/Linux `sage` dispatcher and safe user-level installer;
- Agy-first, legacy-Gemini-fallback crosscheck adapters on Bash and PowerShell;
- expanded Bash/PowerShell selftests and current Agy preflight detection;
- cross-platform GitHub Actions CI with corrected Docker actionlint working directory.

The original Promotion Gate replayed six acceptance commands and created the pilot branch. That
pilot PR is now closed and superseded by
[draft PR2](https://github.com/eason-tien/sage/pull/2), which preserves its history and adds the
unattended knowledge loop, signed Promotion evidence, portable CLI, and consolidated CI.

The current PR2 workflow produces five check runs: the main `test` job on Ubuntu, Bash selftests
on Ubuntu and macOS, PowerShell selftests on Windows, and ShellCheck. The main job includes
actionlint, Gitleaks, Ruff, Biome, unit, fixture, knowledge, CodeGraph, and sprite-audit gates.
A separate signed `SAGE Evidence` status is also green on the last published candidate. PR2
remains draft with `autoMergeRequest=null`; a fresh push must rerun these checks, and review,
human R5, ready-for-review, and merge remain human-owned actions.
